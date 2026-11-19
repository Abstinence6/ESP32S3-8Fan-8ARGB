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

    def test_operating_n16r8_manifest_identifies_merged_image_and_disabled_channel(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            names=list(FLASH_OFFSETS)+["ESP32S3-N16R8-NativeUSB-FULL.bin"]
            for name in names:
                (root/name).write_bytes(("img "+name).encode())
            manifest=generate_manifest(
                root,component="firmware",commit="a"*40,filenames=names,
                environment="esp32s3_n16r8_native_usb")
            target=manifest["target"]
            self.assertFalse(target["diagnostic_only"])
            self.assertEqual(target["disabled_channels"],[2])
            self.assertTrue(target["nvs_reset_when_merged_flashing"])
            self.assertEqual(target["merged_flash_offset"],"0x0")
            (root/names[-1]).unlink()
            with self.assertRaises(FileNotFoundError):
                generate_manifest(root,component="firmware",commit="a"*40,
                                  filenames=names,environment="esp32s3_n16r8_native_usb")

    def test_dc_unlocked_n16r8_manifest_identifies_opt_in_without_hardware_validation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            merged = "ESP32S3-N16R8-NativeUSB-DC-VALIDATED-FULL.bin"
            names = list(FLASH_OFFSETS) + [merged]
            for name in names:
                (root / name).write_bytes(("dc image " + name).encode())
            manifest = generate_manifest(
                root, component="firmware", commit="a" * 40, filenames=names,
                environment="esp32s3_n16r8_native_usb_dc_validated",
            )
            self.assertEqual(manifest["target"], {
                "board": "esp32-s3-devkitc-1",
                "platformio_env": "esp32s3_n16r8_native_usb_dc_validated",
                "flash_offsets": FLASH_OFFSETS,
                "hardware_validation": "not performed; compile-time DC unlock only; "
                                       "required before powering any fans or LEDs",
                "module": "ESP32-S3-WROOM-1-N16R8",
                "flash_size": "16MB",
                "psram": "8MB octal (OPI)",
                "diagnostic_only": False,
                "fan_argb_gpio_outputs_disabled": False,
                "disabled_channels": [2],
                "channel_mask": 253,
                "merged_image": merged,
                "merged_flash_offset": "0x0",
                "nvs_reset_when_merged_flashing": True,
                "dc_pwm_unlocked": True,
            })
            self.assertEqual(set(manifest["files"]), set(names))
            for name in names:
                data = ("dc image " + name).encode()
                self.assertEqual(manifest["files"][name], {
                    "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
                })
            self.assertEqual(json.loads((root / "manifest.json").read_text()), manifest)
            self.assertEqual((root / "SHA256SUMS").read_text(), "".join(
                f"{hashlib.sha256(('dc image ' + name).encode()).hexdigest()}  {name}\n"
                for name in sorted(names)
            ))

    def test_n16r8_packages_reject_missing_extra_or_cross_environment_images(self):
        operating = "ESP32S3-N16R8-NativeUSB-FULL.bin"
        dc_unlocked = "ESP32S3-N16R8-NativeUSB-DC-VALIDATED-FULL.bin"
        base = list(FLASH_OFFSETS)
        cases = (
            ("esp32s3_n16r8_native_usb_dc_validated", base),
            ("esp32s3_n16r8_native_usb_dc_validated", base + [operating]),
            ("esp32s3_n16r8_native_usb_dc_validated", base + [operating, dc_unlocked]),
            ("esp32s3_n16r8_native_usb_dc_validated", base[:-1] + [dc_unlocked]),
            ("esp32s3_n16r8_native_usb", base + [dc_unlocked]),
            ("esp32s3", base + [dc_unlocked]),
        )
        for environment, names in cases:
            with self.subTest(environment=environment, names=names):
                with tempfile.TemporaryDirectory() as temp:
                    root = Path(temp)
                    for name in names:
                        (root / name).write_bytes(b"image")
                    with self.assertRaisesRegex(ValueError, "exactly 4"):
                        generate_manifest(
                            root, component="firmware", commit="a" * 40,
                            filenames=names, environment=environment,
                        )
                    self.assertFalse((root / "manifest.json").exists())
                    self.assertFalse((root / "SHA256SUMS").exists())

    def test_existing_environment_targets_remain_unchanged(self):
        basic = {
            "board": "esp32-s3-devkitc-1",
            "flash_offsets": FLASH_OFFSETS,
            "hardware_validation": "required before powering peripherals",
        }
        n16r8 = {
            "module": "ESP32-S3-WROOM-1-N16R8",
            "flash_size": "16MB",
            "psram": "8MB octal (OPI)",
        }
        targets = {
            "esp32s3": basic,
            "esp32s3_native_usb": basic,
            "esp32s3_n16r8_usb_diag": {
                **basic, **n16r8, "diagnostic_only": True,
                "fan_argb_gpio_outputs_disabled": True,
            },
            "esp32s3_n16r8_native_usb": {
                **basic, **n16r8, "diagnostic_only": False,
                "fan_argb_gpio_outputs_disabled": False,
                "disabled_channels": [2], "channel_mask": 253,
                "merged_image": "ESP32S3-N16R8-NativeUSB-FULL.bin",
                "merged_flash_offset": "0x0",
                "nvs_reset_when_merged_flashing": True,
                "hardware_validation": "required before powering any fans or LEDs",
            },
        }
        for environment, target in targets.items():
            with self.subTest(environment=environment):
                with tempfile.TemporaryDirectory() as temp:
                    root = Path(temp)
                    names = list(FLASH_OFFSETS)
                    if "merged_image" in target:
                        names.append(target["merged_image"])
                    for name in names:
                        (root / name).write_bytes(b"unchanged image")
                    manifest = generate_manifest(
                        root, component="firmware", commit="a" * 40,
                        filenames=names, environment=environment,
                    )
                    self.assertEqual(manifest["target"], {
                        **target, "platformio_env": environment,
                    })

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
