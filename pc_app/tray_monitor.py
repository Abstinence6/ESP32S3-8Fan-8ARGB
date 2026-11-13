"""One-shot, rate-limited PC fan alerts for Windows tray notifications."""
from __future__ import annotations


class FaultNotificationGate:
    def __init__(self, cooldown: float = 60.0):
        self.cooldown = cooldown
        self._states: dict[int, str] = {}
        self._last_alert: dict[tuple[int, str], float] = {}

    def observe(self, channel: int, *, fault: bool, fresh: bool, now: float) -> str | None:
        if not 1 <= channel <= 8:
            return None
        state = "fault" if fault else "stale" if not fresh else "ok"
        previous = self._states.get(channel)
        self._states[channel] = state
        if state == "ok" or state == previous:
            return None
        key = (channel, state)
        if now - self._last_alert.get(key, float("-inf")) < self.cooldown:
            return None
        self._last_alert[key] = now
        if state == "fault":
            return f"Fan {channel}: аварія вентилятора. Перевір TACH і живлення."
        return f"Fan {channel}: немає свіжої температури — захисний режим."

    def reset(self) -> None:
        self._states.clear()
