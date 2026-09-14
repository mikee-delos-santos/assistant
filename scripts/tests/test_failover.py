import unittest

from brain_control.failover import Inputs, step, FAIL_TICKS, OK_TICKS, UNSYNCED_NOTICE_TICKS


def I(**k):
    d = dict(mode="auto", lease="pc", pc_healthy=True, pc_in_sync=True, mac_running=False)
    d.update(k)
    return Inputs(**d)


class Auto(unittest.TestCase):
    def test_pc_fine_nothing(self):
        st = {}
        a = step(I(), st)
        self.assertEqual((a.lease, a.docker, a.notices), (None, None, []))

    def test_failover_after_streak(self):
        st = {}
        for _ in range(FAIL_TICKS - 1):
            self.assertIsNone(step(I(pc_healthy=False), st).lease)
        a = step(I(pc_healthy=False), st)
        self.assertEqual((a.lease, a.docker), ("mac", "up"))
        self.assertEqual(len(a.notices), 1)

    def test_one_good_check_resets(self):
        st = {}
        for _ in range(FAIL_TICKS - 1):
            step(I(pc_healthy=False), st)
        step(I(), st)
        self.assertIsNone(step(I(pc_healthy=False), st).lease)

    def test_stray_mac_brain_stopped(self):
        st = {}
        self.assertIsNone(step(I(mac_running=True), st).docker)
        self.assertEqual(step(I(mac_running=True), st).docker, "stop")

    def test_mac_lease_restarts_brain(self):
        self.assertEqual(step(I(lease="mac", pc_healthy=False), {}).docker, "up")

    def test_failback_needs_streak_and_sync(self):
        st = {}
        for _ in range(OK_TICKS - 1):
            self.assertIsNone(step(I(lease="mac", mac_running=True), st).lease)
        a = step(I(lease="mac", mac_running=True), st)
        self.assertEqual((a.lease, a.docker), ("pc", "stop"))

    def test_no_failback_without_sync_and_one_notice(self):
        st = {}
        notices = 0
        for _ in range(OK_TICKS + UNSYNCED_NOTICE_TICKS + 5):
            a = step(I(lease="mac", mac_running=True, pc_in_sync=False), st)
            self.assertIsNone(a.lease)
            notices += len(a.notices)
        self.assertEqual(notices, 1)


class Manual(unittest.TestCase):
    def test_off(self):
        st = {"fail_streak": 3}
        a = step(I(mode="off", pc_healthy=False), st)
        self.assertEqual((a.lease, a.docker), (None, None))
        self.assertEqual(st, {"fail_streak": 3})

    def test_pin_mac(self):
        a = step(I(mode="mac"), {})
        self.assertEqual((a.lease, a.docker), ("mac", "up"))

    def test_pin_pc(self):
        a = step(I(mode="pc", lease="mac", mac_running=True), {})
        self.assertEqual((a.lease, a.docker), ("pc", "stop"))

    def test_unknown_mode_is_off(self):
        a = step(I(mode="yolo", pc_healthy=False), {})
        self.assertEqual((a.lease, a.docker), (None, None))


if __name__ == "__main__":
    unittest.main()
