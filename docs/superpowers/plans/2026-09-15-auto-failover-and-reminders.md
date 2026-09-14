# Automatic failover and shared reminders - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Mac launchd tick that keeps exactly one brain talking (lease + gate fencing) and fires reminders stored as synced files.

**Architecture:** Pure logic modules (`schedule`, `failover`, `clock`) with injected I/O, one I/O module (`senders`), one entry point (`main`). The gate gains `--brain` fencing. Brice gets a `reminder` CLI in the image.

**Tech Stack:** Python standard library only. `unittest`. launchd. Docker Compose. OpenClaw `/hooks/agent`.

**Spec:** `docs/superpowers/specs/2026-09-15-auto-failover-and-reminders-design.md` (read it first).

## Global Constraints

- Code must run on Mac `/usr/bin/python3` 3.9 AND Debian python 3.11. No `match`, no `X | Y` type syntax, no third-party packages. Use `from typing import Optional, Dict, List`.
- `zoneinfo` is available on both (3.9+). Default tz `Asia/Manila`.
- Never log message text or handles. Log event names, ids, counts.
- No ticket IDs in code comments. Comments explain why, in plain English.
- All file writes that other processes read are atomic: write temp in the same directory, then `os.replace`.
- Run tests from repo root: `cd scripts && /usr/bin/python3 -m unittest discover -s tests -t . -v`
- Commit after each task. Subject format: `AS-3 | <what>`.

## File map

```
scripts/brain_control/__init__.py      empty
scripts/brain_control/schedule.py      Task 1  pure: validate reminders, due slots, late/skip
scripts/brain_control/failover.py      Task 3  pure: state machine -> Actions
scripts/brain_control/clock.py         Task 4  reminder step with injected senders
scripts/brain_control/senders.py       Task 5  real I/O
scripts/brain_control/main.py          Task 5  one tick
scripts/brain-control.plist            Task 5  launchd template
scripts/install-brain-control.sh       Task 5  Mac installer (Mark runs it)
scripts/imsg-ssh-gate.py               Task 2  --brain fencing
scripts/reminder.py                    Task 6  Brice CLI
Dockerfile.imsg, docker-compose.yml    Task 6
scripts/tests/test_schedule.py         Task 1
scripts/tests/test_gate_fencing.py     Task 2
scripts/tests/test_failover.py         Task 3
scripts/tests/test_clock.py            Task 4
scripts/tests/test_main.py             Task 5
scripts/tests/test_reminder_cli.py     Task 6
```

Order: Task 1 first. Then Tasks 2, 3, 6 can run in parallel (6 needs only Task 1). Task 4 needs 1. Task 5 needs 3 and 4.

---

### Task 1: schedule.py

**Files:** Create `scripts/brain_control/__init__.py` (empty), `scripts/brain_control/schedule.py`, `scripts/tests/__init__.py` (empty), `scripts/tests/test_schedule.py`.

**Interfaces (Produces):**

```python
DEFAULT_TZ = "Asia/Manila"
DEFAULT_LATE_LIMIT = 120          # minutes
LATE_MARK_AFTER = timedelta(minutes=2)
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
ID_RE = re.compile(r"^r-[0-9A-Za-z-]{1,60}$")

class ReminderError(ValueError): ...

def parse_iso(value: str) -> datetime
    # aware datetime; accepts trailing "Z"; raises ReminderError if naive or bad
def to_iso_utc(dt: datetime) -> str
    # "2026-09-15T01:30:00Z"
def normalize_handle(handle: str) -> str
    # strip spaces/dashes/parens for phone numbers ("+63 917-123" -> "+63917123"),
    # lowercase emails; raises ReminderError if empty
def parse_allowlist(raw: str) -> set
    # split on commas/whitespace, normalize each; empty string -> empty set
def validate(data: dict, allow: Optional[set] = None, file_id: Optional[str] = None) -> dict
    # returns a NEW normalized dict with defaults filled (tz, late_limit_minutes, prompt/text None)
    # rules exactly as spec 4.1; unknown keys -> error; file_id given -> must equal data["id"]
    # allow given -> every "to" (normalized) must be in allow
def occurrences_between(rem: dict, start: datetime, end: datetime) -> List[datetime]
    # all slots s with start < s <= end, as aware UTC datetimes, ascending
def due_slot(rem: dict, now: datetime, last_done: Optional[datetime]) -> Optional[datetime]
    # latest slot s with s <= now, s > created_at, s > last_done (if given); else None
    # recurring: look back at most 8 days (enough for weekly)
def next_run(rem: dict, now: datetime) -> Optional[datetime]
    # first slot > now (once: at if at > now else None)
def decide(rem: dict, slot: datetime, now: datetime) -> str
    # "skip" if now - slot > late_limit_minutes; "late" if now - slot > LATE_MARK_AFTER; else "send"
def make_id(now: datetime, rand_hex: str) -> str
    # "r-" + now in UTC as %Y%m%dT%H%M%S + "-" + rand_hex
```

- [ ] **Step 1: Write failing tests** in `scripts/tests/test_schedule.py`:

