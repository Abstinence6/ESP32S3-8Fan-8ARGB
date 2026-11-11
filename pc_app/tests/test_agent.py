import json
import unittest
from unittest.mock import Mock
from pc_app.agent import make_sensor_commands
from pc_app.monitor import TemperatureSensor

class AgentTests(unittest.TestCase):
    def test_sensor_routes_and_dual(self):
        data = {
            'source1':'cpu', 'source21':'gpu', 'dualEnabled1':'true',
            'source2':'__GROUP_AVG__', 'groupSensors2':json.dumps(['cpu','gpu']),
        }
        settings = Mock()
        settings.value.side_effect = lambda key, default=None: data.get(key, default)
        readings=[TemperatureSensor('cpu','CPU',65.0), TemperatureSensor('gpu','GPU',70.0)]
        result=make_sensor_commands(settings, readings)
        self.assertIn('TEMP 1 650', result)
        self.assertIn('TEMP2 1 700', result)
        self.assertIn('TEMP 2 675', result)

if __name__ == '__main__': unittest.main()
