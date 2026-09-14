import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
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
        return True

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
        self.cfg = dict(
            (k, os.path.join(d, v)) for k, v in dict(
                lease_path="lease", mode_path="mode", state_path="state.json", lock_path="lock",
                log_path="log", reminders_dir="rem", env_path=".env", hooks_token_path="hooks-token",
                repo_dir=".", clock_ssh_key="k", clock_known_hosts="kh").items())
        self.cfg.update(docker="docker", pc_health_url="u", syncthing_config="x", syncthing_folder="f",
                         pc_device_name="pc", mark_handle_env="MARK_IMESSAGE_HANDLE", clock_ssh_target="t",
                         hooks_urls={"pc": "http://pc", "mac": "http://mac"})
        self.io = FakeIO()

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


if __name__ == "__main__":
    unittest.main()
