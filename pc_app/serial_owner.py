"""Local loopback serial bridge: the headless agent owns COM; GUI is a TCP client.

No second process opens the serial device while the agent is running.
Traffic is raw bytes (ASCII control + binary RGB); handshake is one text line.
Never bind externally. The server drops the GUI peer on disconnect and the
agent resumes normal background telemetry automatically.
"""
from __future__ import annotations

import select
import socket

HOST = "127.0.0.1"
PORT = 42386
HANDSHAKE_PREFIX = "FANARGB-1 "


class SerialProxyClient:
    is_proxy = True

    def __init__(self, port_name: str, *, port: int = PORT) -> None:
        sock = socket.create_connection((HOST, port), timeout=0.5)
        try:
            sock.settimeout(0.5)
            sock.sendall((HANDSHAKE_PREFIX + port_name + "\n").encode("ascii"))
            answer = b""
            while b"\n" not in answer and len(answer) < 128:
                block = sock.recv(128 - len(answer))
                if not block:
                    raise ConnectionError("Agent closed the control channel")
                answer += block
            if answer != b"OK\n":
                raise ConnectionError("Background agent does not own this COM port")
            sock.setblocking(False)
        except Exception:
            sock.close()
            raise
        self.sock = sock

    @property
    def in_waiting(self) -> int:
        if self.sock.fileno() < 0:
            raise OSError("Disconnected from background agent")
        readable, _, _ = select.select([self.sock], [], [], 0)
        return 4096 if readable else 0

    def read(self, size: int = 1) -> bytes:
        if size <= 0:
            return b""
        try:
            data = self.sock.recv(size)
        except BlockingIOError:
            return b""
        if not data:
            raise OSError("Background agent disconnected")
        return data

    def write(self, payload: bytes) -> int:
        if not payload:
            return 0
        # A short timeout prevents UI deadlocks if the agent is wedged.
        self.sock.settimeout(0.2)
        try:
            self.sock.sendall(payload)
        finally:
            self.sock.setblocking(False)
        return len(payload)

    def close(self) -> None:
        self.sock.close()


class SerialOwnerServer:
    """Runs in the agent's already-existing polling loop, without threads."""

    def __init__(self, serial_port: str, *, port: int = PORT) -> None:
        self.serial_port = serial_port
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((HOST, port))
        listener.listen(1)
        listener.setblocking(False)
        self.listener = listener
        self.client: socket.socket | None = None

    @property
    def has_client(self) -> bool:
        return self.client is not None

    def _drop(self) -> None:
        if self.client is not None:
            self.client.close()
        self.client = None

    def poll(self, serial) -> None:
        if self.client is None:
            try:
                c, _ = self.listener.accept()
            except BlockingIOError:
                return
            # The handshake is bounded (one small line / 0.2 s).
            c.settimeout(0.2)
            try:
                header = b""
                while b"\n" not in header and len(header) <= 128:
                    header += c.recv(128 - len(header))
                expected = (HANDSHAKE_PREFIX + self.serial_port + "\n").encode("ascii")
                if header != expected or serial is None:
                    c.sendall(b"ERR\n")
                    c.close()
                    return
                c.sendall(b"OK\n")
                c.setblocking(False)
                self.client = c
            except (OSError, ValueError):
                c.close()
            return
        if serial is None:
            self._drop()
            return
        try:
            data = self.client.recv(4096)
            if data:
                serial.write(data)
            else:
                self._drop()
        except BlockingIOError:
            return
        except OSError:
            self._drop()

    def forward(self, data: bytes) -> None:
        if self.client is None or not data:
            return
        try:
            # Keep serial loop responsive, including under GUI back-pressure.
            self.client.settimeout(0.02)
            self.client.sendall(data)
            self.client.setblocking(False)
        except OSError:
            self._drop()

    def close(self) -> None:
        self._drop()
        self.listener.close()
