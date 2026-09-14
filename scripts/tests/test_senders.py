import os
import stat
import tempfile
import time
import unittest
from unittest import mock

from brain_control import senders


def _fake_ssh(tmp_dir, body):
    """Write an executable named `ssh` on PATH that runs `body` (a bash
    script fragment) instead of a real ssh connection."""
    path = os.path.join(tmp_dir, "ssh")
    with open(path, "w") as f:
        f.write("#!/bin/bash\n" + body)
    st = os.stat(path)
    os.chmod(path, st.st_mode | stat.S_IEXEC)
    return path


class GateSend(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = self.tmp_dir + os.pathsep + self.old_path

    def tearDown(self):
        os.environ["PATH"] = self.old_path

    def test_hung_gate_returns_false_within_timeout(self):
        _fake_ssh(self.tmp_dir, "sleep 30\n")
        start = time.time()
        ok = senders.gate_send("key", "kh", "t", "+1", "hi", timeout=2)
        elapsed = time.time() - start
        self.assertFalse(ok)
        self.assertLess(elapsed, 5, "gate_send should give up around its own timeout, not hang")

    def test_matching_result_is_true(self):
        _fake_ssh(self.tmp_dir, 'read -r line\necho \'{"jsonrpc":"2.0","id":1,"result":{}}\'\n')
        self.assertTrue(senders.gate_send("key", "kh", "t", "+1", "hi", timeout=5))

    def test_error_response_is_false(self):
        _fake_ssh(
            self.tmp_dir,
            'read -r line\necho \'{"jsonrpc":"2.0","id":1,"error":{"code":-1,"message":"no"}}\'\n',
        )
        self.assertFalse(senders.gate_send("key", "kh", "t", "+1", "hi", timeout=5))


if __name__ == "__main__":
    unittest.main()
