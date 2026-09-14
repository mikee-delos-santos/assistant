"""The reminder clock step, run once per launchd tick (spec section 4.3).

Reads reminder JSON files from a synced folder, works out which are due
using schedule.py, and calls the sender functions it is given. It never
does network I/O itself and never touches chat.db: those live in the real
senders that a later task wires in. This module only reads and deletes
reminder files, and mutates the state dict it is handed.

One bad reminder (a sender that raises, a file that can't be opened, a
delete that fails) must never stop the rest of the tick from running, so
every per-reminder step that can fail is caught and logged instead of
propagated.
"""

import hashlib
import json
import os
from datetime import datetime, timedelta
from typing import Callable, Dict, Set

from . import schedule

MAX_PER_TICK = 10
MAX_PER_DAY = 60
GONE_KEEP = timedelta(days=7)
MAX_ATTEMPTS = 6
BACKOFF_MINUTES = [1, 2, 4, 8, 15]  # the last value repeats for later attempts

MANILA = schedule.ZoneInfo("Asia/Manila")


def _manila_date(now: datetime) -> str:
    return now.astimezone(MANILA).strftime("%Y-%m-%d")


def smart_payload(rem: Dict, slot: datetime, late: bool) -> Dict:
    local_slot = slot.astimezone(schedule.ZoneInfo(rem["tz"]))
    lines = [
        "Scheduled job: %s" % rem["name"],
        "Scheduled for: %s" % local_slot.strftime("%Y-%m-%d %H:%M"),
    ]
    if late:
        lines.append("(This job is running late.)")
    to = rem["to"][0]
    lines.append("Send your final answer as one iMessage to %s." % to)
    lines.append("")
    lines.append(rem["prompt"])
    return {
        "message": "\n".join(lines),
        "name": rem["name"],
        "deliver": True,
        "channel": "imessage",
        "to": to,
        "idempotencyKey": rem["id"] + ":" + schedule.to_iso_utc(slot),
    }


def _ensure_state(st: Dict) -> None:
    st.setdefault("last_done", {})
    st.setdefault("partial", {})
    st.setdefault("sent_today", {"date": "", "count": 0})
    st.setdefault("invalid_seen", {})
    st.setdefault("gone", {})
    st.setdefault("attempts", {})


def _file_hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _dedupe(handles):
    """Unique handles, first-occurrence order kept.

    validate() normalizes handles but does not reject duplicates (two
    spellings of the same number can both end up in "to"), so completion
    checks must compare against this, not the raw list.
    """
    seen = set()
    out = []
    for h in handles:
        if h not in seen:
            seen.add(h)
            out.append(h)
    return out


def _next_backoff_iso(now: datetime, n: int) -> str:
    idx = min(n - 1, len(BACKOFF_MINUTES) - 1)
    return schedule.to_iso_utc(now + timedelta(minutes=BACKOFF_MINUTES[idx]))