```python
import unittest
from datetime import datetime, timedelta, timezone
from brain_control import schedule as S

UTC = timezone.utc
def base(**over):
    d = {"version": 1, "id": "r-20260915T013000-abcd", "kind": "text", "name": "Trash",
         "to": ["+639170000001"], "text": "Trash day", "prompt": None,
         "schedule": {"type": "weekly", "days": ["mon"], "time": "08:00"},
         "tz": "Asia/Manila", "late_limit_minutes": 120,
         "created_at": "2026-09-01T00:00:00Z", "created_by": "brice"}
    d.update(over); return d
ALLOW = {"+639170000001", "+639170000002", "kath@example.com"}

class Validate(unittest.TestCase):
    def test_valid_weekly(self):
        r = S.validate(base(), ALLOW, "r-20260915T013000-abcd")
        self.assertEqual(r["schedule"]["days"], ["mon"])
    def test_defaults_filled(self):
        d = base(); del d["tz"]; del d["late_limit_minutes"]; del d["prompt"]
        r = S.validate(d, ALLOW)
        self.assertEqual((r["tz"], r["late_limit_minutes"], r["prompt"]), ("Asia/Manila", 120, None))
    def test_unknown_key(self):
        with self.assertRaises(S.ReminderError): S.validate(base(extra=1), ALLOW)
    def test_not_in_allowlist(self):
        with self.assertRaises(S.ReminderError): S.validate(base(to=["+15550000000"]), ALLOW)
    def test_handle_normalized(self):
        r = S.validate(base(to=["+63 917-000-0001"]), ALLOW)
        self.assertEqual(r["to"], ["+639170000001"])
    def test_smart_one_recipient(self):
        with self.assertRaises(S.ReminderError):
            S.validate(base(kind="smart", text=None, prompt="Chores?", to=["+639170000001", "+639170000002"]), ALLOW)
    def test_text_needs_text(self):
        with self.assertRaises(S.ReminderError): S.validate(base(text=""), ALLOW)
    def test_text_too_long(self):
        with self.assertRaises(S.ReminderError): S.validate(base(text="x" * 1001), ALLOW)
    def test_file_id_mismatch(self):
        with self.assertRaises(S.ReminderError): S.validate(base(), ALLOW, "r-other")
    def test_bad_id(self):
        with self.assertRaises(S.ReminderError): S.validate(base(id="../x"), ALLOW)
    def test_once_needs_offset(self):
        with self.assertRaises(S.ReminderError):
            S.validate(base(schedule={"type": "once", "at": "2026-09-16T08:00:00"}), ALLOW)
    def test_bad_time(self):
        with self.assertRaises(S.ReminderError):
            S.validate(base(schedule={"type": "daily", "time": "25:00"}), ALLOW)
    def test_bad_day(self):
        with self.assertRaises(S.ReminderError):
            S.validate(base(schedule={"type": "weekly", "days": ["funday"], "time": "08:00"}), ALLOW)
    def test_late_limit_range(self):
        with self.assertRaises(S.ReminderError): S.validate(base(late_limit_minutes=5000), ALLOW)

class Slots(unittest.TestCase):
    def test_weekly_due(self):
        r = S.validate(base(), ALLOW)
        now = datetime(2026, 9, 14, 0, 5, tzinfo=UTC)        # Mon 08:05 Manila
        self.assertEqual(S.due_slot(r, now, None), datetime(2026, 9, 14, 0, 0, tzinfo=UTC))
    def test_weekly_already_done(self):
        r = S.validate(base(), ALLOW)
        now = datetime(2026, 9, 14, 0, 5, tzinfo=UTC)
        self.assertIsNone(S.due_slot(r, now, datetime(2026, 9, 14, 0, 0, tzinfo=UTC)))
    def test_not_before_created(self):
        r = S.validate(base(created_at="2026-09-14T00:01:00Z"), ALLOW)
        self.assertIsNone(S.due_slot(r, datetime(2026, 9, 14, 0, 5, tzinfo=UTC), None))
    def test_daily(self):
        r = S.validate(base(schedule={"type": "daily", "time": "07:00"}), ALLOW)
        now = datetime(2026, 9, 15, 23, 30, tzinfo=UTC)       # 07:30 Manila on the 16th
        self.assertEqual(S.due_slot(r, now, None), datetime(2026, 9, 15, 23, 0, tzinfo=UTC))
    def test_once(self):
        r = S.validate(base(schedule={"type": "once", "at": "2026-09-16T08:00:00+08:00"}), ALLOW)
        self.assertIsNone(S.due_slot(r, datetime(2026, 9, 15, 23, 59, tzinfo=UTC), None))
        self.assertEqual(S.due_slot(r, datetime(2026, 9, 16, 0, 1, tzinfo=UTC), None),
                         datetime(2026, 9, 16, 0, 0, tzinfo=UTC))
    def test_next_run_weekly(self):
        r = S.validate(base(schedule={"type": "weekly", "days": ["mon", "thu"], "time": "08:00"}), ALLOW)
        self.assertEqual(S.next_run(r, datetime(2026, 9, 14, 0, 5, tzinfo=UTC)),
                         datetime(2026, 9, 17, 0, 0, tzinfo=UTC))
    def test_decide(self):
        r = S.validate(base(), ALLOW)
        slot = datetime(2026, 9, 14, 0, 0, tzinfo=UTC)
        self.assertEqual(S.decide(r, slot, slot + timedelta(minutes=1)), "send")
        self.assertEqual(S.decide(r, slot, slot + timedelta(minutes=30)), "late")
        self.assertEqual(S.decide(r, slot, slot + timedelta(minutes=121)), "skip")
    def test_parse_iso_z(self):
        self.assertEqual(S.parse_iso("2026-09-15T01:30:00Z"), datetime(2026, 9, 15, 1, 30, tzinfo=UTC))
    def test_allowlist(self):
        self.assertEqual(S.parse_allowlist("+63 917 000 0001, Kath@Example.com"),
                         {"+639170000001", "kath@example.com"})
```

- [ ] **Step 2: Run, expect import failure.** `cd scripts && /usr/bin/python3 -m unittest tests.test_schedule -v`
- [ ] **Step 3: Implement `schedule.py`** to the interface above. Slots: build the local wall time with `datetime(y, m, d, hh, mm, tzinfo=ZoneInfo(tz))`, convert to UTC. For recurring, iterate local dates from `(now_local.date() - 8 days)` to `now_local.date() + 8 days` as needed.
- [ ] **Step 4: Run tests, all pass** on `/usr/bin/python3` (3.9).
- [ ] **Step 5: Commit** `AS-3 | Reminder schedule module`

---

### Task 2: Gate fencing (`imsg-ssh-gate.py --brain`)

**Files:** Modify `scripts/imsg-ssh-gate.py` (`main` near line 729, `run_rpc` near line 515, request loop near line 600, `filter_line` near line 537). Create `scripts/tests/test_gate_fencing.py`.

**Interfaces (Produces):**

