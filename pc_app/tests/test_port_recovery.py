from types import SimpleNamespace
import unittest
from pc_app.port_recovery import PortRecovery


def port(name, serial=None, vid=0x303A, pid=0x1001):
    return SimpleNamespace(device=name, serial_number=serial, vid=vid, pid=pid)


class RecoveryTests(unittest.TestCase):
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
