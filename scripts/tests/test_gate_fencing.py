"""Fencing tests for imsg-ssh-gate.py: --brain lease and the clock role.

Loads the gate module directly from its file path so the tests exercise the
real script without needing it installed anywhere.
"""
import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
GATE_PATH = os.path.join(HERE, "..", "imsg-ssh-gate.py")
spec = importlib.util.spec_from_file_location("gate", GATE_PATH)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class _PassthroughVisibility:
    """Stand-in for Visibility that never hides anything, so filter_line tests exercise
    only the fencing decision, not chat.db/CONFIG-dependent content filtering."""

    def filter_response(self, response):
        return response

    def filter_notification(self, note):
        return note


# A fake `imsg rpc` for wiring tests: echoes back {"id": ..., "result": {"ok": true}} for
# every JSON-RPC request it reads on stdin. It never sees requests the gate rejects
# itself (role-based rejections happen before anything is forwarded to the child).
FAKE_IMSG = '''#!/usr/bin/env python3
import json, sys
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        req = json.loads(line)
    except ValueError:
        continue
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": req.get("id"),
                                  "result": {"ok": True}}) + "\\n")
    sys.stdout.flush()
'''

# Runs inside its own subprocess: imports the gate module fresh, points it at the fake
# imsg and a temp log/lease, then runs run_rpc with the gate's own stdin/stdout (this
# subprocess's), so run_rpc's os._exit only ends this child, never the test process.
WRAPPER = '''
import importlib.util
spec = importlib.util.spec_from_file_location("gate", %(gate_path)r)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)
gate.IMSG = %(imsg_path)r
gate.LOG = %(log_path)r
gate.run_rpc([], role=%(role)r, lease_path=%(lease_path)r)
'''


