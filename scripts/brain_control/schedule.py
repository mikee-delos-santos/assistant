"""Validation and slot math for reminder files.

A reminder file describes a repeating or one-off send (see the design doc,
section 4.1). This module turns raw dict data into a normalized reminder,
and works out when a reminder is due to fire. It has no side effects: it
never reads or writes files, and never sends anything. The clock and the
reminder CLI both build on top of it.
"""

import re
from datetime import datetime, timedelta, timezone

from typing import Dict, List, Optional, Set

from zoneinfo import ZoneInfo

DEFAULT_TZ = "Asia/Manila"
DEFAULT_LATE_LIMIT = 120  # minutes
LATE_MARK_AFTER = timedelta(minutes=2)
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
ID_RE = re.compile(r"^r-[0-9A-Za-z-]{1,60}$")

UTC = timezone.utc

# How far back a recurring schedule looks for a due slot. One week plus a
# little slack, so a weekly reminder is always found even if a tick is
# missed for a few days.
_LOOKBACK_DAYS = 8

_TOP_LEVEL_KEYS = {
    "version", "id", "kind", "name", "to", "text", "prompt",
    "schedule", "tz", "late_limit_minutes", "created_at", "created_by",
}
_SCHEDULE_KEYS = {
    "once": {"type", "at"},
    "daily": {"type", "time"},
    "weekly": {"type", "days", "time"},
}


class ReminderError(ValueError):
    """Raised for any malformed or disallowed reminder data."""


def parse_iso(value: str) -> datetime:
    """Parse an ISO 8601 string into an aware UTC datetime.

    Accepts a trailing "Z" (which Python's fromisoformat does not, on
    3.9/3.11). Rejects naive strings and anything else that fails to parse,
    since a naive time is ambiguous about which timezone it means.
    """
    if not isinstance(value, str) or not value:
        raise ReminderError("expected an ISO 8601 datetime string")
    text = value
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise ReminderError("bad ISO 8601 datetime: %r" % (value,))
    if dt.tzinfo is None:
        raise ReminderError("datetime must include a timezone offset: %r" % (value,))
    return dt.astimezone(UTC)


def to_iso_utc(dt: datetime) -> str:
    """Format an aware datetime as UTC ISO 8601 with a "Z" suffix."""
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_handle(handle: str) -> str:
    """Normalize a phone number or email for allowlist comparison.

    Phone numbers keep only their digits and a leading "+" (spaces,
    dashes, and parens are formatting, not identity). Emails are
    lowercased. Anything blank is an error, since a blank handle would
    silently match nothing (or everything) downstream.
    """
    if not isinstance(handle, str):
        raise ReminderError("handle must be a string")
    stripped = handle.strip()
    if not stripped:
        raise ReminderError("handle must not be empty")
    if "@" in stripped:
        return stripped.lower()
    cleaned = re.sub(r"[\s()-]", "", stripped)
    if not cleaned:
        raise ReminderError("handle must not be empty")
    return cleaned


def parse_allowlist(raw: str) -> Set[str]:
    """Parse a comma/newline-separated allowlist string into a set.

    Entries split on commas and newlines, not on every space, because a
    phone number entry can itself contain spaces as formatting (e.g.
    "+63 917 000 0001") that normalize_handle strips away.
    """
    if not raw:
        return set()
    parts = re.split(r"[,\n]+", raw.strip())
    return set(normalize_handle(p.strip()) for p in parts if p.strip())


def _require(cond: bool, message: str) -> None:
    if not cond:
        raise ReminderError(message)