```python
LEASE = os.path.expanduser("~/.imsg-bridge/active-brain")
BRAINS = ("pc", "mac")
ROLES = ("pc", "mac", "clock")

def parse_role(argv_tail: List[str]) -> Optional[str]
    # [] -> None (legacy, no fencing); ["--brain", "pc"] -> "pc"; anything else -> raises SystemExit via deny()
def read_lease(path: str = LEASE) -> str
    # "pc" or "mac"; missing/unreadable/other content -> "pc"
def may_receive(role: Optional[str], lease_path: str = LEASE) -> bool
    # None -> True; "clock" -> False; pc/mac -> role == read_lease()
def may_send(role: Optional[str], lease_path: str = LEASE) -> bool
    # None -> True; "clock" -> True; pc/mac -> role == read_lease()
def method_allowed_for_role(role: Optional[str], method: str) -> bool
    # "clock" -> only "send"; others -> True (RPC_METHODS check still applies)
```

Wiring:
- `main()`: `role = parse_role(sys.argv[1:])`. Pass `role` into `run_rpc(args, role)`. Argv mode (`status`) unchanged for all roles.
- Request loop: after the `RPC_METHODS` check, `if not method_allowed_for_role(role, method): reject(request_id, "method %s is not allowed for %s" % (short(method), role)); continue`.
- Before the send handling, `if method == "send" and not may_send(role): reject(request_id, "not the active brain"); continue`. Log reason `deny-rpc` with the role, never text.
- `filter_line`: for a notification (`"method" in message`) call `may_receive(role)` first; if False, return `None` and log `fence` with the method name (at most once per 60 s per process, to keep the log small).
- Reads the lease on every call. No caching.

- [ ] **Step 1: Write failing tests** (load the gate with `importlib.util.spec_from_file_location("gate", <repo>/scripts/imsg-ssh-gate.py)`; point `LOG` at a temp file before calling functions that log):

```python
import importlib.util, os, tempfile, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("gate", os.path.join(HERE, "..", "imsg-ssh-gate.py"))
gate = importlib.util.module_from_spec(spec); spec.loader.exec_module(gate)

class Fencing(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(); self.lease = os.path.join(self.d, "active-brain")
        gate.LOG = os.path.join(self.d, "gate.log")
    def put(self, v):
        with open(self.lease, "w") as f: f.write(v)
    def test_parse_role(self):
        self.assertIsNone(gate.parse_role([]))
        self.assertEqual(gate.parse_role(["--brain", "mac"]), "mac")
        with self.assertRaises(SystemExit): gate.parse_role(["--brain", "evil"])
        with self.assertRaises(SystemExit): gate.parse_role(["--brain"])
        with self.assertRaises(SystemExit): gate.parse_role(["--other", "pc"])
    def test_missing_lease_is_pc(self):
        self.assertEqual(gate.read_lease(self.lease), "pc")
    def test_garbage_lease_is_pc(self):
        self.put("banana"); self.assertEqual(gate.read_lease(self.lease), "pc")
    def test_lease_with_newline(self):
        self.put("mac\n"); self.assertEqual(gate.read_lease(self.lease), "mac")
    def test_receive_send_by_lease(self):
        self.put("mac")
        self.assertTrue(gate.may_receive("mac", self.lease)); self.assertFalse(gate.may_receive("pc", self.lease))
        self.assertTrue(gate.may_send("mac", self.lease)); self.assertFalse(gate.may_send("pc", self.lease))
    def test_legacy_role_unfenced(self):
        self.put("mac")
        self.assertTrue(gate.may_receive(None, self.lease)); self.assertTrue(gate.may_send(None, self.lease))
    def test_clock(self):
        self.assertFalse(gate.may_receive("clock", self.lease)); self.assertTrue(gate.may_send("clock", self.lease))
        self.assertTrue(gate.method_allowed_for_role("clock", "send"))
        self.assertFalse(gate.method_allowed_for_role("clock", "watch.subscribe"))
        self.assertFalse(gate.method_allowed_for_role("clock", "messages.history"))
        self.assertTrue(gate.method_allowed_for_role("pc", "watch.subscribe"))
```

- [ ] **Step 2: Run, expect AttributeError.**
- [ ] **Step 3: Implement** the functions and wiring. Update the module docstring with a short "Fencing" paragraph.
- [ ] **Step 4: Run all tests.** Also `python3 -c "import ast;ast.parse(open('scripts/imsg-ssh-gate.py').read())"`.
- [ ] **Step 5: Commit** `AS-3 | Gate: --brain lease fencing and clock role`

---

### Task 3: failover.py

**Files:** Create `scripts/brain_control/failover.py`, `scripts/tests/test_failover.py`.

**Interfaces (Produces):**

```python
FAIL_TICKS = 5
OK_TICKS = 3
STRAY_TICKS = 2
UNSYNCED_NOTICE_TICKS = 20
MODES = ("auto", "pc", "mac", "off")

@dataclass
class Inputs:
    mode: str            # one of MODES; anything else is treated as "off"
    lease: str           # "pc" | "mac"
    pc_healthy: bool
    pc_in_sync: bool
    mac_running: bool

@dataclass
class Actions:
    lease: Optional[str] = None       # new lease to write, None = keep
    docker: Optional[str] = None      # "up" | "stop" | None
    notices: List[str] = field(default_factory=list)

def step(inp: Inputs, st: Dict) -> Actions
    # st keys (create if missing, ints/bools): fail_streak, ok_streak, stray_ticks,
    # unsynced_ticks, unsynced_noticed
```

Rules: spec 3.3, plus:
- mode "pc": lease -> "pc" if different; docker "stop" if mac_running. Reset streaks.
- mode "mac": lease -> "mac" if different; docker "up" if not mac_running. Reset streaks.
- mode "off" or unknown: return empty Actions, do not touch st.
- On FAILOVER: `Actions(lease="mac", docker="up", notices=["Brice moved to the Mac (PC brain not reachable)."])`, reset fail_streak.
- On FAIL BACK: `Actions(lease="pc", docker="stop", notices=["Brice is back on the PC."])`, reset ok_streak, unsynced_ticks, unsynced_noticed.
- Unsynced notice text: `"PC brain is up but memory is not synced yet. Log in on the PC so Syncthing starts."`; send once until a fail back or until PC becomes unhealthy.
- Lease "mac" and mac not running: docker "up" (in the same Actions as other decisions; FAIL BACK wins over "up").

