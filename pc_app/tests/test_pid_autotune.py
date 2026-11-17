import unittest
from pc_app.pid_autotune import (
    recommend_pid, parse_pid_gains, gains_command,
)


class SafePidAutotuneTests(unittest.TestCase):
    def test_estimate_from_two_stable_plateaus(self):
        sample = [
            (0, 40, 1000, 45), (5, 40, 1000, 45),
            (10, 40, 1010, 45), (15, 40, 1005, 45),
            (20, 60, 1080, 45), (25, 60, 1230, 45),
            (30, 60, 1450, 45), (35, 60, 1600, 45),
            (40, 60, 1602, 45), (45, 60, 1598, 45),
        ]
        rec = recommend_pid(sample, now=45)
        self.assertTrue(8 <= rec.kp_milli <= 40)
        self.assertTrue(0 <= rec.ki_milli <= 6)
        self.assertTrue(0 <= rec.kd_milli <= 8)
        self.assertGreater(rec.rpm_delta, 450)
        self.assertEqual(len(rec.gains), 3)

    def test_reject_bad_sign_noise_or_no_step(self):
        for values in (
            [(i * 5, 40, 1000 + i, 45) for i in range(10)],
            [(i * 5, 40 if i < 5 else 60,
              1000 if i < 5 else 700, 45) for i in range(10)],
            [(i * 5, 40 if i < 5 else 60, 0, 45) for i in range(10)],
        ):
            with self.assertRaises(ValueError):
                recommend_pid(values, now=45)

    def test_stale_and_nonmonotonic_rejected(self):
        sample = [(i * 5, 40 if i < 5 else 60,
                   1000 if i < 5 else 1400, 45) for i in range(10)]
        with self.assertRaises(ValueError):
            recommend_pid(sample, now=1000)
        sample[6] = sample[5]
        with self.assertRaises(ValueError):
            recommend_pid(sample, now=45)

    def test_wire_readback(self):
        self.assertEqual(parse_pid_gains("PIDGAINS CH=4 KP=30 KI=3 KD=4"),
                         (4, (30, 3, 4)))
        self.assertEqual(gains_command(4, (30, 3, 4)),
                         "PIDGAINS 4 30 3 4")
        for packet in ("PIDGAINS CH=0 KP=30 KI=3 KD=4",
                       "PIDGAINS CH=4 KP=300 KI=3 KD=4",
                       "PIDGAINS CH=4 KP=30 KI=3"):
            with self.assertRaises(ValueError):
                parse_pid_gains(packet)


if __name__ == "__main__":
    unittest.main()
