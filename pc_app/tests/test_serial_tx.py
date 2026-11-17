import unittest

from pc_app.serial_tx import SerialTransmitter
from pc_app.sacn_bridge import encode_rgb_frame


class FakePort:
    def __init__(self):
        self.events = []
        self.partial = False
    def write(self, payload):
        self.events.append(payload)
        return len(payload)-1 if self.partial else len(payload)


class SerialTxTests(unittest.TestCase):
    def test_control_before_rgb_and_coalescing(self):
        port = FakePort()
        tx = SerialTransmitter(port, rgb_interval=0.04)
        old = encode_rgb_frame(1, bytes([1,2,3]))
        new = encode_rgb_frame(1, bytes([4,5,6]))
        two = encode_rgb_frame(2, bytes([7,8,9]))
        tx.queue_rgb(1, old)
        tx.queue_rgb(1, new)
        tx.queue_rgb(2, two)
        tx.send_command("TEMP 1 450")
        self.assertEqual(port.events, [b"TEMP 1 450\n"])
        tx.flush_rgb(now=20)
        self.assertEqual(port.events[-1], new)
        self.assertEqual(tx.flush_rgb(now=20.01), 0)
        tx.flush_rgb(now=20.05)
        self.assertEqual(port.events[-1], two)
        self.assertEqual(tx.frames_dropped, 1)

    def test_eight_zones_cannot_starve_under_repeated_updates(self):
        port = FakePort()
        tx = SerialTransmitter(port, rgb_interval=0)
        for step in range(80):
            for ch in range(1, 9):
                tx.queue_rgb(ch, encode_rgb_frame(ch, bytes([step, ch, 0])))
            tx.flush_rgb(now=float(step))
        channels = [frame[2] for frame in port.events]
        self.assertEqual(len(channels), 80)
        self.assertEqual([channels.count(ch) for ch in range(1, 9)], [10] * 8)

    def test_batched_rgb_uses_uart_budget(self):
        port = FakePort()
        tx = SerialTransmitter(port, rgb_interval=0, rgb_byte_rate=1000)
        for ch in range(1, 9):
            tx.queue_rgb(ch, encode_rgb_frame(ch, bytes([255, 255, 255]) * 170))
        self.assertEqual(tx.flush_rgb(now=10, max_frames=8), 4 * 517)
        self.assertEqual(tx.flush_rgb(now=10, max_frames=8), 0)
        self.assertEqual(tx.flush_rgb(now=13, max_frames=8), 4 * 517)
        self.assertEqual([packet[2] for packet in port.events], list(range(1, 9)))
        with self.assertRaises(ValueError):
            tx.flush_rgb(max_frames=0)

    def test_never_retry_partial_frame(self):
        port = FakePort()
        tx = SerialTransmitter(port)
        tx.queue_rgb(2, encode_rgb_frame(2, bytes([3,2,1])))
        port.partial = True
        with self.assertRaises(OSError):
            tx.flush_rgb(now=10)
        self.assertIn(2, tx.pending_rgb)  # caller must disconnect/clear
        tx.clear()
        self.assertFalse(tx.pending_rgb)
        with self.assertRaises(OSError):
            tx.send_command("PING")

    def test_control_requires_atomic_line(self):
        tx = SerialTransmitter(FakePort())
        with self.assertRaises(ValueError):
            tx.send_command("TEMP 1 400\nSTATUS")
        with self.assertRaises(ValueError):
            tx.queue_rgb(0, b"bad")


if __name__ == "__main__":
    unittest.main()