- [ ] **Step 1: Write failing tests:**

```python
import unittest
from brain_control.failover import Inputs, step, FAIL_TICKS, OK_TICKS, UNSYNCED_NOTICE_TICKS

def I(**k):
    d = dict(mode="auto", lease="pc", pc_healthy=True, pc_in_sync=True, mac_running=False); d.update(k)
    return Inputs(**d)

class Auto(unittest.TestCase):
    def test_pc_fine_nothing(self):
        st = {}; a = step(I(), st)
        self.assertEqual((a.lease, a.docker, a.notices), (None, None, []))
    def test_failover_after_streak(self):
        st = {}
        for _ in range(FAIL_TICKS - 1):
            self.assertIsNone(step(I(pc_healthy=False), st).lease)
        a = step(I(pc_healthy=False), st)
        self.assertEqual((a.lease, a.docker), ("mac", "up")); self.assertEqual(len(a.notices), 1)
    def test_one_good_check_resets(self):
        st = {}
        for _ in range(FAIL_TICKS - 1): step(I(pc_healthy=False), st)
        step(I(), st)
        self.assertIsNone(step(I(pc_healthy=False), st).lease)
    def test_stray_mac_brain_stopped(self):
        st = {}
        self.assertIsNone(step(I(mac_running=True), st).docker)
        self.assertEqual(step(I(mac_running=True), st).docker, "stop")
    def test_mac_lease_restarts_brain(self):
        self.assertEqual(step(I(lease="mac", pc_healthy=False), {}).docker, "up")
    def test_failback_needs_streak_and_sync(self):
        st = {}
        for _ in range(OK_TICKS - 1):
            self.assertIsNone(step(I(lease="mac", mac_running=True), st).lease)
        a = step(I(lease="mac", mac_running=True), st)
        self.assertEqual((a.lease, a.docker), ("pc", "stop"))
    def test_no_failback_without_sync_and_one_notice(self):
        st = {}; notices = 0
        for _ in range(OK_TICKS + UNSYNCED_NOTICE_TICKS + 5):
            a = step(I(lease="mac", mac_running=True, pc_in_sync=False), st)
            self.assertIsNone(a.lease); notices += len(a.notices)
        self.assertEqual(notices, 1)

class Manual(unittest.TestCase):
    def test_off(self):
        st = {"fail_streak": 3}; a = step(I(mode="off", pc_healthy=False), st)
        self.assertEqual((a.lease, a.docker), (None, None)); self.assertEqual(st, {"fail_streak": 3})
    def test_pin_mac(self):
        a = step(I(mode="mac"), {}); self.assertEqual((a.lease, a.docker), ("mac", "up"))
    def test_pin_pc(self):
        a = step(I(mode="pc", lease="mac", mac_running=True), {}); self.assertEqual((a.lease, a.docker), ("pc", "stop"))
    def test_unknown_mode_is_off(self):
        a = step(I(mode="yolo", pc_healthy=False), {}); self.assertEqual((a.lease, a.docker), (None, None))
```

- [ ] **Step 2: Run, expect import failure.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Tests pass on 3.9.**
- [ ] **Step 5: Commit** `AS-3 | Failover state machine`

---

### Task 4: clock.py

**Files:** Create `scripts/brain_control/clock.py`, `scripts/tests/test_clock.py`.

**Interfaces:**
- Consumes: `schedule.validate`, `schedule.due_slot`, `schedule.decide`, `schedule.parse_iso`, `schedule.to_iso_utc` (Task 1).
- Produces:

```python
MAX_PER_TICK = 10
MAX_PER_DAY = 60
GONE_KEEP = timedelta(days=7)

def smart_payload(rem: dict, slot: datetime, late: bool) -> dict
    # {"message": <header + prompt>, "name": rem["name"], "deliver": True,
    #  "channel": "imessage", "to": rem["to"][0], "idempotencyKey": rem["id"] + ":" + to_iso_utc(slot)}
    # header lines: "Scheduled job: <name>", "Scheduled for: <slot in rem tz, YYYY-MM-DD HH:MM>",
    #   "(This job is running late.)" if late, "Send your final answer as one iMessage to <to>.", "", prompt

def run(reminders_dir: str, st: Dict, now: datetime, lease: str, allow: set,
        send_text: Callable[[str, str], bool],        # (handle, text) -> ok
        send_smart: Callable[[str, dict], bool],      # (lease, payload) -> ok
        notify_mark: Callable[[str], bool],
        log: Callable[[str, str], None]) -> None
```

Behavior (spec 4.3), exact state keys in `st`:
- `last_done: {id: iso}`; `partial: {id: {"slot": iso, "done": [handles]}}`;
  `sent_today: {"date": "YYYY-MM-DD" (Manila), "count": int}`;
  `invalid_seen: {filename: sha256 hex of bytes}`; `gone: {id: iso first seen missing}`.
- Files: only `*.json` directly in `reminders_dir`; missing dir -> return. Sort by file name.
- Invalid (JSON error or `ReminderError`): log `invalid <filename>` only when the hash differs from `invalid_seen`.
- `decide == "skip"`: set `last_done`, collect `rem["name"]`; delete file if `once`; log `skip <id>`.
- send path, `text`: for each handle in `to` not in `partial[id].done` (when `partial[id].slot` equals this slot): stop if tick or day limit reached; `text = ("(late) " if late else "") + rem["text"]`; on ok append to done and count. All done -> `last_done`, clear partial, delete file if once. Else keep partial.
- send path, `smart`: limit check; `send_smart(lease, smart_payload(...))`; ok -> count, last_done, delete if once.
- After the loop: if skipped names, `notify_mark("Skipped late reminders: " + ", ".join(names))` (does not count toward limits).
- `gone`: ids in `last_done`/`partial` with no file: first time record now; older than `GONE_KEEP` -> remove from all maps.
- Deleting a file: `os.remove`, ignore `FileNotFoundError`.