class Fencing(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.lease = os.path.join(self.d, "active-brain")
        gate.LOG = os.path.join(self.d, "gate.log")

    def put(self, v):
        with open(self.lease, "w") as f:
            f.write(v)

    def test_parse_role(self):
        self.assertIsNone(gate.parse_role([]))
        self.assertEqual(gate.parse_role(["--brain", "mac"]), "mac")
        self.assertEqual(gate.parse_role(["--brain", "clock"]), "clock")
        with self.assertRaises(SystemExit):
            gate.parse_role(["--brain", "evil"])
        with self.assertRaises(SystemExit):
            gate.parse_role(["--brain"])
        with self.assertRaises(SystemExit):
            gate.parse_role(["--other", "pc"])

    def test_missing_lease_is_pc(self):
        self.assertEqual(gate.read_lease(self.lease), "pc")

    def test_garbage_lease_is_pc(self):
        self.put("banana")
        self.assertEqual(gate.read_lease(self.lease), "pc")

    def test_lease_with_newline(self):
        self.put("mac\n")
        self.assertEqual(gate.read_lease(self.lease), "mac")

    def test_receive_send_by_lease(self):
        self.put("mac")
        self.assertTrue(gate.may_receive("mac", self.lease))
        self.assertFalse(gate.may_receive("pc", self.lease))
        self.assertTrue(gate.may_send("mac", self.lease))
        self.assertFalse(gate.may_send("pc", self.lease))

    def test_legacy_role_unfenced(self):
        self.put("mac")
        self.assertTrue(gate.may_receive(None, self.lease))
        self.assertTrue(gate.may_send(None, self.lease))

    def test_clock(self):
        self.assertFalse(gate.may_receive("clock", self.lease))
        self.assertTrue(gate.may_send("clock", self.lease))
        self.assertTrue(gate.method_allowed_for_role("clock", "send"))
        self.assertFalse(gate.method_allowed_for_role("clock", "watch.subscribe"))
        self.assertFalse(gate.method_allowed_for_role("clock", "messages.history"))
        self.assertTrue(gate.method_allowed_for_role("pc", "watch.subscribe"))


class FilterLineFencing(unittest.TestCase):
    """Direct tests of the (now module-level) filter_line fencing decision, with a
    passthrough Visibility stand-in so results reflect fencing only."""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.lease = os.path.join(self.d, "active-brain")
        with open(self.lease, "w") as f:
            f.write("mac")
        gate.LOG = os.path.join(self.d, "gate.log")
        self.vis = _PassthroughVisibility()

    @staticmethod
    def line(obj):
        return json.dumps(obj).encode()

    def test_message_notification_dropped_when_not_lease_holder(self):
        note = self.line({"jsonrpc": "2.0", "method": "message",
                          "params": {"message": {"id": 1}}})
        self.assertIsNone(gate.filter_line(note, self.vis, "pc", self.lease))

    def test_response_still_passes_when_not_lease_holder(self):
        resp = self.line({"jsonrpc": "2.0", "id": 7, "result": {"ok": True}})
        out = gate.filter_line(resp, self.vis, "pc", self.lease)
        self.assertIsNotNone(out)
        self.assertEqual(json.loads(out.decode())["id"], 7)

    def test_non_message_notification_not_fenced(self):
        # Ruling: fencing applies only to "message" notifications. Any other method
        # still flows through the (here passthrough) visibility filter unchanged.
        note = self.line({"jsonrpc": "2.0", "method": "watch.pong", "params": {}})
        out = gate.filter_line(note, self.vis, "pc", self.lease)
        self.assertIsNotNone(out)
        self.assertEqual(json.loads(out.decode())["method"], "watch.pong")

    def test_message_notification_passes_for_lease_holder(self):
        note = self.line({"jsonrpc": "2.0", "method": "message",
                          "params": {"message": {"id": 1}}})
        out = gate.filter_line(note, self.vis, "mac", self.lease)
        self.assertIsNotNone(out)

    def test_message_notification_unfenced_for_legacy_role(self):
        note = self.line({"jsonrpc": "2.0", "method": "message",
                          "params": {"message": {"id": 1}}})
        out = gate.filter_line(note, self.vis, None, self.lease)
        self.assertIsNotNone(out)

    def test_message_notification_dropped_for_clock(self):
        note = self.line({"jsonrpc": "2.0", "method": "message",
                          "params": {"message": {"id": 1}}})
        self.assertIsNone(gate.filter_line(note, self.vis, "clock", self.lease))


class Wiring(unittest.TestCase):
    """End-to-end tests of run_rpc's request loop: the gate is run as a real subprocess
    (so its os._exit cannot kill the test process), with gate.IMSG pointed at a tiny
    fake `imsg rpc` and the lease path pointed at a temp file."""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.imsg = os.path.join(self.d, "fake-imsg.py")
        with open(self.imsg, "w") as f:
            f.write(FAKE_IMSG)
        os.chmod(self.imsg, os.stat(self.imsg).st_mode | stat.S_IEXEC)

    def run_gate(self, role, lease_value, requests, timeout=10):
        lease_path = os.path.join(self.d, "lease")
        with open(lease_path, "w") as f:
            f.write(lease_value)
        wrapper = WRAPPER % {
            "gate_path": GATE_PATH,
            "imsg_path": self.imsg,
            "log_path": os.path.join(self.d, "gate.log"),
            "role": role,
            "lease_path": lease_path,
        }
        proc = subprocess.Popen([sys.executable, "-c", wrapper], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        data = b"".join((json.dumps(req) + "\n").encode() for req in requests)
        out, err = proc.communicate(input=data, timeout=timeout)
        lines = [json.loads(l) for l in out.decode().splitlines() if l.strip()]
        return lines, proc.returncode

    def test_send_rejected_when_not_lease_holder(self):
        lines, _ = self.run_gate("pc", "mac", [
            {"jsonrpc": "2.0", "id": 1, "method": "send",
             "params": {"to": "+639171234567", "text": "hi"}}])
        self.assertEqual(len(lines), 1)
        self.assertIn("error", lines[0])
        self.assertIn("not the active brain", lines[0]["error"]["message"])

    def test_clock_rejected_for_non_send_method(self):
        lines, _ = self.run_gate("clock", "pc", [
            {"jsonrpc": "2.0", "id": 1, "method": "chats.list", "params": {}}])
        self.assertEqual(len(lines), 1)
        self.assertIn("error", lines[0])
        self.assertIn("not allowed for clock", lines[0]["error"]["message"])

    def test_legacy_role_unfenced_for_allowed_method(self):
        lines, _ = self.run_gate(None, "pc", [
            {"jsonrpc": "2.0", "id": 1, "method": "status", "params": {}}])
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0].get("result"), {"ok": True})


if __name__ == "__main__":
    unittest.main()
