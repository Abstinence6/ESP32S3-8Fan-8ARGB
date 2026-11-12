import unittest
from pc_app.config_presets import (
    FAN_CURVES, RGB_SCENES, commands, create_configuration,
    from_json, openrgb_e131_manifest, to_json, validate_configuration,
)


class ConfigPresetTests(unittest.TestCase):
    def test_every_combination(self):
        for cooling in FAN_CURVES:
            for lighting in RGB_SCENES:
                cfg = create_configuration(cooling, lighting)
                self.assertEqual(from_json(to_json(cfg)), cfg)
                self.assertEqual(len(cfg["fan_curves"]), 8)
                self.assertTrue(commands(cfg)[0].startswith("CURVE 1 "))

    def test_independent_fans(self):
        cfg = create_configuration()
        cfg["fan_curves"][0][0][1] = 99
        self.assertNotEqual(cfg["fan_curves"][0], cfg["fan_curves"][1])

    def test_validation(self):
        cfg = create_configuration()
        cfg["fan_curves"][0][1][0] = 0
        with self.assertRaises(ValueError):
            validate_configuration(cfg)
        cfg = create_configuration(rgb_scene="Static warm")
        cfg["argb"][0]["rgb"] = [256, 0, 0]
        with self.assertRaises(ValueError):
            commands(cfg)

    def test_commands_never_change_power_hardware(self):
        for scene in RGB_SCENES:
            lines = commands(create_configuration(rgb_scene=scene))
            self.assertEqual(len([x for x in lines if x.startswith("CURVE ")]), 8)
            self.assertFalse(any(x.startswith(("FAN ", "TYPE ", "RGBBUDGET ")) for x in lines))

    def test_openrgb_reference(self):
        data = openrgb_e131_manifest([30] * 8)
        self.assertEqual([x["universe"] for x in data["devices"]], list(range(1, 9)))
        with self.assertRaises(ValueError):
            openrgb_e131_manifest([171] * 8)


if __name__ == "__main__":
    unittest.main()
