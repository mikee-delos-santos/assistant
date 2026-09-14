import inspect
import os
import shutil
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
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_hung_gate_returns_retry_within_timeout(self):
        # exec replaces the shell with sleep, so killing the ssh process
        # actually stops the child instead of leaving it running past the
        # test (a plain background `sleep 30 &` would outlive the kill).
        _fake_ssh(self.tmp_dir, "exec sleep 30\n")
        start = time.time()
        outcome = senders.gate_send("key", "kh", "t", "+1", "hi", timeout=2)
        elapsed = time.time() - start
        self.assertEqual(outcome, "retry")
        self.assertLess(elapsed, 5, "gate_send should give up around its own timeout, not hang")

    def test_matching_result_is_ok(self):
        _fake_ssh(self.tmp_dir, 'read -r line\necho \'{"jsonrpc":"2.0","id":1,"result":{}}\'\n')
        self.assertEqual(senders.gate_send("key", "kh", "t", "+1", "hi", timeout=5), "ok")

    def test_error_with_retry_safe_true_is_retry(self):
        _fake_ssh(
            self.tmp_dir,
            'read -r line\necho \'{"jsonrpc":"2.0","id":1,"error":{"code":-32603,'
            '"message":"no","data":{"retry_safe":true}}}\'\n',
        )
        self.assertEqual(senders.gate_send("key", "kh", "t", "+1", "hi", timeout=5), "retry")

    def test_error_with_retry_safe_false_is_final(self):
        _fake_ssh(
            self.tmp_dir,
            'read -r line\necho \'{"jsonrpc":"2.0","id":1,"error":{"code":-32001,'
            '"message":"no","data":{"retry_safe":false}}}\'\n',
        )
        self.assertEqual(senders.gate_send("key", "kh", "t", "+1", "hi", timeout=5), "final")

    def test_error_without_retry_safe_is_final(self):
        _fake_ssh(
            self.tmp_dir,
            'read -r line\necho \'{"jsonrpc":"2.0","id":1,"error":{"code":-1,"message":"no"}}\'\n',
        )
        self.assertEqual(senders.gate_send("key", "kh", "t", "+1", "hi", timeout=5), "final")

    def test_connect_failure_before_any_output_is_retry(self):
        # ssh exits immediately (e.g. connection refused) without writing
        # anything: the request may never have reached the gate at all.
        _fake_ssh(self.tmp_dir, "exit 255\n")
        self.assertEqual(senders.gate_send("key", "kh", "t", "+1", "hi", timeout=5), "retry")

    def test_default_timeout_is_90_seconds(self):
        self.assertEqual(
            inspect.signature(senders.gate_send).parameters["timeout"].default, 90,
        )


if __name__ == "__main__":
    unittest.main()