- [ ] **Step 1: Write failing tests** with a temp dir and recording fakes:

```python
import json, os, tempfile, unittest
from datetime import datetime, timedelta, timezone
from brain_control import clock

UTC = timezone.utc
ALLOW = {"+639170000001", "+639170000002"}
def write(d, **over):
    r = {"version": 1, "id": "r-a", "kind": "text", "name": "Trash", "to": ["+639170000001"],
         "text": "Trash day", "prompt": None, "schedule": {"type": "once", "at": "2026-09-16T08:00:00+08:00"},
         "tz": "Asia/Manila", "late_limit_minutes": 120, "created_at": "2026-09-15T00:00:00Z", "created_by": "brice"}
    r.update(over)
    with open(os.path.join(d, r["id"] + ".json"), "w") as f: json.dump(r, f)
    return r

class Rec:
    def __init__(self, ok=True): self.calls = []; self.ok = ok
    def __call__(self, *a): self.calls.append(a); return self.ok(a) if callable(self.ok) else self.ok

class Clock(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(); self.st = {}
        self.text, self.smart, self.mark, self.logs = Rec(), Rec(), Rec(), []
    def tick(self, now, lease="pc"):
        clock.run(self.d, self.st, now, lease, ALLOW, self.text, self.smart, self.mark,
                  lambda e, x: self.logs.append((e, x)))
    SLOT = datetime(2026, 9, 16, 0, 0, tzinfo=UTC)

    def test_once_sends_once_and_deletes(self):
        write(self.d); self.tick(self.SLOT + timedelta(seconds=20)); self.tick(self.SLOT + timedelta(seconds=50))
        self.assertEqual(self.text.calls, [("+639170000001", "Trash day")])
        self.assertFalse(os.path.exists(os.path.join(self.d, "r-a.json")))
    def test_not_yet(self):
        write(self.d); self.tick(self.SLOT - timedelta(minutes=1)); self.assertEqual(self.text.calls, [])
    def test_late_prefix(self):
        write(self.d); self.tick(self.SLOT + timedelta(minutes=30))
        self.assertEqual(self.text.calls[0][1], "(late) Trash day")
    def test_skip_reports_once(self):
        write(self.d); self.tick(self.SLOT + timedelta(hours=3))
        self.assertEqual(self.text.calls, []); self.assertEqual(len(self.mark.calls), 1)
        self.assertIn("Trash", self.mark.calls[0][0])
    def test_retry_after_failure(self):
        write(self.d); self.text.ok = False; self.tick(self.SLOT + timedelta(seconds=20))
        self.text.ok = True; self.tick(self.SLOT + timedelta(seconds=50))
        self.assertEqual(len(self.text.calls), 2)
        self.assertFalse(os.path.exists(os.path.join(self.d, "r-a.json")))
    def test_partial_not_resent(self):
        write(self.d, to=["+639170000001", "+639170000002"])
        self.text.ok = lambda a: a[0] == "+639170000001"
        self.tick(self.SLOT + timedelta(seconds=20))
        self.text.ok = True; self.tick(self.SLOT + timedelta(seconds=50))
        self.assertEqual([c[0] for c in self.text.calls], ["+639170000001", "+639170000002", "+639170000002"])
    def test_weekly_kept(self):
        write(self.d, schedule={"type": "weekly", "days": ["wed"], "time": "08:00"})
        self.tick(self.SLOT + timedelta(seconds=20)); self.tick(self.SLOT + timedelta(minutes=5))
        self.assertEqual(len(self.text.calls), 1)
        self.assertTrue(os.path.exists(os.path.join(self.d, "r-a.json")))
    def test_smart_goes_to_lease(self):
        write(self.d, kind="smart", text=None, prompt="List chores")
        self.tick(self.SLOT + timedelta(seconds=20), lease="mac")
        lease, payload = self.smart.calls[0]
        self.assertEqual(lease, "mac"); self.assertEqual(payload["to"], "+639170000001")
        self.assertEqual(payload["idempotencyKey"], "r-a:2026-09-16T00:00:00Z")
        self.assertTrue(payload["deliver"]); self.assertIn("List chores", payload["message"])
    def test_invalid_logged_once_never_sent(self):
        with open(os.path.join(self.d, "r-bad.json"), "w") as f: f.write("{nope")
        self.tick(self.SLOT); self.tick(self.SLOT + timedelta(seconds=30))
        self.assertEqual(len([l for l in self.logs if l[0] == "invalid"]), 1)
    def test_not_in_allowlist_never_sent(self):
        write(self.d, to=["+15550000000"]); self.tick(self.SLOT + timedelta(seconds=20))
        self.assertEqual(self.text.calls, [])
    def test_tick_limit(self):
        for i in range(clock.MAX_PER_TICK + 3):
            write(self.d, id="r-%02d" % i)
        self.tick(self.SLOT + timedelta(seconds=20))
        self.assertEqual(len(self.text.calls), clock.MAX_PER_TICK)
        self.tick(self.SLOT + timedelta(seconds=50))
        self.assertEqual(len(self.text.calls), clock.MAX_PER_TICK + 3)
```

- [ ] **Step 2: Run, expect import failure.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Tests pass on 3.9.**
- [ ] **Step 5: Commit** `AS-3 | Reminder clock step`

---

### Task 5: senders.py, main.py, launchd, installer

**Files:** Create `scripts/brain_control/senders.py`, `scripts/brain_control/main.py`, `scripts/brain-control.plist`, `scripts/install-brain-control.sh`, `scripts/tests/test_main.py`.

**Interfaces:**
- Consumes: `failover.Inputs/Actions/step` (Task 3), `clock.run` (Task 4), `schedule.parse_allowlist` (Task 1).
- Produces (senders.py):

