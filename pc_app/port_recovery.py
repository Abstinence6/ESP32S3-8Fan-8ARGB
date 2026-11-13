"""Conservative USB identity matching for automatic ESP32 reconnection.

Matches a known USB serial number when present. Without a USB serial
number, only the *same port path* and same VID/PID may reconnect; no
guessing among multiple serial devices or bootloader/unknown ports.
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class PortIdentity:
    device: str
    vid: int | None = None
    pid: int | None = None
    serial_number: str | None = None

    @classmethod
    def from_port(cls, port):
        return cls(
            str(port.device), getattr(port, "vid", None),
            getattr(port, "pid", None),
            getattr(port, "serial_number", None) or None,
        )


class PortRecovery:
    def __init__(self):
        self.identity: PortIdentity | None = None

    def remember(self, ports, device: str) -> bool:
        matches = [PortIdentity.from_port(p) for p in ports if p.device == device]
        if len(matches) != 1:
            return False
        self.identity = matches[0]
        return True

    def find(self, ports) -> str | None:
        original = self.identity
        if original is None:
            return None
        seen = [PortIdentity.from_port(p) for p in ports]
        if original.serial_number and original.vid is not None and original.pid is not None:
            found = [
                p for p in seen if p.serial_number == original.serial_number and
                p.vid == original.vid and p.pid == original.pid
            ]
        else:
            found = [
                p for p in seen if p.device == original.device and
                p.vid == original.vid and p.pid == original.pid
            ]
        return found[0].device if len(found) == 1 else None