def _validate_schedule(schedule) -> Dict:
    _require(isinstance(schedule, dict), "schedule must be an object")
    sched_type = schedule.get("type")
    _require(sched_type in _SCHEDULE_KEYS, "schedule.type must be once, daily, or weekly")
    allowed_keys = _SCHEDULE_KEYS[sched_type]
    unknown = set(schedule.keys()) - allowed_keys
    _require(not unknown, "unknown schedule keys: %s" % sorted(unknown))

    if sched_type == "once":
        at = schedule.get("at")
        _require(isinstance(at, str) and at, "schedule.at is required for a once reminder")
        # parse_iso already rejects a naive datetime; "with offset" means
        # exactly that, no bare local time.
        parse_iso(at)
        return {"type": "once", "at": at}

    time_str = schedule.get("time")
    _require(isinstance(time_str, str), "schedule.time is required")
    m = re.match(r"^([0-9]{2}):([0-9]{2})$", time_str or "")
    _require(bool(m), "schedule.time must be HH:MM")
    hh, mm = int(m.group(1)), int(m.group(2))
    _require(0 <= hh <= 23 and 0 <= mm <= 59, "schedule.time out of range")

    if sched_type == "daily":
        return {"type": "daily", "time": time_str}

    days = schedule.get("days")
    _require(isinstance(days, list) and len(days) > 0, "schedule.days must be a non-empty list")
    for d in days:
        _require(d in DAYS, "unknown weekday: %r" % (d,))
    return {"type": "weekly", "days": list(days), "time": time_str}


def validate(data: Dict, allow: Optional[Set[str]] = None, file_id: Optional[str] = None) -> Dict:
    """Validate a raw reminder dict and return a new normalized copy.

    Fills in defaults (tz, late_limit_minutes, prompt/text None) and
    enforces the rules from the design doc, section 4.1. Unknown top-level
    keys are an error so a typo never silently changes behavior. When
    file_id is given it must equal data["id"], since the file name and the
    id inside the file are meant to always agree. When allow is given,
    every "to" handle (after normalizing) must be in it.
    """
    _require(isinstance(data, dict), "reminder data must be an object")
    unknown = set(data.keys()) - _TOP_LEVEL_KEYS
    _require(not unknown, "unknown reminder keys: %s" % sorted(unknown))

    rem_id = data.get("id")
    _require(isinstance(rem_id, str) and bool(ID_RE.match(rem_id)), "invalid reminder id: %r" % (rem_id,))
    if file_id is not None:
        _require(rem_id == file_id, "id %r does not match file name %r" % (rem_id, file_id))

    kind = data.get("kind")
    _require(kind in ("text", "smart"), "kind must be text or smart")

    name = data.get("name")
    _require(isinstance(name, str) and bool(name), "name is required")

    to = data.get("to")
    _require(isinstance(to, list) and len(to) >= 1, "to must be a non-empty list")
    max_to = 5 if kind == "text" else 1
    _require(len(to) <= max_to, "to has too many recipients for kind %r" % (kind,))
    normalized_to = [normalize_handle(h) for h in to]
    if allow is not None:
        for h in normalized_to:
            _require(h in allow, "recipient %r is not in the allowlist" % (h,))

    text = data.get("text")
    prompt = data.get("prompt")
    if kind == "text":
        _require(isinstance(text, str) and 1 <= len(text) <= 1000, "text must be 1-1000 chars for kind text")
        _require(prompt is None, "prompt must not be set for kind text")
    else:
        _require(isinstance(prompt, str) and 1 <= len(prompt) <= 2000, "prompt must be 1-2000 chars for kind smart")
        _require(text is None, "text must not be set for kind smart")

    tz = data.get("tz", DEFAULT_TZ)
    _require(isinstance(tz, str) and bool(tz), "tz must be a non-empty string")
    try:
        ZoneInfo(tz)
    except Exception:
        raise ReminderError("unknown tz: %r" % (tz,))

    late_limit = data.get("late_limit_minutes", DEFAULT_LATE_LIMIT)
    _require(isinstance(late_limit, int) and not isinstance(late_limit, bool), "late_limit_minutes must be an int")
    _require(0 <= late_limit <= 1440, "late_limit_minutes must be 0-1440")

    created_at = data.get("created_at")
    _require(isinstance(created_at, str) and bool(created_at), "created_at is required")
    parse_iso(created_at)  # raises ReminderError if malformed

    created_by = data.get("created_by")
    _require(isinstance(created_by, str) and bool(created_by), "created_by is required")

    schedule = _validate_schedule(data.get("schedule"))

    version = data.get("version", 1)

    return {
        "version": version,
        "id": rem_id,
        "kind": kind,
        "name": name,
        "to": normalized_to,
        "text": text,
        "prompt": prompt,
        "schedule": schedule,
        "tz": tz,
        "late_limit_minutes": late_limit,
        "created_at": created_at,
        "created_by": created_by,
    }