```python
def http_ok(url: str, timeout: float = 5.0, headers: Optional[dict] = None,
            body: Optional[dict] = None) -> bool         # GET or POST JSON; True on 2xx
def pc_healthy(url: str) -> bool                        # http_ok(url, 5)
def syncthing_in_sync(config_xml: str, folder: str, device_name: str) -> bool
    # read <apikey> from config_xml; GET /rest/config/devices, find device whose name == device_name;
    # GET /rest/system/connections -> connections[id].connected; GET /rest/db/completion -> needItems == 0.
    # any error -> False. Never log the api key.
def docker_running(docker: str, name: str) -> bool     # `docker inspect -f {{.State.Running}} name` == "true"
def docker_compose(docker: str, repo_dir: str, action: str) -> bool
    # action "up" -> ["compose","up","-d","openclaw"]; "stop" -> ["compose","stop","openclaw"]; cwd=repo_dir; timeout 180
def read_text(path: str, default: str) -> str
def write_atomic(path: str, data: str, mode: int = 0o600) -> None
def gate_send(ssh_key: str, known_hosts: str, target: str, handle: str, text: str, timeout: float = 60) -> bool
    # ssh -T -i key -o IdentitiesOnly=yes -o BatchMode=yes -o UserKnownHostsFile=known_hosts
    #   -o StrictHostKeyChecking=yes target "/opt/homebrew/bin/imsg rpc"
    # stdin: {"jsonrpc":"2.0","id":1,"method":"send","params":{"chat_identifier":handle,"text":text}}\n
    # read stdout lines until an object with id == 1; ok = "result" in it and "error" not in it.
    # then close stdin and wait (kill after 10 s). Any error/timeout -> False.
def hook_agent(base_url: str, token: str, payload: dict) -> bool
    # POST base_url + "/hooks/agent", Authorization: Bearer token, timeout 20
```

- Produces (main.py): `def tick(cfg: dict, now: Optional[datetime] = None, io=None) -> None` and `if __name__ == "__main__"` that loads `~/.brain-control/config.json`. `io` is an object with the senders functions as attributes (default: the `senders` module), so tests inject fakes.

Config file `~/.brain-control/config.json` (installer writes a template, Mac-specific values):

```json
{
  "repo_dir": "/Users/mikee/workspace/assistant",
  "docker": "/usr/local/bin/docker",
  "lease_path": "/Users/mikee/.imsg-bridge/active-brain",
  "mode_path": "/Users/mikee/.brain-control/mode",
  "state_path": "/Users/mikee/.brain-control/state.json",
  "lock_path": "/Users/mikee/.brain-control/tick.lock",
  "log_path": "/Users/mikee/.brain-control/brain-control.log",
  "pc_health_url": "http://100.123.4.5:18789/healthz",
  "hooks_urls": {"pc": "http://100.123.4.5:18789", "mac": "http://127.0.0.1:18789"},
  "hooks_token_path": "/Users/mikee/.brain-control/hooks-token",
  "syncthing_config": "/Users/mikee/Library/Application Support/Syncthing/config.xml",
  "syncthing_folder": "openclaw-workspace",
  "pc_device_name": "desktop-3p37btg",
  "reminders_dir": "/Users/mikee/workspace/assistant/data/openclaw/workspace/reminders",
  "env_path": "/Users/mikee/workspace/assistant/.env",
  "mark_handle_env": "MARK_IMESSAGE_HANDLE",
  "clock_ssh_key": "/Users/mikee/.brain-control/clock_ed25519",
  "clock_known_hosts": "/Users/mikee/.brain-control/known_hosts",
  "clock_ssh_target": "mikee@127.0.0.1"
}
```

tick():
1. `fcntl.flock(lock, LOCK_EX | LOCK_NB)`; if busy, return.
2. Load state (JSON). Corrupt -> rename to `state.json.bad-<epoch>`, start `{}`.
3. Read `.env` (simple `KEY=VALUE` lines, ignore `#`): `IMESSAGE_ALLOW_FROM` -> allow set; `MARK_IMESSAGE_HANDLE` -> mark handle (if missing, notices are logged only).
4. mode = `read_text(mode_path, "off").strip()`; lease = read lease file ("pc" default).
5. Failover: only query `pc_healthy` / `syncthing_in_sync` / `docker_running` when mode is not "off". `acts = failover.step(...)`. Apply in order: write lease (atomic, 0644), docker action, notices via `gate_send(mark)`. Save state.
6. Clock: `clock.run(reminders_dir, st["clock"], now, current lease, allow, send_text, send_smart, notify_mark, log)` where `send_text` = gate_send, `send_smart(lease, p)` = `hook_agent(hooks_urls[lease], token, p)`. Save state.
7. Every step wrapped: an exception is logged as `error <step> <ExceptionType>` and the next step still runs.

Log format: `2026-09-15T05:00:00 event detail` appended to log_path; rotate by truncating to the last 2000 lines when over 1 MB.

`scripts/brain-control.plist`: Label `com.assistant.brain-control`, ProgramArguments `["/usr/bin/python3", "-m", "brain_control.main"]`, WorkingDirectory `__LIB__` (installer replaces), StartInterval 30, RunAtLoad true, StandardOutPath/StandardErrorPath `__HOME__/.brain-control/launchd.log`, EnvironmentVariables PATH `/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin`.

`scripts/install-brain-control.sh` (Mark runs it; idempotent, `set -euo pipefail`):
1. `mkdir -p ~/.brain-control/lib/brain_control`, chmod 700 `~/.brain-control`.
2. Copy `scripts/brain_control/*.py` into lib.
3. If missing: write config.json template (above), `mode` = `off`, generate `clock_ed25519` (`ssh-keygen -t ed25519 -N "" -C brain-control-clock`), `known_hosts` = `127.0.0.1 <contents of /etc/ssh/ssh_host_ed25519_key.pub first two fields>`, `hooks-token` = `openssl rand -hex 32` (chmod 600).
4. Install gate: copy `scripts/imsg-ssh-gate.py` to `~/.imsg-bridge/imsg-ssh-gate` (backup old copy with timestamp), chmod 755.
5. Write plist to `~/Library/LaunchAgents/com.assistant.brain-control.plist` with placeholders replaced; `launchctl bootout gui/$(id -u)/com.assistant.brain-control 2>/dev/null || true`; `launchctl bootstrap gui/$(id -u) <plist>`.
6. Print the clock public key and the exact `authorized_keys` line to add, and the next steps. Never print the hooks token.

