import json, os, tempfile, unittest
from datetime import datetime, timedelta, timezone
from unittest import mock
from brain_control import clock

UTC = timezone.utc
ALLOW = {"+639170000001", "+639170000002", "+639170000003"}
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

    # --- Fix round 2 ---

    def test_non_hashable_schedule_type_treated_as_invalid(self):
        # schedule.validate does `sched_type in _SCHEDULE_KEYS`, a dict
        # membership check; a list there raises TypeError, not
        # ReminderError. That must not stop reminders sorting after it.
        write(self.d, id="r-0bad", schedule={"type": ["once"]})
        write(self.d)  # id "r-a", sorts after "r-0bad.json"
        self.tick(self.SLOT + timedelta(seconds=20))
        self.assertEqual(self.text.calls, [("+639170000001", "Trash day")])
        self.assertEqual([l for l in self.logs if l[0] == "invalid"], [("invalid", "r-0bad.json")])
        # Only logged once even if the tick runs again with the same content.
        self.tick(self.SLOT + timedelta(seconds=30))
        self.assertEqual(len([l for l in self.logs if l[0] == "invalid"]), 1)

    def test_deeply_nested_json_does_not_raise(self):
        with open(os.path.join(self.d, "r-deep.json"), "w") as f:
            f.write("[" * 100000)
        # json.loads on this raises RecursionError, not ValueError/ReminderError.
        self.tick(self.SLOT + timedelta(seconds=20))
        self.assertEqual(len([l for l in self.logs if l[0] == "invalid"]), 1)

    # --- Fix round 3 (R10: gate_send ok/retry/final outcomes) ---

    def test_final_outcome_stops_after_one_attempt_and_reports_failed(self):
        write(self.d)
        self.text.ok = "final"
        self.tick(self.SLOT + timedelta(seconds=20))
        self.assertEqual(len(self.text.calls), 1)
        self.assertIn("r-a", self.st["last_done"])
        self.assertNotIn("r-a", self.st["attempts"])
        self.assertFalse(os.path.exists(os.path.join(self.d, "r-a.json")))
        # Exactly one report text for the whole run (M3), with the name in it.
        self.assertEqual(len(self.mark.calls), 1)
        self.assertIn("Failed reminders: Trash", self.mark.calls[0][0])
        # A later tick must not retry a handle marked final.
        self.tick(self.SLOT + timedelta(minutes=5))
        self.assertEqual(len(self.text.calls), 1)

    def test_retry_outcome_backs_off_like_a_plain_failure(self):
        write(self.d)
        self.text.ok = "retry"
        self.tick(self.SLOT + timedelta(seconds=20))
        self.assertEqual(len(self.text.calls), 1)
        self.assertIn("r-a", self.st["attempts"])
        too_soon = self.SLOT + timedelta(seconds=50)
        self.tick(too_soon)
        self.assertEqual(len(self.text.calls), 1)
        self.tick(self.SLOT + timedelta(seconds=20, minutes=1))
        self.assertEqual(len(self.text.calls), 2)

    def test_ok_outcome_string_behaves_like_true(self):
        write(self.d)
        self.text.ok = "ok"
        self.tick(self.SLOT + timedelta(seconds=20))
        self.assertIn("r-a", self.st["last_done"])
        self.assertFalse(os.path.exists(os.path.join(self.d, "r-a.json")))

    def test_smart_final_outcome_reports_failed_immediately(self):
        write(self.d, kind="smart", text=None, prompt="List chores")
        self.smart.ok = "final"
        self.tick(self.SLOT + timedelta(seconds=20))
        self.assertEqual(len(self.smart.calls), 1)
        self.assertIn("r-a", self.st["last_done"])
        self.assertEqual(len(self.mark.calls), 1)
        self.assertIn("Failed reminders: Trash", self.mark.calls[0][0])

    # --- Fix round 3 (R11: invalid files reported to Mark) ---

    def test_newly_invalid_file_reported_in_run_report(self):
        with open(os.path.join(self.d, "r-bad.json"), "w") as f:
            f.write("{nope")
        self.tick(self.SLOT)
        self.assertEqual(len(self.mark.calls), 1)
        self.assertIn("Invalid reminders: r-bad.json", self.mark.calls[0][0])
        # Not reported again once already logged (once-per-hash).
        self.tick(self.SLOT + timedelta(seconds=30))
        self.assertEqual(len(self.mark.calls), 1)

    # --- Fix round 3 (M3: at most one text to Mark per run) ---

    def test_skipped_failed_invalid_joined_into_one_notice(self):
        with open(os.path.join(self.d, "r-bad.json"), "w") as f:
            f.write("{nope")
        write(self.d, id="r-skip", schedule={"type": "once", "at": "2026-09-16T08:00:00+08:00"},
              name="Skipped One")
        write(self.d, id="r-fail", name="Failed One", late_limit_minutes=300)
        self.text.ok = "final"
        self.tick(self.SLOT + timedelta(hours=3))
        self.assertEqual(len(self.mark.calls), 1)
        body = self.mark.calls[0][0]
        self.assertIn("Skipped late reminders", body)
        self.assertIn("Failed reminders", body)
        self.assertIn("Invalid reminders", body)

    # --- Fix round 3 (I3: checkpoint called after every send attempt) ---

    def test_checkpoint_called_once_per_attempt(self):
        write(self.d, to=["+639170000001", "+639170000002"])
        checkpoints = []
        clock.run(self.d, self.st, self.SLOT + timedelta(seconds=20), "pc", ALLOW,
                   self.text, self.smart, self.mark, lambda e, x: self.logs.append((e, x)),
                   checkpoint=lambda: checkpoints.append(1))
        self.assertEqual(len(checkpoints), 2)

    # --- Fix round 2 (I3: checkpoint fires after the attempt's outcome
    # is already applied to st, not before) ---

    def test_checkpoint_sees_attempt_already_applied_to_state(self):
        write(self.d, to=["+639170000001", "+639170000002"])
        seen = []

        def checkpoint():
            # Snapshot state at the moment checkpoint fires - it must
            # already include this attempt, not the state as it was
            # before the send.
            partial = self.st.get("partial", {}).get("r-a")
            seen.append({
                "done": list(partial["done"]) if partial else None,
                "last_done": "r-a" in self.st.get("last_done", {}),
            })

        clock.run(self.d, self.st, self.SLOT + timedelta(seconds=20), "pc", ALLOW,
                   self.text, self.smart, self.mark, lambda e, x: self.logs.append((e, x)),
                   checkpoint=checkpoint)
        self.assertEqual(len(seen), 2)
        # After the first recipient's attempt: recorded in partial, not
        # yet the whole reminder's completion.
        self.assertEqual(seen[0], {"done": ["+639170000001"], "last_done": False})
        # After the second (final) recipient's attempt: the reminder is
        # fully done, so partial is already cleared and last_done is
        # already set - not a half-recorded state.
        self.assertEqual(seen[1], {"done": None, "last_done": True})

    def test_checkpoint_sees_last_done_after_final_recipient(self):
        write(self.d)  # single recipient
        seen_last_done = []

        def checkpoint():
            seen_last_done.append(dict(self.st.get("last_done", {})))

        clock.run(self.d, self.st, self.SLOT + timedelta(seconds=20), "pc", ALLOW,
                   self.text, self.smart, self.mark, lambda e, x: self.logs.append((e, x)),
                   checkpoint=checkpoint)
        self.assertEqual(len(seen_last_done), 1)
        # The only checkpoint call already sees last_done set and the
        # once file already deleted, not a half-recorded attempt.
        self.assertIn("r-a", seen_last_done[0])
        self.assertFalse(os.path.exists(os.path.join(self.d, "r-a.json")))

    # --- Fix round 3 (I4: time budget) ---

    def test_time_budget_stops_starting_new_sends(self):
        write(self.d, id="r-1")
        write(self.d, id="r-2")
        times = [0.0]

        def fake_monotonic():
            times[0] += 40.0
            return times[0]

        clock.run(self.d, self.st, self.SLOT + timedelta(seconds=20), "pc", ALLOW,
                   self.text, self.smart, self.mark, lambda e, x: self.logs.append((e, x)),
                   time_budget_s=90.0, monotonic=fake_monotonic)
        self.assertEqual(len(self.text.calls), 1)

    # --- Fix round 2 (I4: budget also checked per recipient, not only per file) ---

    def test_time_budget_checked_per_recipient_not_only_per_file(self):
        write(self.d, to=["+639170000001", "+639170000002", "+639170000003"])
        times = [0.0]

        def fake_monotonic():
            times[0] += 30.0
            return times[0]

        now = self.SLOT + timedelta(seconds=20)
        clock.run(self.d, self.st, now, "pc", ALLOW, self.text, self.smart, self.mark,
                   lambda e, x: self.logs.append((e, x)), time_budget_s=90.0,
                   monotonic=fake_monotonic)
        # Only the first recipient sent this tick; the file is still on
        # disk (not fully done) and the other two are picked up next tick.
        self.assertEqual([c[0] for c in self.text.calls], ["+639170000001"])
        self.assertTrue(os.path.exists(os.path.join(self.d, "r-a.json")))

        # A later tick, with a monotonic that never trips the budget,
        # finishes the job without resending the first recipient.
        self.tick(now + timedelta(minutes=1))
        self.assertEqual(
            [c[0] for c in self.text.calls],
            ["+639170000001", "+639170000002", "+639170000003"],
        )
        self.assertFalse(os.path.exists(os.path.join(self.d, "r-a.json")))
