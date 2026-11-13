from types import SimpleNamespace
import unittest
from pc_app.port_recovery import PortRecovery, SerialHeartbeat


def port(name, serial=None, vid=0x303A, pid=0x1001):
    return SimpleNamespace(device=name, serial_number=serial, vid=vid, pid=pid)


class RecoveryTests(unittest.TestCase):
    def test_heartbeat_detects_silent_port_without_infinite_retry_extension(self):
        h = SerialHeartbeat(timeout_seconds=18)
        self.assertFalse(h.expired(100))
        h.ping(100)
        h.ping(110)  # second PING must not reset original deadline
        self.assertFalse(h.expired(118))
        self.assertTrue(h.expired(119))
        h.pong()
        self.assertFalse(h.expired(1000))
        h.ping(1000)
        self.assertTrue(h.expired(1019))
        h.reset()
        self.assertFalse(h.expired(1019))

    def test_reconnect_by_unique_usb_serial_on_new_com(self):
        recovery = PortRecovery()
        self.assertTrue(recovery.remember([port("COM3", "ESP-S3-007")], "COM3"))
        self.assertEqual(recovery.find([
            port("COM9", "ESP-S3-007"), port("COM3", "another")
        ]), "COM9")
        self.assertIsNone(recovery.find([
            port("COM9", "ESP-S3-007"), port("COM10", "ESP-S3-007")
        ]))

    def test_without_serial_only_exact_port_and_vid_pid(self):
        recovery = PortRecovery()
        recovery.remember([port("COM3")], "COM3")
        self.assertIsNone(recovery.find([port("COM9")]))
        self.assertIsNone(recovery.find([port("COM3", vid=111, pid=222)]))
        self.assertEqual(recovery.find([port("COM3")]), "COM3")


if __name__ == "__main__":
    unittest.main()
