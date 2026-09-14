#!/usr/bin/env python3
"""reminder: the CLI Brice runs to add, list, and cancel reminders.

Each reminder is one JSON file in REMINDERS_DIR. A separate Mac-side clock
watches that folder and fires reminders when they are due (see
scripts/brain_control/schedule.py and the design doc, section 4.1/4.2). This
CLI only validates and writes files; it never sends anything itself.
"""

import argparse
import json
import os
import secrets
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.environ.get("BRAIN_CONTROL_LIB", os.path.dirname(os.path.abspath(__file__))))
from brain_control import schedule  # noqa: E402

MAX_REMINDERS = 100


class _JSONArgumentParser(argparse.ArgumentParser):
    """An ArgumentParser whose usage errors come out as our JSON error shape.

    argparse's default behavior on a bad flag is to print plain text to
    stderr and call sys.exit(2). Brice only ever reads stdout as JSON, so a
    plain-text usage error would look like a crash instead of a normal
    "you gave me something invalid" reply.
    """

    def __init__(self, *args, **kwargs):
        self._out = kwargs.pop("out", sys.stdout)
        super(_JSONArgumentParser, self).__init__(*args, **kwargs)

    def error(self, message):
        _print_error(self._out, message)
        raise SystemExit(2)


def _print_json(out, obj):
    out.write(json.dumps(obj) + "\n")


def _print_error(out, message):
    _print_json(out, {"ok": False, "error": message})


def _build_schedule_group(parser):
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--at", help="ISO 8601 datetime for a one-off reminder")
    group.add_argument("--daily", metavar="HH:MM", help="fire every day at this time")
    group.add_argument("--weekly", nargs=2, metavar=("DAYS", "HH:MM"),
                        help="fire on these comma-separated weekdays at this time")


def _schedule_from_args(args):
    if args.at is not None:
        return {"type": "once", "at": args.at}
    if args.daily is not None:
        return {"type": "daily", "time": args.daily}
    days_str, time_str = args.weekly
    days = [d.strip() for d in days_str.split(",") if d.strip()]
    return {"type": "weekly", "days": days, "time": time_str}


def _add_common_args(subparser):
    subparser.add_argument("--to", action="append", required=True, metavar="H")
    subparser.add_argument("--name", required=True)
    subparser.add_argument("--tz", default=None)
    subparser.add_argument("--late-limit", type=int, default=None, dest="late_limit")


def _build_parser(out):
    # parser_class defaults to type(parser), so every add_parser() below
    # already builds a _JSONArgumentParser; passing out= wires each
    # subparser's errors to the same output stream as the top-level one.
    parser = _JSONArgumentParser(prog="reminder", out=out)
    sub = parser.add_subparsers(dest="command")

    add_text = sub.add_parser("add-text", out=out)
    add_text.add_argument("--text", required=True)
    _add_common_args(add_text)
    _build_schedule_group(add_text)

    add_smart = sub.add_parser("add-smart", out=out)
    add_smart.add_argument("--prompt", required=True)
    _add_common_args(add_smart)
    _build_schedule_group(add_smart)

    sub.add_parser("list", out=out)

    cancel = sub.add_parser("cancel", out=out)
    cancel.add_argument("id")

    return parser


def _env_dirs(env):
    reminders_dir = env.get("REMINDERS_DIR") or "/home/node/.openclaw/workspace/reminders"
    reminders_tmp = env.get("REMINDERS_TMP") or "/home/node/.openclaw/tmp"
    return reminders_dir, reminders_tmp


def _count_reminders(reminders_dir):
    if not os.path.isdir(reminders_dir):
        return 0
    return len([f for f in os.listdir(reminders_dir) if f.endswith(".json")])


