"""Local GUI ↔ headless-agent bridge: exactly one process owns ESP COM.

Protocol: 127.0.0.1 TCP handshake FANARGB-IPC1, then binary frames:
  W + uint16-BE length + bytes: GUI -> USB owner
  R + uint16-BE length + bytes: USB owner -> GUI
The agent must already have a physical serial port before it accepts a client.
No LAN-facing listener; no proprietary OS service or third-party dependency.
"""
from __future__ import annotations

import socket
import struct

HOST = "127.0.0.1"
PORT = 27831
READY = b"FANARGB-IPC1\n"
MAX_FRAME = 8192


def _frame(kind: bytes, data: bytes) -> bytes:
    if kind not in (b"W", b"R") or len(data) > MAX_FRAME:
        raise ValueError("invalid IPC frame")
    return kind + struct.pack(">H", len(data)) + data


class AgentSerialProxy:
    """pyserial-like GUI transport. Never touches or resets the physical COM port."""

    is_agent_proxy = True

    def __init__(self, connection: socket.socket) -> None:
        self._connection = connection
        self._received = bytearray()
        self._partial = bytearray()
        self._closed = False

    @classmethod
    def connect(cls, timeout: float = 0.7) -> AgentSerialProxy:
        connection = socket.create_connection((HOST, PORT), timeout=timeout)
        try:
            connection.settimeout(timeout)
            handshake = bytearray()
            while not handshake.endswith(b"\n") and len(handshake) < 64:
                chunk = connection.recv(64)
                if not chunk:
                    raise ConnectionError("agent refused connection: no serial device")
                handshake.extend(chunk)
            before, sep, remaining = bytes(handshake).partition(b"\n")
            if before + sep != READY:
                raise ConnectionError("incompatible or offline background agent")
            connection.setblocking(False)
            proxy = cls(connection)
            proxy._partial.extend(remaining)
            return proxy
        except Exception:
            connection.close()
            raise

    def _pump(self) -> None:
        if self._closed:
            return
        try:
            for _ in range(8):
                chunk = self._connection.recv(8192)
                if not chunk:
                    raise ConnectionError("background agent disconnected")
                self._partial.extend(chunk)
                while len(self._partial) >= 3:
                    kind, size = bytes(self._partial[:1]), struct.unpack(">H", self._partial[1:3])[0]
                    if kind != b"R" or size > MAX_FRAME:
                        raise ValueError("invalid agent frame")
                    if len(self._partial) < 3 + size:
                        break
                    self._received.extend(self._partial[3:3 + size])
                    del self._partial[:3 + size]
        except (BlockingIOError, InterruptedError):
            pass

    @property
    def in_waiting(self) -> int:
        self._pump()
        return len(self._received)

    def read(self, count: int) -> bytes:
        self._pump()
        size = min(max(0, count), len(self._received))
        result = bytes(self._received[:size])
        del self._received[:size]
        return result

    def write(self, data: bytes) -> int:
        if self._closed:
            raise ConnectionError("agent bridge closed")
        payload = bytes(data)
        self._connection.settimeout(0.25)
        try:
            # 510-pixel ARGB frames fit under MAX_FRAME; leave other writes intact.
            self._connection.sendall(_frame(b"W", payload))
        finally:
            self._connection.setblocking(False)
        return len(payload)

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._connection.close()


class AgentSerialBridge:
    """Listener and USB-owner adapter. Call poll() inside headless agent loop."""

    def __init__(self, host: str = HOST, port: int = PORT) -> None:
        self._host = host
        self._port = port
        self._server: socket.socket | None = None
        self._client: socket.socket | None = None
        self._partial = bytearray()

    def start(self) -> None:
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # Failure to bind means an owner already exists: never launch a second.
        self._server.bind((self._host, self._port))
        self._server.listen(1)
        self._server.setblocking(False)

    def _drop(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
        self._partial.clear()

    def poll(self, physical_port) -> None:
        if self._server is None:
            return
        if self._client is None:
            try:
                client, _addr = self._server.accept()
                if physical_port is None:
                    client.close()
                else:
                    client.settimeout(0.1)
                    client.sendall(READY)
                    client.setblocking(False)
                    self._client = client
            except (BlockingIOError, InterruptedError):
                pass
            return
        if physical_port is None:
            self._drop()
            return
        try:
            for _ in range(8):
                chunk = self._client.recv(8192)
                if not chunk:
                    raise ConnectionError("GUI disconnected")
                self._partial.extend(chunk)
                while len(self._partial) >= 3:
                    kind, size = bytes(self._partial[:1]), struct.unpack(">H", self._partial[1:3])[0]
                    if kind != b"W" or size > MAX_FRAME:
                        raise ValueError("invalid GUI command frame")
                    if len(self._partial) < 3 + size:
                        break
                    payload = bytes(self._partial[3:3 + size])
                    del self._partial[:3 + size]
                    if physical_port.write(payload) != len(payload):
                        raise OSError("short physical USB write")
        except (BlockingIOError, InterruptedError):
            pass
        except (OSError, ConnectionError, ValueError):
            self._drop()

    def forward_rx(self, incoming: bytes) -> None:
        if self._client is None or not incoming:
            return
        try:
            self._client.settimeout(0.05)
            self._client.sendall(_frame(b"R", incoming))
            self._client.setblocking(False)
        except (OSError, ValueError):
            self._drop()

    def close(self) -> None:
        self._drop()
        if self._server is not None:
            self._server.close()
            self._server = None
