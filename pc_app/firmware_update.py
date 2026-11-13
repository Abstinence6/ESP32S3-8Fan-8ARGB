"""Guarded ESP32-S3 firmware-only update helper.

Never downloads or flashes an arbitrary image automatically. The user chooses
a local .bin, verifies target board/partition layout, and confirms that the
PC fans will remain electrically ON while ESP32 reboots.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path


def inspect_firmware(path: str) -> tuple[str, int]:
    """Validate the ESP32-S3 application image, segments, checksum and SHA.

    ESP image header: 8 bytes + 16-byte extended header. The target
    esp_chip_id_t is at offsets 12-13 and ESP32-S3 is 0x0009.
    Never accept a bare magic byte or an image built for another ESP32.
    """
    file = Path(path)
    if file.suffix.lower() != ".bin" or not file.is_file():
        raise ValueError("Вибери файл firmware.bin")
    data = file.read_bytes()
    size = len(data)
    if not 1024 <= size <= 4 * 1024 * 1024 or len(data) < 24:
        raise ValueError("Некоректний розмір прошивки")
    if data[0] != 0xE9 or not 1 <= data[1] <= 16:
        raise ValueError("Файл не є стандартним ESP firmware image")
    if int.from_bytes(data[12:14], "little") != 0x0009:
        raise ValueError("Образ призначений не для ESP32-S3 (chip_id != 9)")
    if data[23] not in (0, 1):
        raise ValueError("Некоректний прапорець SHA-256 в ESP image")
    cursor = 24
    check = 0xEF
    for _segment in range(data[1]):
        if cursor + 8 > size:
            raise ValueError("Заголовок сегмента виходить за межі BIN")
        address = int.from_bytes(data[cursor:cursor + 4], "little")
        length = int.from_bytes(data[cursor + 4:cursor + 8], "little")
        cursor += 8
        if not address or length == 0 or length > size - cursor:
            raise ValueError("Некоректна адреса чи розмір ESP image сегмента")
        for byte in data[cursor:cursor + length]:
            check ^= byte
        cursor += length
    checksum_at = ((cursor + 16) // 16) * 16 - 1
    if checksum_at >= size or data[checksum_at] != check:
        raise ValueError("Пошкоджено контрольну суму сегментів ESP32-S3")
    image_end = checksum_at + 1
    if data[23] == 1:
        if size != image_end + 32:
            raise ValueError("Некоректна довжина SHA-256 ESP image")
        if data[image_end:] != hashlib.sha256(data[:image_end]).digest():
            raise ValueError("SHA-256 усередині прошивки не збігається")
    elif size != image_end:
        raise ValueError("Неочікувані дані після ESP image")
    digest = hashlib.sha256(data).hexdigest()
    return digest, size

def flash_command(port: str, path: str) -> list[str]:
    if not (re.fullmatch(r"COM[1-9][0-9]*", port, flags=re.IGNORECASE) or port.startswith("/dev/")):
        raise ValueError("Необхідно вибрати Serial порт ESP32-S3")
    inspect_firmware(path)
    return [
        "--chip", "esp32s3", "--port", port, "--baud", "460800",
        "write_flash", "0x10000", str(Path(path).resolve()),
    ]


def flash_preflight(
    pc_state: str, *, isolated_bench: bool, is_proxy: bool,
) -> None:
    """Fail closed if PC is on; unknown/disabled state needs explicit bench check.

    Physical isolation can never be inferred from an unavailable status sensor.
    """
    if is_proxy:
        raise ValueError("Вимкни фоновий агент: він володіє USB COM-портом")
    if str(pc_state).lower() == "on":
        raise ValueError("ПК увімкнений: перепрошивання заборонено")
    if str(pc_state).lower() != "off" and not isolated_bench:
        raise ValueError(
            "Немає підтвердження, що ПК вимкнений. Потрібен незалежний "
            "стенд і явне підтвердження його ізоляції."
        )


def flash_firmware(port: str, path: str, expected_sha256: str | None = None) -> None:
    digest, _size = inspect_firmware(path)
    if expected_sha256 is not None and digest != expected_sha256:
        raise ValueError("Файл прошивки змінився після вибору — запис скасовано")
    import esptool  # bundled dependency in Windows EXE
    args = flash_command(port, path)
    esptool.main(args)
