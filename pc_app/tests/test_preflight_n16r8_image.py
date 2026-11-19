"""Offline checks preventing standalone app/DC-variant misflashing at 0x0."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.preflight_n16r8_image import IMAGE_NAME, verify_full_image


class N16R8PreflightTests(unittest.TestCase):
    def make_image(self, root: Path) -> tuple[Path, dict]:
        data = bytearray(b"\xFF" * (0x10000 + 1200))
        for offset in (0, 0x10000):
            data[offset:offset + 2] = b"\xE9\x03"
            data[offset + 12:offset + 14] = (9).to_bytes(2, "little")
        data[0x8000:0x8002] = b"\xAA\x50"
        data[0xE000:0xE004] = b"OTA!"
        path = root / IMAGE_NAME
        path.write_bytes(data)
        manifest = {
            "component": "firmware",
            "source_commit": "a" * 40,
            "target": {
                "platformio_env": "esp32s3_n16r8_native_usb",
                "module": "ESP32-S3-WROOM-1-N16R8",
                "flash_size": "16MB",
                "merged_image": IMAGE_NAME,
                "merged_flash_offset": "0x0",
                "channel_mask": 253,
                "disabled_channels": [2],
                "diagnostic_only": False,
                "nvs_reset_when_merged_flashing": True,
            },
            "files": {
                IMAGE_NAME: {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            },
        }
        (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return path, manifest

    def test_valid_standard_full_image_and_explicit_sha(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, manifest = self.make_image(Path(tmp))
            report = verify_full_image(path)
            self.assertEqual(report["flash_offset"], "0x0")
            self.assertTrue(report["nvs_will_be_overwritten"])
            self.assertFalse(report["hardware_verified"])
            self.assertEqual(report["source_commit"], "a" * 40)
            (path.parent / "manifest.json").unlink()
            report = verify_full_image(path, expected_sha256=manifest["files"][IMAGE_NAME]["sha256"])
            self.assertEqual(report["sha256"], manifest["files"][IMAGE_NAME]["sha256"])
            with self.assertRaisesRegex(ValueError, "trusted"):
                verify_full_image(path)

    def test_reject_application_only_corruption_and_bad_locations(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, _ = self.make_image(Path(tmp))
            initial = path.read_bytes()
            path.write_bytes(initial[0x10000:])
            with self.assertRaisesRegex(ValueError, "size"):
                verify_full_image(path)
            path.write_bytes(initial)
            for offset, expected in ((0x8000, "partition"), (0x10000, "application"),
                                     (0xE000, "boot_app0"), (0xA000, "NVS")):
                data = bytearray(initial)
                if offset == 0xE000:
                    data[offset:offset + 0x100] = b"\xFF" * 0x100
                else:
                    data[offset] = 0
                path.write_bytes(data)
                with self.subTest(offset=hex(offset)):
                    with self.assertRaisesRegex(ValueError, expected):
                        verify_full_image(path)
            path.write_bytes(initial)
            bad = bytearray(initial)
            bad[-1] ^= 0x01
            path.write_bytes(bad)
            with self.assertRaisesRegex(ValueError, "manifest"):
                verify_full_image(path)

    def test_reject_dc_unlocked_and_wrong_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, manifest = self.make_image(Path(tmp))
            manifest["target"]["platformio_env"] = "esp32s3_n16r8_native_usb_dc_validated"
            (path.parent / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "standard"):
                verify_full_image(path)
            manifest["target"]["platformio_env"] = "esp32s3_n16r8_native_usb"
            manifest["target"]["dc_pwm_unlocked"] = True
            (path.parent / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "standard"):
                verify_full_image(path)

    def test_reject_renamed_standalone_bin_and_wrong_trusted_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, _ = self.make_image(Path(tmp))
            renamed = path.rename(path.parent / "firmware.bin")
            with self.assertRaisesRegex(ValueError, "named"):
                verify_full_image(renamed)
            renamed.rename(path)
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                verify_full_image(path, expected_sha256="0" * 64)


if __name__ == "__main__":
    unittest.main()
