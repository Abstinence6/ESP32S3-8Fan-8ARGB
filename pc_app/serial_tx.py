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
    def __init__(self, port, rgb_interval: float = 0.0, rgb_byte_rate: int = 60000):
        # Reserve ~35% of the 921600-baud UART for cooling and status traffic.
        if rgb_interval < 0 or rgb_byte_rate <= 0:
            raise ValueError("Invalid RGB scheduling limits")
        self.port = port
        self.rgb_interval = rgb_interval
        self.rgb_byte_rate = rgb_byte_rate
        self._rgb_burst = 4 * 517  # Up to four 170-pixel RGB packets.
        self._rgb_tokens = float(self._rgb_burst)
        self._rgb_budget_at: float | None = None
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
                # Preserve insertion order: replacing a pending frame must not
                # starve other zones under sustained 8-channel streaming.
            self.pending_rgb[channel] = packet

    def flush_rgb(self, now: float | None = None, *, max_frames: int = 1) -> int:
        """Bound RGB throughput and batch strips without blocking control traffic."""
        if not 1 <= max_frames <= 8:
            raise ValueError("Invalid RGB batch size")
        if now is None:
            now = time.monotonic()
        with self._lock:
            if self._rgb_budget_at is not None:
                elapsed = max(0.0, now - self._rgb_budget_at)
                self._rgb_tokens = min(float(self._rgb_burst),
                                       self._rgb_tokens + elapsed * self.rgb_byte_rate)
            self._rgb_budget_at = now
            if now < self.next_rgb_at or not self.pending_rgb:
                return 0
            sent_total = 0
            for _ in range(max_frames):
                if not self.pending_rgb:
                    break
                channel = next(iter(self.pending_rgb))
                packet = self.pending_rgb[channel]
                if len(packet) > self._rgb_tokens:
                    break
                # On partial write, caller disconnects and discards the queue.
                size = self._write(packet)
                del self.pending_rgb[channel]
                self._rgb_tokens -= size
                self.frames_sent += 1
                sent_total += size
                if self.rgb_interval:
                    break
            if sent_total:
                self.next_rgb_at = now + self.rgb_interval
            return sent_total

    def clear(self) -> None:
        with self._lock:
            self.pending_rgb.clear()
