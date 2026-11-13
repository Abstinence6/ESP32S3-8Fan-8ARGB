"""Single physical writer for ASCII control and RGB frames.

ASCII/temperature commands take priority, whereas RGB frames are replaceable
by newer frames for the same zone. All writes are serialized behind one lock.
No operation fabricates an ESP acknowledgement; write success means only that
the OS accepted the bytes. Firmware still owns safety/thermal decisions.
"""
from __future__ import annotations

from collections import OrderedDict
import threading
import time


class SerialTransmitter:
    def __init__(self, port, rgb_interval: float = 0.04):
        if rgb_interval < 0:
            raise ValueError("Invalid RGB interval")
        self.port = port
        self.rgb_interval = rgb_interval
        self.pending_rgb: OrderedDict[int, bytes] = OrderedDict()
        self.next_rgb_at = 0.0
        self._lock = threading.RLock()
        self.frames_dropped = 0
        self.frames_sent = 0
        self.commands_sent = 0

    def _write(self, packet: bytes) -> int:
        size = self.port.write(packet)
        if size != len(packet):
            raise OSError(f"Serial partial write: {size}/{len(packet)}")
        return size

    def write(self, packet: bytes) -> int:
        """Control and proxy traffic: highest priority, never coalesced."""
        if not packet or not isinstance(packet, bytes):
            raise ValueError("Serial control must be nonempty bytes")
        with self._lock:
            count = self._write(packet)
            self.commands_sent += 1
            return count

    def send_command(self, command: str) -> int:
        if not command or "\r" in command or "\n" in command or len(command) > 256:
            raise ValueError("Invalid Serial command")
        return self.write((command + "\n").encode("ascii"))

    def queue_rgb(self, channel: int, packet: bytes) -> None:
        """The most recent RGB frame replaces an unsent older frame per channel."""
        if not 1 <= channel <= 8:
            raise ValueError("RGB zone must be 1..8")
        if (len(packet) < 10 or not packet.startswith(b"\xA5\x5A") or
                packet[2] != channel):
            raise ValueError("Invalid RGB packet")
        with self._lock:
            if channel in self.pending_rgb:
                self.frames_dropped += 1
                del self.pending_rgb[channel]
            self.pending_rgb[channel] = packet

    def flush_rgb(self, now: float | None = None) -> int:
        """Transmit at most one frame per interval; avoid starving control."""
        if now is None:
            now = time.monotonic()
        with self._lock:
            if now < self.next_rgb_at or not self.pending_rgb:
                return 0
            channel = next(iter(self.pending_rgb))
            packet = self.pending_rgb[channel]
            # On a partial write/exception, caller must disconnect and drop
            # queued frames; replaying truncated binary can desynchronize RX.
            sent = self._write(packet)
            del self.pending_rgb[channel]
            self.next_rgb_at = now + self.rgb_interval
            self.frames_sent += 1
            return sent

    def clear(self) -> None:
        with self._lock:
            self.pending_rgb.clear()
