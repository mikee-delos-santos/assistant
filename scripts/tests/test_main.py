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
        self.assertEqual(self.io.sent, [])  # not resent, even though it's newly due
        with open(self.cfg["state_path"]) as f:
            saved = json.load(f)
        self.assertIn("r-daily", saved["clock"]["last_done"])


if __name__ == "__main__":
    unittest.main()
