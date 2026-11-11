"""Local sACN (ANSI E1.31) RGB bridge for OpenRGB/xLights -> ESP32-S3.

OpenRGB is the sACN TRANSMITTER (E1.31 Devices); no receiver plugin is
needed. Eight universes map to eight physical RGB strips. The PC app owns
USB Serial for both thermal control and RGB streaming.
"""
from __future__ import annotations

import socket
from typing import Optional

SACN_PORT = 5568
SACN_UNIVERSES = 8
MAX_LEDS_PER_UNIVERSE = 170
SERIAL_BAUD = 921600
MAGIC = b"\xA5\x5A"


def crc16_ccitt(data: bytes) -> int:
    """CRC-16/CCITT-FALSE (poly=0x1021, init=0xFFFF, non-reflected)."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if (crc & 0x8000) else (crc << 1) & 0xFFFF
    return crc


def encode_rgb_frame(channel: int, rgb: bytes) -> bytes:
    """Wire: A5 5A | channel(1..8) | pixel-count(u16 LE) | RGB | CRC16 LE."""
    if not 1 <= channel <= SACN_UNIVERSES:
        raise ValueError("RGB output must be 1..8")
    if not isinstance(rgb, bytes) or not rgb or len(rgb) % 3 or len(rgb) > MAX_LEDS_PER_UNIVERSE * 3:
        raise ValueError("RGB must contain 1..170 complete 24-bit pixels")
    payload = bytes((channel,)) + (len(rgb) // 3).to_bytes(2, "little") + rgb
    return MAGIC + payload + crc16_ccitt(payload).to_bytes(2, "little")


def decode_sacn(packet: bytes) -> Optional[tuple[int, bytes]]:
    """Validate standard sACN data packet. Ignore preview / termination.

    DMX channel 1 starts at packet offset 126; channel 0 (offset 125) is
    the DMX start code and must be zero. Each RGB pixel consumes 3 slots.
    """
    if len(packet) < 129 or len(packet) > 638:
        return None
    if packet[:2] != b"\x00\x10" or packet[4:16] != b"ASC-E1.17\x00\x00\x00":
        return None
    if packet[18:22] != b"\x00\x00\x00\x04" or packet[40:44] != b"\x00\x00\x00\x02":
        return None
    if packet[117:119] != b"\x02\xA1" or packet[119:123] != b"\x00\x00\x00\x01":
        return None
    for pos in (16, 38, 115):
        flags_and_length = int.from_bytes(packet[pos:pos + 2], "big")
        if flags_and_length != (0x7000 | (len(packet) - pos)):
            return None
    # Option bit 7: preview; bit 6: stream terminated.
    if packet[112] & 0xC0:
        return None
    universe = int.from_bytes(packet[113:115], "big")
    if not 1 <= universe <= SACN_UNIVERSES:
        return None
    value_count = int.from_bytes(packet[123:125], "big")
    if not 4 <= value_count <= 513 or (125 + value_count) != len(packet):
        return None
    if packet[125] != 0:
        return None
    rgb = packet[126:]
    # Trim padding/non-RGB tail, if the sACN sender includes extra DMX slots.
    rgb = rgb[:(len(rgb) // 3) * 3]
    return (universe, rgb) if rgb else None


class E131Listener:
    """Non-blocking *local* UDP receiver; drains all packets and keeps newest frame per output."""

    def __init__(self, host: str = "127.0.0.1", port: int = SACN_PORT) -> None:
        self.host = host
        self.port = port
        self.sock: Optional[socket.socket] = None

    def start(self) -> None:
        if self.sock is not None:
            return
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.bind((self.host, self.port))
            sock.setblocking(False)
        except BaseException:
            sock.close()
            raise
        self.sock = sock

    def stop(self) -> None:
        if self.sock is not None:
            self.sock.close()
            self.sock = None

    def read_latest(self, max_datagrams: int = 256) -> dict[int, bytes]:
        results: dict[int, bytes] = {}
        if self.sock is None:
            return results
        for _ in range(max_datagrams):
            try:
                packet, _addr = self.sock.recvfrom(2048)
            except BlockingIOError:
                break
            data = decode_sacn(packet)
            if data is not None:
                channel, rgb = data
                results[channel] = rgb
        return results
