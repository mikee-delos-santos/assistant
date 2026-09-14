import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from brain_control import main


class FakeIO(object):
    # main.py reads and writes local files (lease, mode, state) through
    # brain_control.senders directly, not through io, so this fake only
    # needs to cover the external-I/O calls: health checks, docker, and
    # the two message senders.
    def __init__(self):
        self.healthy = True
        self.running = False
        self.sync = True
        self.compose = []
        self.compose_ok = True
        self.sent = []
        self.hooks = []

    def pc_healthy(self, url):
        return self.healthy

    def syncthing_in_sync(self, cfg, folder, name):
        return self.sync

    def docker_running(self, docker, name):
        return self.running

    def docker_compose(self, docker, repo, action):
        self.compose.append(action)
        return self.compose_ok

    def gate_send(self, key, kh, target, handle, text, timeout=60):
        self.sent.append((handle, text))
        return True

    def hook_agent(self, url, token, payload):
        self.hooks.append((url, payload))
        return True


class Tick(unittest.TestCase):
    def setUp(self):
        d = self.d = tempfile.mkdtemp()
        os.mkdir(os.path.join(d, "rem"))
        with open(os.path.join(d, ".env"), "w") as f:
            f.write("IMESSAGE_ALLOW_FROM=+639170000001\nMARK_IMESSAGE_HANDLE=+639170000001\n")
        with open(os.path.join(d, "hooks-token"), "w") as f:
            f.write("tok")
        # A properly-fenced authorized_keys by default, so the unfenced-gate
        # guard (I1) does not interfere with tests that are not about it.
        with open(os.path.join(d, "authorized_keys"), "w") as f:
            f.write('command="imsg-ssh-gate --brain mac" ssh-ed25519 AAAAtest\n')
        self.cfg = dict(
            (k, os.path.join(d, v)) for k, v in dict(
                lease_path="lease", mode_path="mode", state_path="state.json", lock_path="lock",
                log_path="log", reminders_dir="rem", env_path=".env", hooks_token_path="hooks-token",
                repo_dir=".", clock_ssh_key="k", clock_known_hosts="kh",
                authorized_keys_path="authorized_keys").items())
        self.cfg.update(docker="docker", pc_health_url="u", syncthing_config="x", syncthing_folder="f",
                         pc_device_name="pc", mark_handle_env="MARK_IMESSAGE_HANDLE", clock_ssh_target="t",
                         hooks_urls={"pc": "http://pc", "mac": "http://mac"})
        self.io = FakeIO()

    def log_lines(self):
        with open(self.cfg["log_path"]) as f:
            return f.read().splitlines()

    def mode(self, m):
        with open(self.cfg["mode_path"], "w") as f:
            f.write(m)

    def test_mode_off_by_default_does_no_failover(self):
        self.io.healthy = False
        for _ in range(10):
            main.tick(self.cfg, io=self.io)
        self.assertEqual(self.io.compose, [])
        self.assertFalse(os.path.exists(self.cfg["lease_path"]))

    def test_auto_failover_writes_lease_starts_and_notifies(self):
        self.mode("auto")
        self.io.healthy = False
        for _ in range(5):
            main.tick(self.cfg, io=self.io)
        with open(self.cfg["lease_path"]) as f:
            self.assertEqual(f.read().strip(), "mac")
        self.assertEqual(self.io.compose, ["up"])
        self.assertEqual(len(self.io.sent), 1)

    def test_corrupt_state_recovered(self):
        with open(self.cfg["state_path"], "w") as f:
            f.write("{bad")
        main.tick(self.cfg, io=self.io)
        self.assertTrue(any(n.startswith("state.json.bad-") for n in os.listdir(self.d)))

    def test_smart_uses_lease_url(self):
        with open(self.cfg["lease_path"], "w") as f:
            f.write("mac")
        r = {"version": 1, "id": "r-s", "kind": "smart", "name": "Chores", "to": ["+639170000001"],
             "text": None, "prompt": "chores?", "schedule": {"type": "once", "at": "2026-09-16T08:00:00+08:00"},
             "created_at": "2026-09-15T00:00:00Z", "created_by": "brice"}
        with open(os.path.join(self.cfg["reminders_dir"], "r-s.json"), "w") as f:
            json.dump(r, f)
        main.tick(self.cfg, now=datetime(2026, 9, 16, 0, 0, 30, tzinfo=timezone.utc), io=self.io)
        self.assertEqual(self.io.hooks[0][0], "http://mac")

    def test_clock_exception_still_saves_state(self):
        with open(self.cfg["state_path"], "w") as f:
            json.dump({"failover": {}, "clock": {"last_done": {"r-x": "2026-09-15T00:00:00Z"}}}, f)
        with mock.patch("brain_control.main.clock.run", side_effect=RuntimeError("boom")):
            main.tick(self.cfg, io=self.io)  # must not raise: tick catches and logs
        with open(self.cfg["state_path"]) as f:
            saved = json.load(f)
        self.assertEqual(saved["clock"]["last_done"]["r-x"], "2026-09-15T00:00:00Z")

    def test_non_object_state_json_treated_as_corrupt(self):
        with open(self.cfg["state_path"], "w") as f:
            f.write("[1, 2, 3]")  # valid JSON, but a state file must be an object
        main.tick(self.cfg, io=self.io)  # must not raise
        self.assertTrue(any(n.startswith("state.json.bad-") for n in os.listdir(self.d)))
        with open(self.cfg["state_path"]) as f:
            saved = json.load(f)
        self.assertIn("failover", saved)
        self.assertIn("clock", saved)

    # --- Fix round 3 (M6: _read_env strips one pair of matching quotes) ---

    def test_read_env_strips_matching_quotes(self):
        with open(self.cfg["env_path"], "w") as f:
            f.write('A="hello"\nB=\'world\'\nC=bare\nD="mismatched\'\nE=""\n')
        env = main._read_env(self.cfg["env_path"])
        self.assertEqual(env["A"], "hello")
        self.assertEqual(env["B"], "world")
        self.assertEqual(env["C"], "bare")
        self.assertEqual(env["D"], "\"mismatched'")  # mismatched: left untouched
        self.assertEqual(env["E"], "")

    # --- Fix round 3 (C3: missing mark handle logged once per tick) ---

    def test_missing_mark_handle_logs_config_missing_once_per_tick(self):
        with open(self.cfg["env_path"], "w") as f:
            f.write("IMESSAGE_ALLOW_FROM=+639170000001\n")  # no MARK_IMESSAGE_HANDLE
        self.mode("auto")
        self.io.healthy = False
        for _ in range(5):
            main.tick(self.cfg, io=self.io)
        lines = [l for l in self.log_lines() if "config_missing" in l]
        # 5 ticks, but only failover's 5th tick actually fires a notice
        # attempt; every tick with a missing handle logs it once.
        self.assertEqual(len(lines), 5)
        self.assertTrue(all("mark_handle" in l for l in lines))

    # --- Fix round 3 (I1/R13: unfenced gate line pauses failover) ---

    def test_unfenced_gate_line_pauses_failover(self):
        with open(self.cfg["authorized_keys_path"], "w") as f:
            f.write('command="imsg-ssh-gate" ssh-ed25519 AAAAtest\n')  # no --brain
        self.mode("auto")
        self.io.healthy = False
        for _ in range(10):
            main.tick(self.cfg, io=self.io)
        self.assertEqual(self.io.compose, [])
        self.assertFalse(os.path.exists(self.cfg["lease_path"]))
        lines = [l for l in self.log_lines() if "unfenced_gate_line" in l]
        self.assertEqual(len(lines), 10)

    def test_unfenced_gate_line_sends_one_notice_per_24h(self):
        with open(self.cfg["authorized_keys_path"], "w") as f:
            f.write('command="imsg-ssh-gate" ssh-ed25519 AAAAtest\n')
        self.mode("auto")
        t0 = datetime(2026, 9, 15, 0, 0, tzinfo=timezone.utc)
        for i in range(3):
            main.tick(self.cfg, now=t0 + timedelta(minutes=i), io=self.io)
        self.assertEqual(len(self.io.sent), 1)
        main.tick(self.cfg, now=t0 + timedelta(hours=25), io=self.io)
        self.assertEqual(len(self.io.sent), 2)

    def test_missing_authorized_keys_treated_as_unfenced(self):
        os.remove(self.cfg["authorized_keys_path"])
        self.mode("auto")
        self.io.healthy = False
        main.tick(self.cfg, io=self.io)
        self.assertEqual(self.io.compose, [])
        lines = [l for l in self.log_lines() if "unfenced_gate_line" in l]
        self.assertEqual(len(lines), 1)

    def test_undecodable_authorized_keys_treated_as_unfenced(self):
        # Binary garbage the "r" mode can't decode as text at all -
        # UnicodeDecodeError, not OSError - must fail safe the same way.
        with open(self.cfg["authorized_keys_path"], "wb") as f:
            f.write(b"\xff\xfe\x00\xff not valid utf-8 \x80\x81")
        self.mode("auto")
        self.io.healthy = False
        main.tick(self.cfg, io=self.io)
        self.assertEqual(self.io.compose, [])
        lines = [l for l in self.log_lines() if "unfenced_gate_line" in l]
        self.assertEqual(len(lines), 1)

    def test_unfenced_notice_not_delivered_retries_next_tick_not_in_24h(self):
        with open(self.cfg["authorized_keys_path"], "w") as f:
            f.write('command="imsg-ssh-gate" ssh-ed25519 AAAAtest\n')  # no --brain

        class Undelivered(FakeIO):
            def gate_send(self, key, kh, target, handle, text, timeout=90):
                self.sent.append((handle, text))
                return "final"

        self.io = Undelivered()
        self.mode("auto")
        t0 = datetime(2026, 9, 15, 0, 0, tzinfo=timezone.utc)
        main.tick(self.cfg, now=t0, io=self.io)
        main.tick(self.cfg, now=t0 + timedelta(minutes=1), io=self.io)
        # Neither attempt was delivered, so last_notice_at was never set:
        # every tick keeps trying, not waiting out a 24h window that a
        # real delivery never actually started.
        self.assertEqual(len(self.io.sent), 2)

    def test_fenced_gate_line_does_not_block_failover(self):
        # authorized_keys already has a --brain-fenced line from setUp.
        self.mode("auto")
        self.io.healthy = False
        for _ in range(5):
            main.tick(self.cfg, io=self.io)
        self.assertEqual(self.io.compose, ["up"])

    def test_gate_check_skipped_in_pc_mode(self):
        with open(self.cfg["authorized_keys_path"], "w") as f:
            f.write('command="imsg-ssh-gate" ssh-ed25519 AAAAtest\n')  # no --brain
        with open(self.cfg["lease_path"], "w") as f:
            f.write("mac")
        self.io.running = True
        self.mode("pc")
        main.tick(self.cfg, io=self.io)
        with open(self.cfg["lease_path"]) as f:
            self.assertEqual(f.read().strip(), "pc")

    # --- Fix round 2 (I3: checkpoint wired into main._run_clock with a
    # real atomic full-state save) ---

    def test_checkpoint_persists_state_after_first_recipient_before_crash(self):
        r = {"version": 1, "id": "r-two", "kind": "text", "name": "Two people",
             "to": ["+639170000001", "+639170000002"], "text": "hi", "prompt": None,
             "schedule": {"type": "once", "at": "2026-09-16T00:00:20Z"}, "tz": "Asia/Manila",
             "late_limit_minutes": 120, "created_at": "2026-09-15T00:00:00Z",
             "created_by": "brice"}
        with open(os.path.join(self.cfg["reminders_dir"], "r-two.json"), "w") as f:
            json.dump(r, f)
        with open(self.cfg["env_path"], "w") as f:
            f.write("IMESSAGE_ALLOW_FROM=+639170000001,+639170000002\n"
                     "MARK_IMESSAGE_HANDLE=+639170000001\n")

        class InterruptsOnSecondSend(FakeIO):
            def gate_send(self, key, kh, target, handle, text, timeout=90):
                self.sent.append((handle, text))
                if len(self.sent) >= 2:
                    raise KeyboardInterrupt()
                return True

        self.io = InterruptsOnSecondSend()
        now = datetime(2026, 9, 16, 0, 0, 30, tzinfo=timezone.utc)
        with self.assertRaises(KeyboardInterrupt):
            main.tick(self.cfg, now=now, io=self.io)
        with open(self.cfg["state_path"]) as f:
            saved = json.load(f)
        self.assertEqual(saved["clock"]["partial"]["r-two"]["done"], ["+639170000001"])

    def test_checkpoint_writes_state_more_than_once_per_tick(self):
        # Distinguishes real per-attempt checkpointing from the single
        # save already done in _run_clock's finally block: two sends in
        # one tick must mean at least two extra state writes beyond that
        # one final save.
        r = {"version": 1, "id": "r-two", "kind": "text", "name": "Two people",
             "to": ["+639170000001", "+639170000002"], "text": "hi", "prompt": None,
             "schedule": {"type": "once", "at": "2026-09-16T00:00:20Z"}, "tz": "Asia/Manila",
             "late_limit_minutes": 120, "created_at": "2026-09-15T00:00:00Z",
             "created_by": "brice"}
        with open(os.path.join(self.cfg["reminders_dir"], "r-two.json"), "w") as f:
            json.dump(r, f)
        with open(self.cfg["env_path"], "w") as f:
            f.write("IMESSAGE_ALLOW_FROM=+639170000001,+639170000002\n"
                     "MARK_IMESSAGE_HANDLE=+639170000001\n")
        now = datetime(2026, 9, 16, 0, 0, 30, tzinfo=timezone.utc)
        calls = []
        real_write_atomic = main._senders.write_atomic

        def spy(path, data, mode=0o600):
            if path == self.cfg["state_path"]:
                calls.append(1)
            return real_write_atomic(path, data, mode)

        with mock.patch("brain_control.main._senders.write_atomic", side_effect=spy):
            main.tick(self.cfg, now=now, io=self.io)
        # 2 checkpoints (one per recipient) + the failover save + the
        # clock step's own finally save.
        self.assertGreaterEqual(len(calls), 4)

    # --- Fix round 3 (notify_mark treats a non-"ok" gate_send result as
    # not delivered: log only, never raise, never resend) ---

    def test_notify_mark_logs_when_gate_send_is_not_ok(self):
        write_reminder = {"version": 1, "id": "r-skip", "kind": "text", "name": "Old one",
                           "to": ["+639170000001"], "text": "x", "prompt": None,
                           "schedule": {"type": "once", "at": "2026-09-01T00:00:00Z"},
                           "tz": "Asia/Manila", "late_limit_minutes": 120,
                           "created_at": "2026-08-01T00:00:00Z", "created_by": "brice"}
        with open(os.path.join(self.cfg["reminders_dir"], "r-skip.json"), "w") as f:
            json.dump(write_reminder, f)

        class Undelivered(FakeIO):
            def gate_send(self, key, kh, target, handle, text, timeout=90):
                self.sent.append((handle, text))
                return "final"

        self.io = Undelivered()
        main.tick(self.cfg, now=datetime(2026, 9, 15, 1, 0, tzinfo=timezone.utc), io=self.io)
        self.assertEqual(len(self.io.sent), 1)
        lines = [l for l in self.log_lines() if "notice_undelivered" in l]
        self.assertEqual(len(lines), 1)
        # Never the notice text itself.
        self.assertNotIn("Old one", lines[0])

    # --- Fix round 3 (M2: docker up failure gets its own notice text) ---

    def test_docker_up_failure_has_its_own_notice_text(self):
        self.mode("auto")
        self.io.healthy = False
        self.io.compose_ok = False
        for _ in range(5):
            main.tick(self.cfg, io=self.io)
        self.assertEqual(self.io.compose, ["up"])
        self.assertEqual(len(self.io.sent), 1)
        self.assertIn("did not start", self.io.sent[0][1])
        self.assertIn("Docker", self.io.sent[0][1])

    # --- Fix round 3 (M1: corrupt-state recovery does not resend recurring reminders) ---

    def test_corrupt_state_recovery_seeds_last_done_from_due_slot(self):
        r = {"version": 1, "id": "r-daily", "kind": "text", "name": "Water plants",
             "to": ["+639170000001"], "text": "Water", "prompt": None,
             "schedule": {"type": "daily", "time": "08:00"}, "tz": "Asia/Manila",
             "late_limit_minutes": 1440, "created_at": "2026-09-01T00:00:00Z",
             "created_by": "brice"}
        with open(os.path.join(self.cfg["reminders_dir"], "r-daily.json"), "w") as f:
            json.dump(r, f)
        with open(self.cfg["state_path"], "w") as f:
            f.write("{bad")
        now = datetime(2026, 9, 15, 1, 0, tzinfo=timezone.utc)  # 09:00 Manila: already due
        main.tick(self.cfg, now=now, io=self.io)
        # Not resent (the reminder's own text never goes out this tick) -
        # the only send is the single Skipped-report notice (R15).
        self.assertEqual(self.io.sent, [("+639170000001", "Skipped late reminders: Water plants")])
        with open(self.cfg["state_path"]) as f:
            saved = json.load(f)
        self.assertIn("r-daily", saved["clock"]["last_done"])

    # --- Fix round 2 (R15: once reminders never seeded; recurring
    # reminders' names go on the tick's Skipped report) ---

    def test_corrupt_state_recovery_never_seeds_once_reminders(self):
        r = {"version": 1, "id": "r-once", "kind": "text", "name": "Pay rent",
             "to": ["+639170000001"], "text": "Pay rent", "prompt": None,
             "schedule": {"type": "once", "at": "2026-09-15T00:30:00Z"}, "tz": "Asia/Manila",
             "late_limit_minutes": 1440, "created_at": "2026-09-01T00:00:00Z",
             "created_by": "brice"}
        with open(os.path.join(self.cfg["reminders_dir"], "r-once.json"), "w") as f:
            json.dump(r, f)
        with open(self.cfg["state_path"], "w") as f:
            f.write("{bad")
        now = datetime(2026, 9, 15, 1, 0, tzinfo=timezone.utc)  # already due
        main.tick(self.cfg, now=now, io=self.io)
        # A once file still on disk is itself the proof it was never
        # completed: it must still be sent, not silently marked done.
        self.assertIn(("+639170000001", "(late) Pay rent"), self.io.sent)
        with open(self.cfg["state_path"]) as f:
            saved = json.load(f)
        self.assertIn("r-once", saved["clock"]["last_done"])
        self.assertFalse(os.path.exists(os.path.join(self.cfg["reminders_dir"], "r-once.json")))


if __name__ == "__main__":
    unittest.main()
