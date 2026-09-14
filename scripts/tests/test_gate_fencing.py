"""Fencing tests for imsg-ssh-gate.py: --brain lease and the clock role.

Loads the gate module directly from its file path so the tests exercise the
real script without needing it installed anywhere.
"""
import importlib.util
import os
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("gate", os.path.join(HERE, "..", "imsg-ssh-gate.py"))
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


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


if __name__ == "__main__":
    unittest.main()