- [ ] **Step 1: Write failing `test_main.py`** with a fake `io` object and temp paths:

```python
import json, os, tempfile, unittest
from datetime import datetime, timezone
from brain_control import main

class FakeIO:
    def __init__(self): self.healthy = True; self.running = False; self.sync = True; self.compose = []; self.sent = []; self.hooks = []
    def pc_healthy(self, url): return self.healthy
    def syncthing_in_sync(self, cfg, folder, name): return self.sync
    def docker_running(self, docker, name): return self.running
    def docker_compose(self, docker, repo, action): self.compose.append(action); return True
    def gate_send(self, key, kh, target, handle, text, timeout=60): self.sent.append((handle, text)); return True
    def hook_agent(self, url, token, payload): self.hooks.append((url, payload)); return True
    from brain_control.senders import read_text, write_atomic

class Tick(unittest.TestCase):
    def setUp(self):
        d = self.d = tempfile.mkdtemp(); os.mkdir(os.path.join(d, "rem"))
        with open(os.path.join(d, ".env"), "w") as f:
            f.write("IMESSAGE_ALLOW_FROM=+639170000001\nMARK_IMESSAGE_HANDLE=+639170000001\n")
        with open(os.path.join(d, "hooks-token"), "w") as f: f.write("tok")
        self.cfg = {k: os.path.join(d, v) for k, v in dict(
            lease_path="lease", mode_path="mode", state_path="state.json", lock_path="lock",
            log_path="log", reminders_dir="rem", env_path=".env", hooks_token_path="hooks-token",
            repo_dir=".", clock_ssh_key="k", clock_known_hosts="kh").items()}
        self.cfg.update(docker="docker", pc_health_url="u", syncthing_config="x", syncthing_folder="f",
                        pc_device_name="pc", mark_handle_env="MARK_IMESSAGE_HANDLE", clock_ssh_target="t",
                        hooks_urls={"pc": "http://pc", "mac": "http://mac"})
        self.io = FakeIO()
    def mode(self, m):
        with open(self.cfg["mode_path"], "w") as f: f.write(m)
    def test_mode_off_by_default_does_no_failover(self):
        self.io.healthy = False
        for _ in range(10): main.tick(self.cfg, io=self.io)
        self.assertEqual(self.io.compose, []); self.assertFalse(os.path.exists(self.cfg["lease_path"]))
    def test_auto_failover_writes_lease_starts_and_notifies(self):
        self.mode("auto"); self.io.healthy = False
        for _ in range(5): main.tick(self.cfg, io=self.io)
        self.assertEqual(open(self.cfg["lease_path"]).read().strip(), "mac")
        self.assertEqual(self.io.compose, ["up"]); self.assertEqual(len(self.io.sent), 1)
    def test_corrupt_state_recovered(self):
        with open(self.cfg["state_path"], "w") as f: f.write("{bad")
        main.tick(self.cfg, io=self.io)
        self.assertTrue(any(n.startswith("state.json.bad-") for n in os.listdir(self.d)))
    def test_smart_uses_lease_url(self):
        with open(self.cfg["lease_path"], "w") as f: f.write("mac")
        r = {"version": 1, "id": "r-s", "kind": "smart", "name": "Chores", "to": ["+639170000001"],
             "text": None, "prompt": "chores?", "schedule": {"type": "once", "at": "2026-09-16T08:00:00+08:00"},
             "created_at": "2026-09-15T00:00:00Z", "created_by": "brice"}
        with open(os.path.join(self.cfg["reminders_dir"], "r-s.json"), "w") as f: json.dump(r, f)
        main.tick(self.cfg, now=datetime(2026, 9, 16, 0, 0, 30, tzinfo=timezone.utc), io=self.io)
        self.assertEqual(self.io.hooks[0][0], "http://mac")
```

(Implementer: the `FakeIO` class-body import is only to reuse real file helpers; if that is awkward, set `read_text`/`write_atomic` as attributes in `__init__`.)

- [ ] **Step 2: Run, expect import failure.**
- [ ] **Step 3: Implement senders.py, main.py, plist, installer.** `bash -n scripts/install-brain-control.sh`. `plutil -lint` the plist after placeholder replacement in a temp copy.
- [ ] **Step 4: Full test suite passes on 3.9.**
- [ ] **Step 5: Commit** `AS-3 | brain-control tick, senders, launchd installer`

---

### Task 6: `reminder` CLI, image, compose

**Files:** Create `scripts/reminder.py`, `scripts/tests/test_reminder_cli.py`. Modify `Dockerfile.imsg`, `docker-compose.yml`.

**Interfaces:**
- Consumes: `schedule.validate`, `schedule.next_run`, `schedule.make_id`, `schedule.to_iso_utc`, `schedule.parse_allowlist` (Task 1).
- Produces: `def main(argv: List[str], env: Dict[str, str], now: Optional[datetime] = None, out=sys.stdout) -> int`

CLI (spec 4.2):

```
reminder add-text  --to H [--to H ...] --text T --name N (--at ISO | --daily HH:MM | --weekly DAYS HH:MM) [--tz TZ] [--late-limit MIN]
reminder add-smart --to H --prompt P --name N (...same schedule flags...)
reminder list
reminder cancel ID
```