def run(reminders_dir: str, st: Dict, now: datetime, lease: str, allow: Set[str],
        send_text: Callable[[str, str], bool],
        send_smart: Callable[[str, dict], bool],
        notify_mark: Callable[[str], bool],
        log: Callable[[str, str], None]) -> None:
    if not os.path.isdir(reminders_dir):
        return

    _ensure_state(st)
    last_done = st["last_done"]
    partial = st["partial"]
    invalid_seen = st["invalid_seen"]
    gone = st["gone"]
    attempts = st["attempts"]

    today = _manila_date(now)
    sent_today = st["sent_today"]
    if sent_today.get("date") != today:
        sent_today["date"] = today
        sent_today["count"] = 0

    counters = {"tick": 0}

    def limit_reached():
        return counters["tick"] >= MAX_PER_TICK or sent_today["count"] >= MAX_PER_DAY

    def record_attempt():
        counters["tick"] += 1
        sent_today["count"] += 1

    skipped_names = []
    failed_names = []

    filenames = sorted(f for f in os.listdir(reminders_dir) if f.endswith(".json"))

    for filename in filenames:
        file_id = filename[:-len(".json")]
        path = os.path.join(reminders_dir, filename)

        try:
            with open(path, "rb") as f:
                raw = f.read()
        except OSError:
            # Missing, a directory, or unreadable: treat like a malformed
            # file rather than letting the tick crash on one bad entry.
            marker = "unreadable"
            if invalid_seen.get(filename) != marker:
                invalid_seen[filename] = marker
                log("invalid", filename)
            continue

        try:
            data = json.loads(raw.decode("utf-8"))
            rem = schedule.validate(data, allow=allow, file_id=file_id)
        except (ValueError, schedule.ReminderError):
            digest = _file_hash(raw)
            if invalid_seen.get(filename) != digest:
                invalid_seen[filename] = digest
                log("invalid", filename)
            continue

        rem_id = rem["id"]
        try:
            _process_reminder(
                rem, rem_id, path, now, last_done, partial, attempts,
                limit_reached, record_attempt, send_text, send_smart, lease,
                skipped_names, failed_names, log,
            )
        except Exception as e:
            # A bug here (ours, not the sender's - those are caught inside
            # _process_reminder) must not take down the rest of the tick.
            log("error", "%s %s" % (rem_id, type(e).__name__))
            continue

    if skipped_names:
        notify_mark("Skipped late reminders: " + ", ".join(skipped_names))
    if failed_names:
        notify_mark("Failed reminders: " + ", ".join(failed_names))

    _sweep_gone(last_done, partial, attempts, gone, filenames, now)


def _process_reminder(rem, rem_id, path, now, last_done, partial, attempts,
                       limit_reached, record_attempt, send_text, send_smart,
                       lease, skipped_names, failed_names, log):
    last_done_dt = schedule.parse_iso(last_done[rem_id]) if rem_id in last_done else None
    slot = schedule.due_slot(rem, now, last_done_dt)
    if slot is None:
        return

    slot_iso = schedule.to_iso_utc(slot)
    outcome = schedule.decide(rem, slot, now)
    is_once = rem["schedule"]["type"] == "once"

    if outcome == "skip":
        last_done[rem_id] = slot_iso
        partial.pop(rem_id, None)
        attempts.pop(rem_id, None)
        skipped_names.append(rem["name"])
        if is_once:
            _delete(path, rem_id, log)
        log("skip", rem_id)
        return

    late = outcome == "late"

    entry = attempts.get(rem_id)
    if entry is None or entry.get("slot") != slot_iso:
        entry = {"slot": slot_iso, "per": {}}
        attempts[rem_id] = entry
    per_handle = entry["per"]

    if rem["kind"] == "text":
        _run_text(rem, rem_id, path, slot_iso, now, late, is_once, last_done,
                   partial, attempts, per_handle, limit_reached, record_attempt,
                   send_text, failed_names, log)
    else:
        _run_smart(rem, rem_id, path, slot, slot_iso, now, late, is_once,
                    last_done, partial, attempts, per_handle, limit_reached,
                    record_attempt, send_smart, lease, failed_names, log)


def _due_for_retry(att, now):
    next_at = att.get("next")
    if next_at is None:
        return True
    return now >= schedule.parse_iso(next_at)


