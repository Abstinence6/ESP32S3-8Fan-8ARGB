"""Read-only preflight for the standard ESP32-S3 N16R8 native-USB FULL.bin.

This does not access USB or flash a board. It refuses standalone firmware.bin,
wrong offsets, and the opt-in DC-unlocked candidate when using its CI manifest.
For a previously verified standalone file, pass its known SHA-256 explicitly.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

IMAGE_NAME = "ESP32S3-N16R8-NativeUSB-FULL.bin"
ENVIRONMENT = "esp32s3_n16r8_native_usb"
FLASH_SIZE = 16 * 1024 * 1024
APP_OFFSET = 0x10000
NVS_GAP_START = 0x9000
NVS_GAP_END = 0xE000


def _check_sha256(value: str) -> str:
    if not re.fullmatch(r"[0-9a-fA-F]{64}", value):
        raise ValueError("Expected SHA-256 must have 64 hexadecimal digits")
    return value.lower()


def verify_full_image(
    image_path: str | Path,
    *,
    manifest_path: str | Path | None = None,
    expected_sha256: str | None = None,
) -> dict:
    """Validate image placement, release identity and a trusted expected hash.

    A matching, unsigned manifest checks build consistency but is not proof of
    hardware suitability, authenticity or safe electrical power-up.
    """
    path = Path(image_path)
    if path.name != IMAGE_NAME or not path.is_file():
        raise ValueError(f"Expected the standard merged N16R8 image named {IMAGE_NAME}")
    data = path.read_bytes()
    if not APP_OFFSET + 1024 <= len(data) <= FLASH_SIZE:
        raise ValueError("Invalid merged image size for 16 MB flash")

    # Validate the *locations*, not just the ESP image magic at offset 0.
    # Standalone app images also start with 0xE9 and must never go to 0x0.
    for label, offset in (("bootloader", 0), ("application", APP_OFFSET)):
        if data[offset] != 0xE9 or not 1 <= data[offset + 1] <= 16:
            raise ValueError(f"Missing ESP image header at {label} offset 0x{offset:x}")
        if int.from_bytes(data[offset + 12:offset + 14], "little") != 9:
            raise ValueError(f"{label} image is not for ESP32-S3")
    if data[0x8000:0x8002] != b"\xAA\x50":
        raise ValueError("Missing partition table at 0x8000")
    if data[0xE000:0xE100] == b"\xFF" * 0x100:
        raise ValueError("Missing boot_app0 data at 0xE000")
    if data[NVS_GAP_START:NVS_GAP_END] != b"\xFF" * (NVS_GAP_END - NVS_GAP_START):
        raise ValueError("Unexpected bytes in the merged NVS gap (0x9000..0xDFFF)")

    digest = hashlib.sha256(data).hexdigest()
    source = ""
    if manifest_path is None:
        sibling = path.parent / "manifest.json"
        if sibling.is_file():
            manifest_path = sibling
    if manifest_path is not None:
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("Invalid firmware release manifest")
        target = manifest.get("target", {})
        records = manifest.get("files", {})
        if not isinstance(target, dict) or not isinstance(records, dict):
            raise ValueError("Invalid firmware release manifest structure")
        if manifest.get("component") != "firmware" or not re.fullmatch(
            r"[0-9a-fA-F]{40}", str(manifest.get("source_commit", ""))
        ):
            raise ValueError("Invalid firmware release manifest")
        if (
            target.get("platformio_env") != ENVIRONMENT
            or target.get("module") != "ESP32-S3-WROOM-1-N16R8"
            or target.get("flash_size") != "16MB"
            or target.get("merged_image") != IMAGE_NAME
            or target.get("merged_flash_offset") != "0x0"
            or target.get("channel_mask") != 255
            or target.get("disabled_channels") != []
            or target.get("fan2_gpio_reroute") != {"pwm": 8, "tach": 11, "argb": 17}
            or target.get("physical_reroute_required") is not True
            or target.get("diagnostic_only") is not False
            or target.get("dc_pwm_unlocked") is True
            or target.get("nvs_reset_when_merged_flashing") is not True
        ):
            raise ValueError("Manifest target is not the standard N16R8 native-USB build")
        record = records.get(IMAGE_NAME, {})
        if not isinstance(record, dict):
            raise ValueError("Invalid merged image manifest record")
        if record.get("bytes") != len(data) or _check_sha256(str(record.get("sha256", ""))) != digest:
            raise ValueError("Merged BIN does not match the release manifest")
        source = str(manifest["source_commit"])
    if expected_sha256 is not None and _check_sha256(expected_sha256) != digest:
        raise ValueError("Merged BIN SHA-256 differs from the expected trusted value")
    if manifest_path is None and expected_sha256 is None:
        raise ValueError("Provide the CI manifest.json or a trusted --expected-sha256")

    return {
        "image": str(path),
        "sha256": digest,
        "bytes": len(data),
        "source_commit": source or None,
        "flash_offset": "0x0",
        "nvs_will_be_overwritten": True,
        "hardware_verified": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="Standard N16R8 FULL.bin, NOT firmware.bin")
    parser.add_argument("--manifest", help="manifest.json from the same firmware CI artifact")
    parser.add_argument("--expected-sha256", help="SHA-256 independently obtained from a trusted build")
    args = parser.parse_args()
    try:
        report = verify_full_image(
            args.image, manifest_path=args.manifest, expected_sha256=args.expected_sha256
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(2, f"PREFLIGHT FAILED: {exc}\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("VERIFIED FILE FORMAT ONLY. This does NOT flash or test the board.")
    print("Full merged BIN: 0x0 only. Standalone firmware.bin: 0x10000 only.")
    print("WARNING: full image at 0x0 overwrites NVS, including stored settings.")
    print("Damaged board: check 5V/3.3V shorts and supply rails BEFORE USB connection.")


if __name__ == "__main__":
    main()
