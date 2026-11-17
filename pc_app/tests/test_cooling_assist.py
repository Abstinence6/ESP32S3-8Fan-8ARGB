import unittest
from pc_app.cooling_assist import (
    CoolingAssistConfig, make_assist_command, parse_assist_reply, power_payload,
)


class CoolingAssistTests(unittest.TestCase):
    def test_full_wire_configuration(self):
        cfg = CoolingAssistConfig(
            enabled=True, roles=(1, 2, 0, 0, 1, 2, 1, 2),
            sources=(3, 1, 2, 3, 1, 2, 3, 0),
        )
        wire = make_assist_command(cfg)
        self.assertTrue(wire.startswith("ASSIST SET 1 65 160 100 300 15 5"))
        self.assertLess(len(wire), 240)
        packet = ("ASSIST ENABLE=1 CPU_START=65 CPU_FULL=160 GPU_START=100 "
                  "GPU_FULL=300 BOOST=15 BIAS=5 MAP=1:3,2:1,0:2,0:3,1:1,2:2,1:3,2:0")
        self.assertEqual(parse_assist_reply(packet), cfg)

    def test_invalid_commands_are_rejected(self):
        with self.assertRaises(ValueError):
            CoolingAssistConfig(cpu_start=150, cpu_full=150).validate()
        with self.assertRaises(ValueError):
            CoolingAssistConfig(roles=(0,) * 7).validate()
        with self.assertRaises(ValueError):
            parse_assist_reply("ASSIST ENABLE=1 CPU_START=65 MAP=0:3")

    def test_invalid_power_metrics_are_never_interpreted_as_valid(self):
        self.assertEqual(power_payload(100.4, 210.9), "PWRDATA 100 211")
        self.assertEqual(power_payload(None, 200), "PWRDATA 65535 200")
        self.assertEqual(power_payload(float("nan"), float("inf")),
                         "PWRDATA 65535 65535")
        self.assertEqual(power_payload(4000, -1), "PWRDATA 65535 65535")


if __name__ == "__main__":
    unittest.main()
