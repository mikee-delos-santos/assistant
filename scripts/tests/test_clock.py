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
