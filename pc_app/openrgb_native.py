"""Opt-in localhost OpenRGB SDK v1 virtual RGB controller.

OpenRGB GUI can add a remote SDK server on 127.0.0.1:6743. This server
exposes one virtual LED-strip controller with eight fixed-size linear zones;
per-LED and per-zone updates become RGB frames for the existing Serial
transmitter. No internet access or E1.31 bridge is needed.

Strictly a local, opt-in effect bridge; cannot change fan speed, PC power or
firmware settings. Control/UI ownership prevents running this and E1.31
or ARGB Studio concurrently.
"""
from __future__ import annotations

from collections import OrderedDict
import socket
import struct
import threading

HOST = "127.0.0.1"
PORT = 6743
HEADER = struct.Struct("<4sIII")
MAGIC = b"ORGB"
MAX_BODY = 64 * 1024
MAX_LEDS = 8 * 170
VERSION = 1
REQUEST_COUNT = 0
REQUEST_DATA = 1
REQUEST_VERSION = 40
SET_CLIENT_NAME = 50
UPDATE_LEDS = 1050
UPDATE_ZONE = 1051
UPDATE_SINGLE = 1052
SET_CUSTOM_MODE = 1100


def _s(text: str) -> bytes:
    content = text.encode("utf-8") + b"\x00"
    return struct.pack("<H", len(content)) + content


def pack_packet(device: int, cmd: int, body: bytes) -> bytes:
    if len(body) > MAX_BODY:
        raise ValueError("OpenRGB packet too large")
    return HEADER.pack(MAGIC, device, cmd, len(body)) + body


def controller_description(counts: tuple[int, ...], protocol: int) -> bytes:
    """OpenRGB SDK Controller Description block for versions 0 and 1."""
    if protocol not in (0, 1) or len(counts) != 8 or any(not 1 <= n <= 170 for n in counts):
        raise ValueError("Invalid OpenRGB device layout")
    total = sum(counts)
    dev = struct.pack("<i", 4)  # DEVICE_TYPE_LEDSTRIP
    dev += _s("FanARGB ESP32-S3")
    if protocol >= 1:
        dev += _s("FanARGB")
    dev += _s("8 independent addressable LED strips")
    dev += _s("7")
    dev += _s("ESP32S3-8Fan-8ARGB")
    dev += _s("USB via FanARGBControl")
    dev += struct.pack("<Hi", 1, 0)  # num_modes, active_mode
    dev += _s("Direct")
    dev += struct.pack("<i", 0)  # mode value, SDK v0/v1
    dev += struct.pack("<7I", 1 << 5, 0, 0, 0, 0, 0, 0)
    # flags, speed_min, speed_max, colors_min/max, speed, direction
    dev += struct.pack("<I", 1)  # MODE_COLORS_PER_LED
    dev += struct.pack("<H", 0)  # mode_colors_count
    dev += struct.pack("<H", 8)  # zones
    for index, count in enumerate(counts, 1):
        dev += _s(f"ARGB Zone {index}")
        dev += struct.pack("<iIIIH", 1, count, count, count, 0)
        # type=ZONE_TYPE_LINEAR, min/max/count, zero matrix length
    dev += struct.pack("<H", total)
    for ch, count in enumerate(counts, 1):
        for led in range(1, count + 1):
            dev += _s(f"Zone {ch} LED {led}")
            dev += struct.pack("<I", 0)
    dev += struct.pack("<H", total)
    dev += bytes(total * 4)  # RGBColor = 4-byte R,G,B,0
    return struct.pack("<I", 4 + len(dev)) + dev


def _colors(raw: bytes) -> bytes:
    if len(raw) % 4:
        raise ValueError("Invalid RGBColor bytes")
    return bytes(b for pos in range(0, len(raw), 4) for b in raw[pos:pos + 3])


