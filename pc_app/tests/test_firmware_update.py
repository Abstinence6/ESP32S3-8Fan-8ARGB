import tempfile
from pathlib import Path
import unittest

from pc_app.firmware_update import inspect_firmware, flash_command


class FirmwareTests(unittest.TestCase):
    def test_valid_esp_image_only_and_fixed_address(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "firmware.bin"
            path.write_bytes(bytes([0xE9, 3, 0, 0, 0, 0, 0, 0]) + bytes(2200))
            digest, length = inspect_firmware(str(path))
            self.assertEqual(length, 2208)
            self.assertEqual(len(digest), 64)
            cmd = flash_command("COM5", str(path))
            self.assertIn("esp32s3", cmd)
            self.assertEqual(cmd[-2], "0x10000")
            self.assertNotIn("erase_flash", cmd)
            path.write_bytes(b"NO" + bytes(2200))
            with self.assertRaises(ValueError):
                inspect_firmware(str(path))


if __name__ == "__main__":
    unittest.main()
