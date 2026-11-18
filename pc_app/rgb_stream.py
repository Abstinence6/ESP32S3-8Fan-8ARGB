"""Adaptive, loss-tolerant RGB scene pacing shared by GUI and headless agent.

Only the newest frame per zone is buffered. SerialTransmitter remains the sole
physical writer and reserves UART bandwidth for temperature/control traffic.
"""
from __future__ import annotations

import math
import time
from typing import Callable, Mapping, Sequence

try:
    from .sacn_bridge import encode_rgb_frame
except ImportError:
    from sacn_bridge import encode_rgb_frame


class AdaptiveRgbStream:
    def __init__(self, *, byte_rate: int = 60000, max_fps: float = 25.0,
                 keepalive_seconds: float = 2.0, active_window: float = 1.0):
        if (byte_rate <= 0 or not math.isfinite(max_fps) or max_fps <= 0 or
            not 0 < keepalive_seconds < 3.0 or active_window <= 0):
            raise ValueError('Invalid adaptive RGB rate or keepalive')
        self.byte_rate = byte_rate
        self.max_fps = max_fps
        self.keepalive_seconds = keepalive_seconds
        self.active_window = active_window
        self._pending: dict[int, bytes] = {}
        self._last_input: dict[int, bytes] = {}
        self._last_sent: dict[int, tuple[bytes, float]] = {}
        self._changed: dict[int, tuple[int, float]] = {}
        self._last_dispatch: float | None = None
        self.frames_queued = 0
        self.frames_coalesced = 0
        self.frames_unchanged = 0

    def reset(self) -> None:
        """Forget the previous controller/owner; never replay old RGB frames."""
        self._pending.clear()
        self._last_input.clear()
        self._last_sent.clear()
        self._changed.clear()
        self._last_dispatch = None

    def offer(self, frames: Mapping[int, bytes], led_counts: Sequence[int], *,
              now: float | None = None) -> int:
        """Coalesce input frames; remember which zones are actually changing."""
        if now is None:
            now = time.monotonic()
        received = 0
        for channel, frame in frames.items():
            if (type(channel) is not int or not 1 <= channel <= 8 or
                channel > len(led_counts) or not isinstance(frame, bytes) or
                len(frame) < 3 or len(frame) % 3):
                continue
            count = led_counts[channel - 1]
            if type(count) is not int or not 1 <= count <= 170:
                continue
            rgb = frame[:count * 3]
            if not rgb:
                continue
            if self._last_input.get(channel) != rgb:
                self._changed[channel] = (len(rgb) + 7, now)
            self._last_input[channel] = rgb
            if channel in self._pending:
                self.frames_coalesced += 1
            self._pending[channel] = rgb
            received += 1
        return received

    def target_fps(self, *, now: float | None = None) -> float:
        """Scene FPS cap determined by recently changing zones and their sizes."""
        if now is None:
            now = time.monotonic()
        active_bytes = sum(size for size, changed_at in self._changed.values()
                           if 0 <= now - changed_at <= self.active_window)
        return min(self.max_fps, self.byte_rate / active_bytes) if active_bytes else self.max_fps

    def dispatch(self, queue_rgb: Callable[[int, bytes], object], *,
                 now: float | None = None) -> int:
        """Queue a whole latest scene at a safe source FPS; TX enforces byte budget.

        Repeated static colors are suppressed but retransmitted within the ESP's
        three-second external-RGB timeout while fresh source frames arrive.
        """
        if now is None:
            now = time.monotonic()
        if not self._pending:
            return 0
        if (self._last_dispatch is not None and
                now - self._last_dispatch < 1.0 / self.target_fps(now=now)):
            return 0
        queued = 0
        for channel, rgb in sorted(self._pending.items()):
            previous = self._last_sent.get(channel)
            if previous is not None and previous[0] == rgb and now - previous[1] < self.keepalive_seconds:
                self.frames_unchanged += 1
                continue
            result = queue_rgb(channel, encode_rgb_frame(channel, rgb))
            if result is False:
                raise OSError('RGB queue failed')
            self._last_sent[channel] = (rgb, now)
            self.frames_queued += 1
            queued += 1
        self._pending.clear()
        if queued:
            self._last_dispatch = now
        return queued
