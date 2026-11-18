import unittest
from pc_app.fan_groups import FanGroup, command, dumps, loads, validate

class FanGroupTests(unittest.TestCase):
    def test_roundtrip_and_mask(self):
        groups = (FanGroup("Intake", (1, 2, 3)), FanGroup("Exhaust", (6,)))
        self.assertEqual(loads(dumps(groups)), groups)
        self.assertEqual(command(groups[0], "manual", 65), "FANMASK MANUAL 7 65")
        self.assertEqual(command(groups[1], "auto"), "FANMASK AUTO 32")

    def test_duplicate_and_bad_data(self):
        with self.assertRaises(ValueError):
            validate((FanGroup("First", (1,2)), FanGroup("Second", (2,))))
        for raw in ('[]', '{"version":9,"groups":[]}', '{"version":1,"groups":[{"name":"A","channels":[1,1]}]}'):
            with self.assertRaises(ValueError):
                loads(raw)
        with self.assertRaises(ValueError):
            command(FanGroup("A", (1,)), "manual", 101)

if __name__ == "__main__":
    unittest.main()
