import socket
import struct
import time
import unittest

from pc_app.openrgb_native import (
    OpenRGBNativeServer, HEADER, MAGIC, pack_packet, controller_description
)


def request(sock, dev, command, body=b""):
    sock.sendall(pack_packet(dev, command, body))
    header = b""
    while len(header) < HEADER.size:
        header += sock.recv(HEADER.size - len(header))
    magic, device, kind, length = HEADER.unpack(header)
    data = b""
    while len(data) < length:
        data += sock.recv(length - len(data))
    return magic, device, kind, data


class NativeOpenRGBTests(unittest.TestCase):
    def test_description_has_eight_linear_zones(self):
        for protocol in (0, 1):
            body = controller_description((2, 3, 2, 3, 2, 3, 2, 3), protocol)
            self.assertEqual(int.from_bytes(body[:4], "little"), len(body))
            self.assertIn(b"ARGB Zone 1\x00", body)
            self.assertIn(b"ARGB Zone 8\x00", body)
            self.assertIn(b"FanARGB ESP32-S3\x00", body)

    def test_local_sdk_handshake_and_zone_update_without_hardware(self):
        server = OpenRGBNativeServer(port=0)
        server.start([2] * 8)
        try:
            port = server._listener.getsockname()[1]
            with socket.create_connection(("127.0.0.1", port), timeout=2) as sock:
                sock.settimeout(2)
                m, device, kind, data = request(sock, 0, 40, struct.pack("<I", 1))
                self.assertEqual((m, device, kind), (MAGIC, 0, 40))
                self.assertEqual(struct.unpack("<I", data)[0], 1)
                self.assertEqual(struct.unpack("<I", request(sock, 0, 0)[3])[0], 1)
                self.assertIn(b"ARGB Zone 8", request(sock, 0, 1, struct.pack("<I", 1))[3])
                colors = bytes((255, 5, 10, 0, 0, 20, 40, 0))
                data = struct.pack("<IIH", 10 + len(colors), 2, 2) + colors
                sock.sendall(pack_packet(0, 1051, data))
                for _ in range(100):
                    frames = server.read_latest()
                    if frames:
                        break
                    time.sleep(.01)
                self.assertEqual(frames, {3: bytes((255, 5, 10, 0, 20, 40))})
        finally:
            server.stop()

    def test_invalid_frames_do_not_enqueue_pixels(self):
        bridge = OpenRGBNativeServer()
        bridge.led_counts = (2,) * 8
        bridge._colors = [bytearray(6) for _ in range(8)]
        colors = bytes([55, 60, 70, 0] * 2)
        # Inflated length is discarded; never send RGB to an unintended zone.
        bridge._handle(0, 1051, struct.pack("<IIH", 999, 0, 2) + colors)
        bridge._handle(9, 1051, struct.pack("<IIH", 18, 0, 2) + colors)
        self.assertFalse(bridge.read_latest())
        with self.assertRaises(ValueError):
            bridge.start([171] * 8)


if __name__ == "__main__":
    unittest.main()