def _run_text(rem, rem_id, path, slot_iso, now, late, is_once, last_done,
              partial, attempts, per_handle, limit_reached, record_attempt,
              send_text, failed_names, log):
    unique_to = _dedupe(rem["to"])

    prior = partial.get(rem_id)
    if prior is not None and prior.get("slot") == slot_iso:
        done = list(prior.get("done", []))
    else:
        done = []
    done_set = set(done)

    text = ("(late) " if late else "") + rem["text"]
    already_failed = False
    stopped_on_limit = False

    for handle in unique_to:
        if handle in done_set:
            continue

        att = per_handle.get(handle, {"n": 0, "next": None})
        if att["n"] >= MAX_ATTEMPTS:
            done_set.add(handle)
            done.append(handle)
            if not already_failed:
                failed_names.append(rem["name"])
                already_failed = True
            continue

        if not _due_for_retry(att, now):
            continue

        if limit_reached():
            stopped_on_limit = True
            break

        try:
            ok = send_text(handle, text)
        except Exception:
            ok = False
        record_attempt()

        if ok:
            done_set.add(handle)
            done.append(handle)
            per_handle.pop(handle, None)
        else:
            n = att["n"] + 1
            if n >= MAX_ATTEMPTS:
                done_set.add(handle)
                done.append(handle)
                per_handle.pop(handle, None)
                if not already_failed:
                    failed_names.append(rem["name"])
                    already_failed = True
            else:
                per_handle[handle] = {"n": n, "next": _next_backoff_iso(now, n)}

        # Persist as we go so a later crash in this same reminder (or the
        # process dying) never loses an attempt that already happened.
        partial[rem_id] = {"slot": slot_iso, "done": done}

    if len(done_set) >= len(unique_to):
        last_done[rem_id] = slot_iso
        partial.pop(rem_id, None)
        attempts.pop(rem_id, None)
        if is_once:
            _delete(path, rem_id, log)
    elif not stopped_on_limit:
        # Every remaining handle is just waiting out its backoff.
        partial[rem_id] = {"slot": slot_iso, "done": done}


def _run_smart(rem, rem_id, path, slot, slot_iso, now, late, is_once,
                last_done, partial, attempts, per_handle, limit_reached,
                record_attempt, send_smart, lease, failed_names, log):
    handle = rem["to"][0]
    att = per_handle.get(handle, {"n": 0, "next": None})

    if att["n"] >= MAX_ATTEMPTS:
        failed_names.append(rem["name"])
        last_done[rem_id] = slot_iso
        partial.pop(rem_id, None)
        attempts.pop(rem_id, None)
        if is_once:
            _delete(path, rem_id, log)
        return

    if not _due_for_retry(att, now):
        return

    if limit_reached():
        return

    payload = smart_payload(rem, slot, late)
    try:
        ok = send_smart(lease, payload)
    except Exception:
        ok = False
    record_attempt()

    if ok:
        last_done[rem_id] = slot_iso
        partial.pop(rem_id, None)
        attempts.pop(rem_id, None)
        if is_once:
            _delete(path, rem_id, log)
        return

    n = att["n"] + 1
    if n >= MAX_ATTEMPTS:
        failed_names.append(rem["name"])
        last_done[rem_id] = slot_iso
        partial.pop(rem_id, None)
        attempts.pop(rem_id, None)
        if is_once:
            _delete(path, rem_id, log)
    else:
        per_handle[handle] = {"n": n, "next": _next_backoff_iso(now, n)}


def _sweep_gone(last_done: Dict, partial: Dict, attempts: Dict, gone: Dict,
                 filenames, now: datetime) -> None:
    present_ids = set(f[:-len(".json")] for f in filenames)
    tracked_ids = set(last_done.keys()) | set(partial.keys()) | set(attempts.keys())
    missing_ids = tracked_ids - present_ids

    for rem_id in list(gone.keys()):
        if rem_id not in missing_ids:
            del gone[rem_id]

    for rem_id in missing_ids:
        if rem_id not in gone:
            gone[rem_id] = schedule.to_iso_utc(now)
            continue
        first_seen = schedule.parse_iso(gone[rem_id])
        if now - first_seen > GONE_KEEP:
            gone.pop(rem_id, None)
            last_done.pop(rem_id, None)
            partial.pop(rem_id, None)
            attempts.pop(rem_id, None)


def _delete(path: str, rem_id: str, log: Callable[[str, str], None]) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except OSError:
        log("delete_failed", rem_id)