def _do_add(kind, args, env, now, out):
    allow_raw = env.get("IMESSAGE_ALLOW_FROM")
    if not allow_raw:
        _print_error(out, "IMESSAGE_ALLOW_FROM is not set")
        return 1
    allow = schedule.parse_allowlist(allow_raw)

    reminders_dir, reminders_tmp = _env_dirs(env)

    sched = _schedule_from_args(args)
    if sched["type"] == "once":
        try:
            at_dt = schedule.parse_iso(sched["at"])
        except schedule.ReminderError as exc:
            _print_error(out, str(exc))
            return 1
        if at_dt <= now:
            _print_error(out, "time is in the past")
            return 1

    rem_id = schedule.make_id(now, secrets.token_hex(2))
    data = {
        "id": rem_id,
        "kind": kind,
        "name": args.name,
        "to": args.to,
        "schedule": sched,
        "created_at": schedule.to_iso_utc(now),
        "created_by": "brice",
    }
    if kind == "text":
        data["text"] = args.text
    else:
        data["prompt"] = args.prompt
    if args.tz is not None:
        data["tz"] = args.tz
    if args.late_limit is not None:
        data["late_limit_minutes"] = args.late_limit

    try:
        normalized = schedule.validate(data, allow)
    except schedule.ReminderError as exc:
        _print_error(out, str(exc))
        return 1

    if _count_reminders(reminders_dir) >= MAX_REMINDERS:
        _print_error(out, "too many reminders (limit %d)" % MAX_REMINDERS)
        return 1

    try:
        os.makedirs(reminders_dir, exist_ok=True)
        os.makedirs(reminders_tmp, exist_ok=True)
    except OSError as exc:
        _print_error(out, "could not create reminder directories: %s" % (exc,))
        return 1

    tmp_path = os.path.join(reminders_tmp, rem_id + ".json.tmp-" + secrets.token_hex(4))
    final_path = os.path.join(reminders_dir, rem_id + ".json")
    try:
        with open(tmp_path, "w") as f:
            json.dump(normalized, f)
        os.replace(tmp_path, final_path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    nr = schedule.next_run(normalized, now)
    next_run_str = None
    if nr is not None:
        manila = nr.astimezone(schedule.ZoneInfo(schedule.DEFAULT_TZ))
        next_run_str = manila.strftime("%Y-%m-%d %H:%M")

    _print_json(out, {"ok": True, "id": rem_id, "next_run": next_run_str})
    return 0


def _do_list(env, now, out):
    reminders_dir, _ = _env_dirs(env)
    reminders = []
    if os.path.isdir(reminders_dir):
        for fname in sorted(os.listdir(reminders_dir)):
            if not fname.endswith(".json"):
                continue
            file_id = fname[:-len(".json")]
            path = os.path.join(reminders_dir, fname)
            try:
                with open(path) as f:
                    data = json.load(f)
                normalized = schedule.validate(data, allow=None, file_id=file_id)
            except (schedule.ReminderError, ValueError, OSError):
                reminders.append({"file": fname, "invalid": True})
                continue
            nr = schedule.next_run(normalized, now)
            next_run_str = None
            if nr is not None:
                manila = nr.astimezone(schedule.ZoneInfo(schedule.DEFAULT_TZ))
                next_run_str = manila.strftime("%Y-%m-%d %H:%M")
            reminders.append({
                "id": normalized["id"],
                "kind": normalized["kind"],
                "name": normalized["name"],
                "to_count": len(normalized["to"]),
                "schedule": normalized["schedule"],
                "next_run": next_run_str,
            })
    _print_json(out, {"ok": True, "reminders": reminders})
    return 0


def _do_cancel(rem_id, env, out):
    if not schedule.ID_RE.fullmatch(rem_id):
        _print_error(out, "invalid reminder id")
        return 1
    reminders_dir, _ = _env_dirs(env)
    path = os.path.join(reminders_dir, rem_id + ".json")
    if not os.path.isfile(path):
        _print_error(out, "no such reminder")
        return 1
    os.remove(path)
    _print_json(out, {"ok": True})
    return 0


def main(argv, env, now=None, out=sys.stdout):
    if now is None:
        now = datetime.now(timezone.utc)

    parser = _build_parser(out)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2

    if args.command is None:
        _print_error(out, "no command given")
        return 2

    try:
        if args.command == "add-text":
            return _do_add("text", args, env, now, out)
        if args.command == "add-smart":
            return _do_add("smart", args, env, now, out)
        if args.command == "list":
            return _do_list(env, now, out)
        if args.command == "cancel":
            return _do_cancel(args.id, env, out)
    except schedule.ReminderError as exc:
        _print_error(out, str(exc))
        return 1

    _print_error(out, "unknown command: %s" % (args.command,))
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:], dict(os.environ)))
