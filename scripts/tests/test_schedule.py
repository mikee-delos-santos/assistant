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

    # --- Fix round 3 (C2: `once` must be portable across Python 3.9/3.11) ---

    def test_offset_without_colon_rejected(self):
        with self.assertRaises(S.ReminderError):
            S.validate(base(schedule={"type": "once", "at": "2026-09-16T08:00:00+0800"}), ALLOW)

    def test_fractional_seconds_rejected(self):
        with self.assertRaises(S.ReminderError):
            S.validate(base(schedule={"type": "once", "at": "2026-09-16T08:00:00.500Z"}), ALLOW)

    def test_once_at_normalized_to_utc_z_form(self):
        r = S.validate(base(schedule={"type": "once", "at": "2026-09-16T08:00:00+08:00"}), ALLOW)
        self.assertEqual(r["schedule"]["at"], "2026-09-16T00:00:00Z")

    def test_once_at_already_z_stays_z(self):
        r = S.validate(base(schedule={"type": "once", "at": "2026-09-16T00:00:00Z"}), ALLOW)
        self.assertEqual(r["schedule"]["at"], "2026-09-16T00:00:00Z")

    def test_once_at_no_seconds_accepted_and_normalized(self):
        r = S.validate(base(schedule={"type": "once", "at": "2026-09-16T08:00+08:00"}), ALLOW)
        self.assertEqual(r["schedule"]["at"], "2026-09-16T00:00:00Z")

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
