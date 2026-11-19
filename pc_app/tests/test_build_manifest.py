import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts.build_manifest import FLASH_OFFSETS, generate_manifest


class ManifestTests(unittest.TestCase):
    def test_firmware_manifest_contains_exact_hashes_and_flash_offsets(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in FLASH_OFFSETS:
                (root / name).write_bytes(("image " + name).encode())
            manifest = generate_manifest(
                root, component="firmware", commit="a" * 40,
                filenames=list(FLASH_OFFSETS),
            )
            self.assertEqual(manifest["target"]["flash_offsets"], FLASH_OFFSETS)
            self.assertEqual(manifest["source_commit"], "a" * 40)
            for name in FLASH_OFFSETS:
                digest = hashlib.sha256(("image " + name).encode()).hexdigest()
                self.assertEqual(manifest["files"][name]["sha256"], digest)
            self.assertEqual(json.loads((root / "manifest.json").read_text()), manifest)
            self.assertEqual(len((root / "SHA256SUMS").read_text().splitlines()), 4)

    def test_native_usb_manifest_identifies_the_correct_build(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in FLASH_OFFSETS:
                (root / name).write_bytes(("native usb " + name).encode())
            manifest = generate_manifest(
                root, component="firmware", commit="b" * 40,
                filenames=list(FLASH_OFFSETS), environment="esp32s3_native_usb",
            )
            self.assertEqual(manifest["target"]["platformio_env"], "esp32s3_native_usb")
            with self.assertRaisesRegex(ValueError, "Unknown firmware environment"):
                generate_manifest(root, component="firmware", commit="b" * 40,
                                  filenames=list(FLASH_OFFSETS), environment="unsafe")

    def test_n16r8_diagnostic_manifest_disables_peripheral_outputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in FLASH_OFFSETS:
                (root / name).write_bytes(("n16r8 " + name).encode())
            manifest = generate_manifest(
                root, component="firmware", commit="a" * 40,
                filenames=list(FLASH_OFFSETS),
                environment="esp32s3_n16r8_usb_diag",
            )
            target = manifest["target"]
            self.assertEqual(target["flash_size"], "16MB")
            self.assertEqual(target["psram"], "8MB octal (OPI)")
            self.assertTrue(target["diagnostic_only"])
            self.assertTrue(target["fan_argb_gpio_outputs_disabled"])

    def test_manifest_rejects_unsafe_files_and_missing_firmware_images(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "firmware.bin").write_bytes(b"test")
            with self.assertRaisesRegex(ValueError, "exactly 4"):
                generate_manifest(root, component="firmware", commit="a" * 40,
                                  filenames=["firmware.bin"])
            with self.assertRaisesRegex(ValueError, "Unsafe"):
                generate_manifest(root, component="windows", commit="a" * 40,
                                  filenames=["../FanARGBControl.exe"])
            with self.assertRaises(ValueError):
                generate_manifest(root, component="firmware", commit="unknown",
                                  filenames=["firmware.bin"])

    def test_windows_manifest_checks_binary_integrity(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "FanARGBControl.exe").write_bytes(b"MZdummy")
            manifest = generate_manifest(
                root, component="windows", commit="0123456789abcdef" * 2 + "01234567",
                filenames=["FanARGBControl.exe"],
            )
            self.assertEqual(manifest["files"]["FanARGBControl.exe"]["bytes"], 7)
            self.assertNotIn("target", manifest)


if __name__ == "__main__":
    unittest.main()
