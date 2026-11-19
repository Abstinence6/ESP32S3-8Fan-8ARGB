"""Deterministic, inspectable SHA-256 manifests for CI-built release artifacts.

The manifest binds images and binaries to the exact source revision. It is
not a code-signing mechanism, and does not establish hardware compatibility
without checking the target board and partition map.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


FLASH_OFFSETS = {
    "bootloader.bin": "0x0",
    "partitions.bin": "0x8000",
    "boot_app0.bin": "0xe000",
    "firmware.bin": "0x10000",
}


def _digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def generate_manifest(
    directory: str | Path, *, component: str, commit: str, filenames: list[str],
    environment: str = "esp32s3",
) -> dict:
    """Create manifest.json and SHA256SUMS from named files in directory."""
    if component not in ("firmware", "windows"):
        raise ValueError("Unknown artifact component")
    if not re.fullmatch(r"[a-fA-F0-9]{40}", commit):
        raise ValueError("Commit must be a full 40-digit Git SHA")
    if not filenames or len(filenames) != len(set(filenames)):
        raise ValueError("Empty or duplicate artifacts")
    root = Path(directory)
    records = {}
    for name in sorted(filenames):
        if name in (".", "..") or "/" in name or "\\" in name or Path(name).name != name:
            raise ValueError(f"Unsafe artifact filename: {name!r}")
        path = root / name
        if not path.is_file():
            raise FileNotFoundError(f"Missing release artifact: {name}")
        records[name] = {"sha256": _digest(path), "bytes": path.stat().st_size}

    manifest = {
        "schema": 1,
        "component": component,
        "source_commit": commit.lower(),
        "files": records,
    }
    if component == "firmware":
        if environment not in ("esp32s3", "esp32s3_native_usb",
                               "esp32s3_n16r8_usb_diag",
                               "esp32s3_n16r8_native_usb",
                               "esp32s3_n16r8_native_usb_dc_validated",
                               "esp32s3_n16r8_native_usb_fan2_rerouted",
                               "esp32s3_n16r8_native_usb_fan2_rerouted_dc_validated"):
            raise ValueError("Unknown firmware environment")
        merged_images = {
            "esp32s3_n16r8_native_usb": "ESP32S3-N16R8-NativeUSB-FULL.bin",
            "esp32s3_n16r8_native_usb_dc_validated":
                "ESP32S3-N16R8-NativeUSB-DC-VALIDATED-FULL.bin",
            "esp32s3_n16r8_native_usb_fan2_rerouted":
                "ESP32S3-N16R8-FAN2-REROUTED-SAFE-FULL.bin",
            "esp32s3_n16r8_native_usb_fan2_rerouted_dc_validated":
                "ESP32S3-N16R8-FAN2-REROUTED-DC-FULL.bin",
        }
        required = set(FLASH_OFFSETS)
        if environment in merged_images:
            required.add(merged_images[environment])
        if set(records) != required:
            raise ValueError("Firmware package requires exactly 4 expected images"
                             " (5 including merged BIN for operating N16R8)")
        manifest["target"] = {
            "board": "esp32-s3-devkitc-1",
            "platformio_env": environment,
            "flash_offsets": FLASH_OFFSETS,
            "hardware_validation": "required before powering peripherals",
        }
        if environment in ("esp32s3_n16r8_usb_diag",
                           "esp32s3_n16r8_native_usb",
                           "esp32s3_n16r8_native_usb_dc_validated",
                           "esp32s3_n16r8_native_usb_fan2_rerouted",
                           "esp32s3_n16r8_native_usb_fan2_rerouted_dc_validated"):
            manifest["target"].update({
                "module": "ESP32-S3-WROOM-1-N16R8",
                "flash_size": "16MB",
                "psram": "8MB octal (OPI)",
                "diagnostic_only": environment == "esp32s3_n16r8_usb_diag",
                "fan_argb_gpio_outputs_disabled": environment == "esp32s3_n16r8_usb_diag",
            })
        if environment in merged_images:
            manifest["target"].update({
                "disabled_channels": [2],
                "channel_mask": 253,
                "merged_image": merged_images[environment],
                "merged_flash_offset": "0x0",
                "nvs_reset_when_merged_flashing": True,
                "hardware_validation": "required before powering any fans or LEDs",
            })
        if environment in ("esp32s3_n16r8_native_usb_fan2_rerouted",
                           "esp32s3_n16r8_native_usb_fan2_rerouted_dc_validated"):
            manifest["target"].update({
                "disabled_channels": [],
                "channel_mask": 255,
                "fan2_gpio_reroute": {"pwm": 8, "tach": 11, "argb": 17},
                "physical_reroute_required": True,
                "hardware_validation": "physical wiring must be confirmed; "
                                       "software build does not verify hardware",
            })
        if environment in ("esp32s3_n16r8_native_usb_dc_validated",
                           "esp32s3_n16r8_native_usb_fan2_rerouted_dc_validated"):
            manifest["target"].update({
                "dc_pwm_unlocked": True,
                "hardware_validation": "not performed; compile-time DC unlock only; "
                                       "required before powering any fans or LEDs",
            })
    elif set(records) != {"FanARGBControl.exe"}:
        raise ValueError("Windows package requires FanARGBControl.exe")

    root.mkdir(parents=True, exist_ok=True)
    (root / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (root / "SHA256SUMS").write_text(
        "".join(f"{entry['sha256']}  {name}\n" for name, entry in records.items()),
        encoding="ascii",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--component", required=True, choices=("firmware", "windows"))
    parser.add_argument("--directory", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--file", action="append", required=True, dest="files")
    parser.add_argument("--environment", default="esp32s3")
    args = parser.parse_args()
    result = generate_manifest(
        args.directory, component=args.component, commit=args.commit,
        filenames=args.files, environment=args.environment,
    )
    print(f"Validated {len(result['files'])} {args.component} release artifacts.")


if __name__ == "__main__":
    main()