- env: `IMESSAGE_ALLOW_FROM` (required for add), `REMINDERS_DIR` (default `/home/node/.openclaw/workspace/reminders`), `REMINDERS_TMP` (default `/home/node/.openclaw/tmp`).
- Import: `sys.path.insert(0, os.environ.get("BRAIN_CONTROL_LIB", <dir of this file>))` then `from brain_control import schedule`.
- `add-*`: build dict, `created_at = to_iso_utc(now)`, `created_by = "brice"`, id via `make_id(now, secrets.token_hex(2))`; `validate(data, allow)`; refuse `once` with `at <= now` ("time is in the past"); refuse when `REMINDERS_DIR` has >= 100 `*.json`; `os.makedirs` both dirs; write temp in `REMINDERS_TMP`, `os.replace` into `REMINDERS_DIR/<id>.json`. Print `{"ok": true, "id": ..., "next_run": "<Manila YYYY-MM-DD HH:MM>"}`. Exit 0.
- `list`: each valid file -> `{"id","kind","name","to_count","schedule","next_run"}` inside `{"ok": true, "reminders": [...]}` (one line). Invalid files listed as `{"file": name, "invalid": true}`. Never print full handles; print `to_count`.
- `cancel`: id must match `ID_RE`; remove file; missing -> `{"ok": false, "error": "no such reminder"}` exit 1.
- Errors: `{"ok": false, "error": "..."}` on stdout, exit 2 for usage, 1 otherwise. argparse errors must also come out as this JSON (override `ArgumentParser.error`).

Dockerfile.imsg additions (before `USER node`):

```dockerfile
COPY scripts/brain_control/__init__.py scripts/brain_control/schedule.py /usr/local/lib/brain_control/brain_control/
COPY scripts/reminder.py /usr/local/bin/reminder
RUN sed -i 's/\r$//' /usr/local/bin/reminder && chmod 0755 /usr/local/bin/reminder
```

and set `ENV BRAIN_CONTROL_LIB=/usr/local/lib/brain_control`. `reminder.py` starts with `#!/usr/bin/env python3`. Extend the existing CR-strip `sed` line to include `/usr/local/bin/reminder` instead of a second RUN if simpler.

docker-compose.yml: add under `openclaw:` `mem_limit: ${OPENCLAW_MEM_LIMIT:-3g}` with a one-line comment (why: the Mac Docker VM also runs other stacks).

- [ ] **Step 1: Write failing tests:**

```python
import io, json, os, tempfile, unittest
from datetime import datetime, timezone
import importlib.util
HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("reminder_cli", os.path.join(HERE, "..", "reminder.py"))
cli = importlib.util.module_from_spec(spec); spec.loader.exec_module(cli)
NOW = datetime(2026, 9, 15, 1, 0, tzinfo=timezone.utc)

class CLI(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp()
        self.env = {"IMESSAGE_ALLOW_FROM": "+639170000001,+639170000002",
                    "REMINDERS_DIR": os.path.join(d, "rem"), "REMINDERS_TMP": os.path.join(d, "tmp")}
    def run_cli(self, *argv):
        out = io.StringIO(); code = cli.main(list(argv), self.env, NOW, out)
        return code, json.loads(out.getvalue().strip().splitlines()[-1])
    def test_add_text_weekly_and_list(self):
        code, r = self.run_cli("add-text", "--to", "+639170000002", "--text", "Trash", "--name", "Trash", "--weekly", "mon,thu", "08:00")
        self.assertEqual(code, 0); self.assertTrue(r["ok"])
        self.assertTrue(os.path.exists(os.path.join(self.env["REMINDERS_DIR"], r["id"] + ".json")))
        code, l = self.run_cli("list")
        self.assertEqual(l["reminders"][0]["name"], "Trash"); self.assertNotIn("to", l["reminders"][0])
    def test_add_smart_once(self):
        code, r = self.run_cli("add-smart", "--to", "+639170000001", "--prompt", "Chores today?", "--name", "Chores", "--at", "2026-09-16T07:00:00+08:00")
        self.assertEqual((code, r["next_run"]), (0, "2026-09-16 07:00"))
    def test_past_refused(self):
        code, r = self.run_cli("add-text", "--to", "+639170000001", "--text", "x", "--name", "x", "--at", "2026-09-14T07:00:00+08:00")
        self.assertEqual(code, 1); self.assertFalse(r["ok"])
    def test_not_allowlisted(self):
        code, r = self.run_cli("add-text", "--to", "+15550000000", "--text", "x", "--name", "x", "--daily", "08:00")
        self.assertEqual(code, 1); self.assertIn("allow", r["error"])
    def test_usage_error_is_json(self):
        code, r = self.run_cli("add-text", "--text", "x")
        self.assertEqual(code, 2); self.assertFalse(r["ok"])
    def test_cancel(self):
        _, r = self.run_cli("add-text", "--to", "+639170000001", "--text", "x", "--name", "x", "--daily", "08:00")
        self.assertEqual(self.run_cli("cancel", r["id"])[0], 0)
        self.assertEqual(self.run_cli("cancel", r["id"])[0], 1)
        self.assertEqual(self.run_cli("cancel", "../../etc/passwd")[0], 1)
```

- [ ] **Step 2: Run, expect failures.**
- [ ] **Step 3: Implement CLI; update Dockerfile and compose.**
- [ ] **Step 4: Tests pass on 3.9. `docker compose build` succeeds. `docker run --rm --entrypoint reminder assistant/openclaw:with-ssh list` prints `{"ok": true, "reminders": []}` (with `-e REMINDERS_DIR=/tmp/r`).**
- [ ] **Step 5: Commit** `AS-3 | reminder CLI in the brain image + memory limit`

---

### Task 7: Brice docs, ROADMAP, operations (orchestrator does this, not a subagent)

- Workspace (synced, not git): TOOLS.md "Reminders" section; new skill `skills/reminders/SKILL.md`; remove the finished "Buy flowers" entry from `memory/tasks.json`.
- ROADMAP.md: status of this work, Mark's `authorized_keys` steps, PC Claude steps (hooks config, `OPENCLAW_HOOKS_TOKEN`, rebuild, migrate cron jobs).
- Mac: run installer (Mark), add authorized_keys lines (Mark), configure Mac brain hooks + token, set mode `auto`, run the drill in spec section 6.