class OpenRGBNativeServer:
    def __init__(self, port: int = PORT):
        self.port = port
        self.host = HOST
        self.led_counts: tuple[int, ...] = ()
        self._listener: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._frames: OrderedDict[int, bytes] = OrderedDict()
        self._colors: list[bytearray] = []
        self.connections = 0

    def start(self, counts) -> None:
        counts = tuple(counts)
        if len(counts) != 8 or any(type(n) is not int or not 1 <= n <= 170 for n in counts):
            raise ValueError("Wait for eight valid ESP32 LEDCOUNTS")
        if self._listener is not None:
            return
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((self.host, self.port))
            sock.listen(1)
            sock.settimeout(0.25)
        except BaseException:
            sock.close()
            raise
        self.led_counts = counts
        self._colors = [bytearray(n * 3) for n in counts]
        self._stop.clear()
        self._listener = sock
        self._thread = threading.Thread(target=self._run, daemon=True, name="FanARGB-OpenRGB-SDK")
        self._thread.start()

    def _enqueue(self, zone: int, rgb: bytes) -> None:
        if not 0 <= zone < 8 or len(rgb) != self.led_counts[zone] * 3:
            return
        with self._lock:
            self._colors[zone][:] = rgb
            self._frames[zone + 1] = rgb

    def read_latest(self) -> dict[int, bytes]:
        with self._lock:
            frames = dict(self._frames)
            self._frames.clear()
        return frames

    def _handle(self, dev: int, cmd: int, payload: bytes) -> bytes | None:
        if cmd == REQUEST_VERSION and len(payload) == 4:
            return pack_packet(dev, cmd, struct.pack("<I", VERSION))
        if cmd == REQUEST_COUNT and not payload:
            return pack_packet(dev, cmd, struct.pack("<I", 1))
        if cmd == REQUEST_DATA and dev == 0 and len(payload) in (0, 4):
            protocol = 0 if len(payload) == 0 else min(VERSION, struct.unpack("<I", payload)[0])
            return pack_packet(dev, cmd, controller_description(self.led_counts, protocol))
        if cmd in (SET_CLIENT_NAME, SET_CUSTOM_MODE) or dev != 0:
            return None
        if cmd == UPDATE_ZONE and len(payload) >= 10:
            size, zone, count = struct.unpack_from("<IIH", payload)
            if (size != len(payload) or zone >= 8 or
                    count != self.led_counts[zone] or len(payload) != 10 + 4 * count):
                return None
            self._enqueue(zone, _colors(payload[10:]))
        elif cmd == UPDATE_LEDS and len(payload) >= 6:
            size, count = struct.unpack_from("<IH", payload)
            if size != len(payload) or count != sum(self.led_counts) or len(payload) != 6 + 4 * count:
                return None
            rgb = _colors(payload[6:])
            offset = 0
            for zone, num in enumerate(self.led_counts):
                self._enqueue(zone, rgb[offset:offset + num * 3])
                offset += num * 3
        elif cmd == UPDATE_SINGLE and len(payload) == 8:
            index, color = struct.unpack("<i4s", payload)
            if not 0 <= index < sum(self.led_counts):
                return None
            for zone, size in enumerate(self.led_counts):
                if index < size:
                    with self._lock:
                        row = self._colors[zone]
                        row[index * 3:index * 3 + 3] = color[:3]
                        self._frames[zone + 1] = bytes(row)
                    break
                index -= size
        return None

    def _run(self) -> None:
        sock = self._listener
        if sock is None:
            return
        while not self._stop.is_set():
            try:
                peer, _ = sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            self.connections += 1
            with peer:
                peer.settimeout(0.3)
                buffer = bytearray()
                while not self._stop.is_set():
                    try:
                        data = peer.recv(4096)
                        if not data:
                            break
                        buffer.extend(data)
                        while len(buffer) >= HEADER.size:
                            magic, dev, cmd, size = HEADER.unpack_from(buffer)
                            if magic != MAGIC or size > MAX_BODY:
                                return
                            if len(buffer) < HEADER.size + size:
                                break
                            payload = bytes(buffer[HEADER.size:HEADER.size + size])
                            del buffer[:HEADER.size + size]
                            answer = self._handle(dev, cmd, payload)
                            if answer:
                                peer.sendall(answer)
                    except socket.timeout:
                        continue
                    except (OSError, ValueError):
                        break

    def stop(self) -> None:
        self._stop.set()
        listener, self._listener = self._listener, None
        if listener:
            listener.close()
        if self._thread:
            self._thread.join(timeout=1)
        self._thread = None
        with self._lock:
            self._frames.clear()
