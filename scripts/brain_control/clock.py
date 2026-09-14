"""The reminder clock step, run once per launchd tick (spec section 4.3).

Reads reminder JSON files from a synced folder, works out which are due
using schedule.py, and calls the sender functions it is given. It never
does network I/O itself and never touches chat.db: those live in the real
senders that a later task wires in. This module only reads and deletes
reminder files, and mutates the state dict it is handed.
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


def _file_hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


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

    today = _manila_date(now)
    sent_today = st["sent_today"]
    if sent_today.get("date") != today:
        sent_today["date"] = today
        sent_today["count"] = 0

    tick_count = 0
    skipped_names = []

    def limit_reached():
        return tick_count >= MAX_PER_TICK or sent_today["count"] >= MAX_PER_DAY

    filenames = sorted(f for f in os.listdir(reminders_dir) if f.endswith(".json"))
    seen_ids = set()

    for filename in filenames:
        file_id = filename[:-len(".json")]
        path = os.path.join(reminders_dir, filename)
        try:
            with open(path, "rb") as f:
                raw = f.read()
        except FileNotFoundError:
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

        seen_ids.add(rem["id"])
        rem_id = rem["id"]
        last_done_dt = schedule.parse_iso(last_done[rem_id]) if rem_id in last_done else None
        slot = schedule.due_slot(rem, now, last_done_dt)
        if slot is None:
            continue

        outcome = schedule.decide(rem, slot, now)
        is_once = rem["schedule"]["type"] == "once"

        if outcome == "skip":
            last_done[rem_id] = schedule.to_iso_utc(slot)
            partial.pop(rem_id, None)
            skipped_names.append(rem["name"])
            if is_once:
                _delete(path)
            log("skip", rem_id)
            continue

        late = outcome == "late"

        if rem["kind"] == "text":
            entry = partial.get(rem_id)
            if entry is not None and entry.get("slot") == schedule.to_iso_utc(slot):
                done = list(entry.get("done", []))
            else:
                done = []
            done_set = set(done)
            text = ("(late) " if late else "") + rem["text"]

            all_sent = True
            for handle in rem["to"]:
                if handle in done_set:
                    continue
                if limit_reached():
                    all_sent = False
                    break
                ok = send_text(handle, text)
                if ok:
                    done_set.add(handle)
                    done.append(handle)
                    tick_count += 1
                    sent_today["count"] += 1
                else:
                    all_sent = False

            if all_sent and len(done_set) >= len(rem["to"]):
                last_done[rem_id] = schedule.to_iso_utc(slot)
                partial.pop(rem_id, None)
                if is_once:
                    _delete(path)
            else:
                partial[rem_id] = {"slot": schedule.to_iso_utc(slot), "done": done}
        else:
            if limit_reached():
                continue
            payload = smart_payload(rem, slot, late)
            ok = send_smart(lease, payload)
            if ok:
                tick_count += 1
                sent_today["count"] += 1
                last_done[rem_id] = schedule.to_iso_utc(slot)
                partial.pop(rem_id, None)
                if is_once:
                    _delete(path)

    if skipped_names:
        notify_mark("Skipped late reminders: " + ", ".join(skipped_names))

    _sweep_gone(last_done, partial, gone, filenames, now)


def _sweep_gone(last_done: Dict, partial: Dict, gone: Dict, filenames, now: datetime) -> None:
    present_ids = set(f[:-len(".json")] for f in filenames)
    tracked_ids = set(last_done.keys()) | set(partial.keys())
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


def _delete(path: str) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
