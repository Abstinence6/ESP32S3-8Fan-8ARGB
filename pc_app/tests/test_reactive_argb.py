import unittest
from pc_app.monitor import TemperatureSensor
from pc_app.nwinfo_sensors import HardwareMetric
from pc_app.reactive_argb import (
    ReactiveScene,default_scene,make_set,parse_readback,
    load_slots,dump_slots,value_commands
)

class ReactiveArgbTests(unittest.TestCase):
    def test_scene_command_and_readback(self):
        scene=default_scene(2)
        self.assertEqual(make_set(scene),
            "RFX SET 2 10 0 1 300 850 2 0 100 255 255 0 0 3 64 0")
        line=("RFX CH=2 SRC=26 FALL=1 STYLE=2 LOW=100 HIGH=900 PATTERN=2 "
              "R1=10,20,30 R2=100,110,120 SPEED=3 BRIGHT=64 DIR=0 "
              "BOOT=1 ACTIVE=1 FRESH=1 VALUE=555")
        got=parse_readback(line)
        self.assertIsNotNone(got)
        self.assertTrue(got.boot)
        self.assertEqual(got.value,555)
        self.assertIsNone(parse_readback(line.replace("FALL=1","FALL=26")))
        with self.assertRaises(ValueError):
            make_set(ReactiveScene(**{**scene.__dict__,"low":1000,"high":100}))
    def test_selected_host_metric_and_temperature_are_only_live_values(self):
        slots=[""]*8
        slots[0]="metric:nwinfo/gpu/radeon/utilization"
        slots[1]="metric:nwinfo/gpu/radeon/power"
        slots[2]="temp:nwinfo/cpu/package/temperature"
        raw=dump_slots(slots)
        self.assertEqual(load_slots(raw),tuple(slots))
        m=[HardwareMetric("nwinfo/gpu/radeon/utilization","GPU load",93.2,"%","load"),
           HardwareMetric("nwinfo/gpu/radeon/power","GPU power",245.6,"W","power")]
        t=[TemperatureSensor("nwinfo/cpu/package/temperature","CPU",58.4)]
        self.assertEqual(value_commands(raw,t,m),(
            "RVAL 1 932","RVAL 2 2456","RVAL 3 584"))
        self.assertEqual(value_commands(raw,[],[]),())
        self.assertEqual(value_commands(raw,[],[HardwareMetric(
            "nwinfo/gpu/radeon/utilization","GPU",float("nan"),"%","load")]),())
        with self.assertRaises(ValueError):
            load_slots('{"version":1,"slots":["C:/bad.exe",null]}')
        with self.assertRaises(ValueError):
            dump_slots(["metric:untrusted/id"]+[""]*7)

if __name__=="__main__":
    unittest.main()
