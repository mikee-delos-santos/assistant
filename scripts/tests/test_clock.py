import json, os, tempfile, unittest
from datetime import datetime, timedelta, timezone
from unittest import mock
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
        # Retries wait out the backoff (1 minute after the first failure).
        write(self.d); self.text.ok = False; self.tick(self.SLOT + timedelta(seconds=20))
        self.text.ok = True; self.tick(self.SLOT + timedelta(seconds=20, minutes=1))
        self.assertEqual(len(self.text.calls), 2)
        self.assertFalse(os.path.exists(os.path.join(self.d, "r-a.json")))
    def test_partial_not_resent(self):
        write(self.d, to=["+639170000001", "+639170000002"])
        self.text.ok = lambda a: a[0] == "+639170000001"
        self.tick(self.SLOT + timedelta(seconds=20))
        self.text.ok = True; self.tick(self.SLOT + timedelta(seconds=20, minutes=1))
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

    # --- Fix round 1 ---

    def test_dedupe_recipients(self):
        # validate() normalizes both spellings to the same handle but does
        # not reject the duplicate; the clock must still send once.
        write(self.d, to=["+639170000001", "+63 917 000 0001"])
        self.tick(self.SLOT + timedelta(seconds=20))
        self.assertEqual(len(self.text.calls), 1)
        self.assertFalse(os.path.exists(os.path.join(self.d, "r-a.json")))
        self.assertIn("r-a", self.st["last_done"])
        # No stuck partial, so a much later tick reports nothing skipped.
        self.tick(self.SLOT + timedelta(hours=3))
        self.assertEqual(len(self.mark.calls), 0)

    def test_delete_failure_not_resent(self):
        write(self.d)
        with mock.patch("brain_control.clock.os.remove", side_effect=PermissionError):
            self.tick(self.SLOT + timedelta(seconds=20))
        self.assertEqual(len(self.text.calls), 1)
        self.assertIn("r-a", self.st["last_done"])
        self.assertEqual([l for l in self.logs if l[0] == "delete_failed"], [("delete_failed", "r-a")])
        # File still exists (delete failed) but must not be resent.
        self.assertTrue(os.path.exists(os.path.join(self.d, "r-a.json")))
        self.tick(self.SLOT + timedelta(seconds=50))
        self.assertEqual(len(self.text.calls), 1)

    def test_sender_raises_other_reminder_still_processed(self):
        write(self.d, id="r-raise", to=["+639170000001"])
        write(self.d, id="r-ok", to=["+639170000002"])

        def flaky(a):
            if a[0] == "+639170000001":
                raise RuntimeError("boom")
            return True
        self.text.ok = flaky

        self.tick(self.SLOT + timedelta(seconds=20))
        self.assertEqual(len(self.text.calls), 2)
        self.assertIn("r-ok", self.st["last_done"])
        self.assertNotIn("r-raise", self.st["last_done"])
        self.assertEqual(self.st["attempts"]["r-raise"]["per"]["+639170000001"]["n"], 1)

    def test_backoff_spacing_then_exhausts(self):
        write(self.d); self.text.ok = False
        t0 = self.SLOT + timedelta(seconds=20)
        self.tick(t0)
        self.assertEqual(len(self.text.calls), 1)

        too_soon = t0 + timedelta(seconds=30)
        self.tick(too_soon)
        self.assertEqual(len(self.text.calls), 1)

        t1 = t0 + timedelta(minutes=1)
        self.tick(t1)
        self.assertEqual(len(self.text.calls), 2)

        t2 = t1 + timedelta(minutes=2)
        self.tick(t2)
        self.assertEqual(len(self.text.calls), 3)

        t3 = t2 + timedelta(minutes=4)
        self.tick(t3)
        self.assertEqual(len(self.text.calls), 4)

        t4 = t3 + timedelta(minutes=8)
        self.tick(t4)
        self.assertEqual(len(self.text.calls), 5)

        t5 = t4 + timedelta(minutes=15)
        self.tick(t5)
        self.assertEqual(len(self.text.calls), 6)

        self.assertEqual(len(self.mark.calls), 1)
        self.assertIn("Failed reminders", self.mark.calls[0][0])
        self.assertIn("Trash", self.mark.calls[0][0])
        self.assertFalse(os.path.exists(os.path.join(self.d, "r-a.json")))
        self.assertIn("r-a", self.st["last_done"])
        self.assertNotIn("r-a", self.st["attempts"])
        self.assertEqual(self.st["sent_today"]["count"], 6)
