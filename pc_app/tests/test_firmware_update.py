import tempfile
from pathlib import Path
import unittest

from pc_app.firmware_update import inspect_firmware, flash_command
from pc_app.tests.esp_image_fixture import make_test_image


class FirmwareTests(unittest.TestCase):
    def test_valid_esp_image_only_and_fixed_address(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "firmware.bin"
            payload = make_test_image()
            path.write_bytes(payload)
            digest, length = inspect_firmware(str(path))
            self.assertEqual(length, len(payload))
            self.assertEqual(len(digest), 64)
            cmd = flash_command("COM5", str(path))
            self.assertIn("esp32s3", cmd)
            self.assertEqual(cmd[-2], "0x10000")
            self.assertNotIn("erase_flash", cmd)
            path.write_bytes(b"NO" + bytes(2200))
            with self.assertRaises(ValueError):
                inspect_firmware(str(path))
            path.write_bytes(make_test_image(chip_id=0))
            with self.assertRaisesRegex(ValueError, "ESP32-S3"):
                inspect_firmware(str(path))
            path.write_bytes(make_test_image(content=bytes(range(256)) * 9))
            with self.assertRaisesRegex(ValueError, "descriptor"):
                inspect_firmware(str(path))
            # Descriptor-like bytes in an unrelated segment are not proof of an app.
            path.write_bytes(make_test_image(segment_address=0x3FC00020))
            with self.assertRaisesRegex(ValueError, "DROM"):
                inspect_firmware(str(path))
            # A stray signature late in DROM must not disguise a bootloader.
            path.write_bytes(make_test_image(content=bytes(128) + bytes.fromhex("3254cdab") + bytes(2200)))
            with self.assertRaisesRegex(ValueError, "DROM"):
                inspect_firmware(str(path))
            # The two known ESP-IDF app-descriptor layouts are supported.
            path.write_bytes(make_test_image(content=bytes.fromhex("3254cdab") + bytes(2300)))
            inspect_firmware(str(path))
            path.write_bytes(payload)
            damaged = bytearray(payload)
            damaged[100] ^= 1
            path.write_bytes(damaged)
            with self.assertRaises(ValueError):
                inspect_firmware(str(path))


if __name__ == "__main__":
    unittest.main()
