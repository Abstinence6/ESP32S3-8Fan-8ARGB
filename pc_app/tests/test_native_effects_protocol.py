import unittest
from pc_app.native_effects_protocol import make_fx_set, parse_fx_line

class NativeEffectsTests(unittest.TestCase):
    def test_commands_and_readback(self):
        self.assertEqual(make_fx_set(2,2,(10,20,30),(90,100,110),3,64,0),
                         "FX SET 2 2 10 20 30 90 100 110 3 64 0")
        line="FX CH=2 MODE=2 R1=10,20,30 R2=90,100,110 SPEED=3 BRIGHT=64 DIR=0 BOOT=1 ACTIVE=1"
        state=parse_fx_line(line)
        self.assertIsNotNone(state)
        self.assertTrue(state.boot)
        self.assertEqual(state.secondary,(90,100,110))
        self.assertIsNone(parse_fx_line(line.replace("SPEED=3","SPEED=0")))
        with self.assertRaises(ValueError):
            make_fx_set(0,1,(1,2,3),(4,5,6),3,64,0)

if __name__=="__main__":
    unittest.main()
