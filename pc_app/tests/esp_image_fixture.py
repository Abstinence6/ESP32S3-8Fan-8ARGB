"""Minimal internally consistent ESP32-S3 app image for unit tests."""
import hashlib
import struct


def make_test_image(chip_id: int = 9, content: bytes | None = None) -> bytes:
    payload = bytes(range(256)) * 9 if content is None else content
    header = bytearray(24)
    header[0] = 0xE9
    header[1] = 1
    header[2] = 2  # DIO
    header[3] = 0x30  # 8 MB, 40 MHz
    header[4:8] = struct.pack("<I", 0x40380000)
    header[8] = 0xEE
    header[12:14] = struct.pack("<H", chip_id)
    header[23] = 1  # embedded SHA256
    data = bytes(header) + struct.pack("<II", 0x3C000020, len(payload)) + payload
    data += bytes((-(len(data) + 1)) % 16)
    check = 0xEF
    for value in payload:
        check ^= value
    data += bytes([check])
    return data + hashlib.sha256(data).digest()
