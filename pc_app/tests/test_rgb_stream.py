"""Adaptive transport honors physical RGB throughput and the ESP keepalive."""
import unittest

from pc_app.rgb_stream import AdaptiveRgbStream


class RgbStreamTests(unittest.TestCase):
    def test_eight_long_strips_slow_down_but_eight_short_strips_stay_fast(self):
        stream = AdaptiveRgbStream(byte_rate=60000)
        long_frames = {ch: bytes([ch, 2, 3]) * 170 for ch in range(1, 9)}
        stream.offer(long_frames, [170] * 8, now=10)
        self.assertAlmostEqual(stream.target_fps(now=10), 60000 / (517 * 8), places=5)
        queued = []
        self.assertEqual(stream.dispatch(lambda ch, packet: queued.append((ch, packet)), now=10), 8)
        updated = {ch: bytes([ch, 4, 5]) * 170 for ch in range(1, 9)}
        stream.offer(updated, [170] * 8, now=10.04)
        self.assertEqual(stream.dispatch(lambda ch, packet: queued.append((ch, packet)), now=10.04), 0)
        self.assertEqual(stream.dispatch(lambda ch, packet: queued.append((ch, packet)), now=10.08), 8)
        self.assertEqual(len(queued), 16)
        stream.reset()
        stream.offer({ch: bytes([ch, 2, 3]) * 10 for ch in range(1, 9)}, [10] * 8, now=20)
        self.assertEqual(stream.target_fps(now=20), 25)

    def test_unchanged_frames_are_suppressed_and_kept_alive(self):
        stream = AdaptiveRgbStream(keepalive_seconds=2.0)
        scene = {1: b'\x01\x02\x03'}
        sent = []
        stream.offer(scene, [1] * 8, now=1)
        self.assertEqual(stream.dispatch(lambda ch, packet: sent.append(packet), now=1), 1)
        stream.offer(scene, [1] * 8, now=1.1)
        self.assertEqual(stream.dispatch(lambda ch, packet: sent.append(packet), now=1.1), 0)
        stream.offer(scene, [1] * 8, now=2.9)
        self.assertEqual(stream.dispatch(lambda ch, packet: sent.append(packet), now=2.9), 0)
        stream.offer(scene, [1] * 8, now=3.1)
        self.assertEqual(stream.dispatch(lambda ch, packet: sent.append(packet), now=3.1), 1)
        self.assertEqual(len(sent), 2)
        self.assertEqual(stream.frames_unchanged, 2)

    def test_latest_wins_and_geometry_is_clamped(self):
        stream = AdaptiveRgbStream()
        stream.offer({3: b'\x00\x00\x00' * 3}, [2] * 8, now=5)
        stream.offer({3: b'\xff\x00\x00' * 3}, [2] * 8, now=5)
        self.assertEqual(stream.frames_coalesced, 1)
        packets = []
        self.assertEqual(stream.dispatch(lambda ch, packet: packets.append(packet), now=5), 1)
        self.assertEqual(packets[0][2:5], b'\x03\x02\x00')
        self.assertEqual(packets[0][5:-2], b'\xff\x00\x00' * 2)
        self.assertEqual(stream.offer({9: b'\x00' * 3, 2: b'\x00' * 4}, [2] * 8, now=6), 0)

    def test_no_stale_replay_after_reset_or_failed_queue(self):
        stream = AdaptiveRgbStream()
        scene = {1: b'\x10\x20\x30'}
        stream.offer(scene, [1] * 8, now=1)
        with self.assertRaises(OSError):
            stream.dispatch(lambda ch, packet: False, now=1)
        forwarded = []
        self.assertEqual(stream.dispatch(lambda ch, packet: forwarded.append(packet), now=1), 1)
        stream.reset()
        stream.offer(scene, [1] * 8, now=1.1)
        self.assertEqual(stream.dispatch(lambda ch, packet: forwarded.append(packet), now=1.1), 1)
        self.assertEqual(len(forwarded), 2)


if __name__ == '__main__':
    unittest.main()
