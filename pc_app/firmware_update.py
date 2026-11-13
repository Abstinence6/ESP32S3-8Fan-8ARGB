"""Guarded ESP32-S3 firmware-only update helper.

Never downloads or flashes an arbitrary image automatically. The user chooses
a local .bin, verifies target board/partition layout, and confirms that the
PC fans will remain electrically ON while ESP32 reboots.
"""
from __future__ import annotations

import hashlib
from pathlib import Path


def inspect_firmware(path: str) -> tuple[str, int]:
    file = Path(path)
    if file.suffix.lower() != ".bin" or not file.is_file():
        raise ValueError("Вибери файл firmware.bin")
    size = file.stat().st_size
    if not 1024 <= size <= 4 * 1024 * 1024:
        raise ValueError("Некоректний розмір прошивки")
    with file.open("rb") as inp:
        header = inp.read(8)
    if len(header) < 8 or header[0] != 0xE9 or not (1 <= header[1] <= 16):
        raise ValueError("Файл не схожий на ESP32 firmware image")
    sha = hashlib.sha256(file.read_bytes()).hexdigest()
    return sha, size


def flash_command(port: str, path: str) -> list[str]:
    if not port or not port.upper().startswith("COM") and not port.startswith("/dev/"):
        raise ValueError("Необхідно вибрати Serial порт ESP32-S3")
    inspect_firmware(path)
    return [
        "--chip", "esp32s3", "--port", port, "--baud", "460800",
        "write_flash", "0x10000", str(Path(path).resolve()),
    ]


def flash_firmware(port: str, path: str) -> None:
    import esptool  # bundled dependency in Windows EXE
    args = flash_command(port, path)
    esptool.main(args)
