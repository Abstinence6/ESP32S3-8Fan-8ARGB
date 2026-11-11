import socket
import unittest

from pc_app.sacn_bridge import (
    E131Listener, decode_sacn, encode_rgb_frame, crc16_ccitt, SACN_PORT,
)


def make_sacn(universe: int, rgb: bytes, start_code: int = 0) -> bytes:
    count = len(rgb) + 1
    total = 126 + len(rgb)
    packet = bytearray(total)
    packet[0:2] = b'\x00\x10'
    packet[4:16] = b'ASC-E1.17\x00\x00\x00'
    packet[16:18] = (0x7000 | (total - 16)).to_bytes(2, 'big')
    packet[18:22] = b'\x00\x00\x00\x04'
    packet[38:40] = (0x7000 | (total - 38)).to_bytes(2, 'big')
    packet[40:44] = b'\x00\x00\x00\x02'
    packet[113:115] = universe.to_bytes(2, 'big')
    packet[115:117] = (0x7000 | (total - 115)).to_bytes(2, 'big')
    packet[117] = 2
    packet[118] = 0xA1
    packet[121:123] = b'\x00\x01'
    packet[123:125] = count.to_bytes(2, 'big')
    packet[125] = start_code
    packet[126:] = rgb
    return bytes(packet)


class SacnTests(unittest.TestCase):
    def test_sacn_data_packet_per_universe(self):
        rgb = b'\xff\x01\x00\x00\x00\xff'
        self.assertEqual(decode_sacn(make_sacn(3, rgb)), (3, rgb))
        self.assertIsNone(decode_sacn(make_sacn(0, rgb)))
        self.assertIsNone(decode_sacn(make_sacn(9, rgb)))
        self.assertIsNone(decode_sacn(make_sacn(1, rgb, start_code=1)))

    def test_rejects_malformed_packet(self):
        raw = make_sacn(1, b'\x01\x02\x03')
        for damaged in (b'', raw[:100], raw[:-1],
                        raw[:4] + b'not-acn' + raw[11:],
                        raw[:16] + b'\x00\x01' + raw[18:]):
            self.assertIsNone(decode_sacn(damaged))
        preview = bytearray(raw)
        preview[112] = 0x80
        self.assertIsNone(decode_sacn(bytes(preview)))

    def test_valid_rgb_framing_and_crc(self):
        rgb = bytes((255, 0, 0, 1, 2, 3, 0xa5, 0x5a, 10))
        packet = encode_rgb_frame(5, rgb)
        self.assertEqual(packet[:5], b'\xa5\x5a\x05\x03\x00')
        self.assertEqual(packet[5:-2], rgb)
        self.assertEqual(int.from_bytes(packet[-2:], 'little'), crc16_ccitt(packet[2:-2]))
        with self.assertRaises(ValueError):
            encode_rgb_frame(0, rgb)
        with self.assertRaises(ValueError):
            encode_rgb_frame(2, b'\x00\x01')
        with self.assertRaises(ValueError):
            encode_rgb_frame(2, bytes(171 * 3))

    def test_nonblocking_udp_and_coalesce(self):
        listener = E131Listener('127.0.0.1', 0)
        listener.start()
        try:
            port = listener.sock.getsockname()[1]
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as src:
                src.sendto(make_sacn(2, b'\xff\x00\x00'), ('127.0.0.1', port))
                src.sendto(make_sacn(2, b'\x00\xff\x00'), ('127.0.0.1', port))
                src.sendto(make_sacn(8, b'\x00\x00\xff'), ('127.0.0.1', port))
            self.assertEqual(listener.read_latest(), {2: b'\x00\xff\x00', 8: b'\x00\x00\xff'})
            self.assertEqual(listener.read_latest(), {})
        finally:
            listener.stop()


if __name__ == '__main__':
    unittest.main()