def _slot_for_daily(local_date, time_str: str, tz: ZoneInfo) -> datetime:
    hh, mm = [int(x) for x in time_str.split(":")]
    local_dt = datetime(local_date.year, local_date.month, local_date.day, hh, mm, tzinfo=tz)
    return local_dt.astimezone(UTC)


def occurrences_between(rem: Dict, start: datetime, end: datetime) -> List[datetime]:
    """All slots s with start < s <= end, as aware UTC datetimes, ascending.

    start and end may be given in any timezone; they are compared as
    absolute instants.
    """
    _require(start.tzinfo is not None and end.tzinfo is not None, "start/end must be aware datetimes")
    sched = rem["schedule"]
    tz = ZoneInfo(rem["tz"])

    if sched["type"] == "once":
        at = parse_iso(sched["at"])
        return [at] if (start < at <= end) else []

    results = []
    start_local = start.astimezone(tz)
    end_local = end.astimezone(tz)
    day = start_local.date() - timedelta(days=1)
    last_day = end_local.date() + timedelta(days=1)
    while day <= last_day:
        if sched["type"] == "daily" or (sched["type"] == "weekly" and DAYS[day.weekday()] in sched["days"]):
            slot = _slot_for_daily(day, sched["time"], tz)
            if start < slot <= end:
                results.append(slot)
        day += timedelta(days=1)
    results.sort()
    return results


def due_slot(rem: Dict, now: datetime, last_done: Optional[datetime]) -> Optional[datetime]:
    """The latest slot s with s <= now, s > created_at, and s > last_done.

    Returns None when no such slot exists. Looks back at most
    _LOOKBACK_DAYS days, which comfortably covers a weekly schedule even
    if ticks were missed for a while.
    """
    created_at = parse_iso(rem["created_at"])
    lower_bound = created_at
    if last_done is not None and last_done > lower_bound:
        lower_bound = last_done

    sched = rem["schedule"]
    if sched["type"] == "once":
        at = parse_iso(sched["at"])
        if lower_bound < at <= now:
            return at
        return None

    window_start = now - timedelta(days=_LOOKBACK_DAYS)
    if lower_bound > window_start:
        window_start = lower_bound
    slots = occurrences_between(rem, window_start, now)
    return slots[-1] if slots else None


def next_run(rem: Dict, now: datetime) -> Optional[datetime]:
    """The first slot strictly after now, or None if there isn't one."""
    sched = rem["schedule"]
    if sched["type"] == "once":
        at = parse_iso(sched["at"])
        return at if at > now else None

    window_end = now + timedelta(days=_LOOKBACK_DAYS)
    slots = occurrences_between(rem, now, window_end)
    return slots[0] if slots else None


def decide(rem: Dict, slot: datetime, now: datetime) -> str:
    """"skip" once too late, "late" if a little late, else "send"."""
    late_limit = timedelta(minutes=rem["late_limit_minutes"])
    lateness = now - slot
    if lateness > late_limit:
        return "skip"
    if lateness > LATE_MARK_AFTER:
        return "late"
    return "send"


def make_id(now: datetime, rand_hex: str) -> str:
    """Build a reminder id from a creation time and a random hex suffix."""
    stamp = now.astimezone(UTC).strftime("%Y%m%dT%H%M%S")
    return "r-%s-%s" % (stamp, rand_hex)
