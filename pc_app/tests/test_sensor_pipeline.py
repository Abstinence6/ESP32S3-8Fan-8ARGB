"""Both PC modes must plan exactly the same safe ESP32 commands."""
import json
from types import SimpleNamespace
import unittest

from pc_app.monitor import GROUP_AVG, GROUP_MAX, GROUP_WEIGHTED, MAX_ALL, MAX_CPU_GPU, TemperatureSensor
from pc_app.sensor_pipeline import (
    FanSensorRoute, routes_from_settings, plan_sensor_telemetry,
    choose_automatic_profile, automatic_profile_commands,
)
from pc_app.smart_control import SafeTemperatureFilter, AutoProfileSelector


class _Settings:
    def __init__(self, values):
        self.values = values

    def value(self, key, default=None):
        return self.values.get(key, default)


class SensorPipelineTests(unittest.TestCase):
    def test_settings_and_live_gui_routes_have_identical_commands(self):
        data = {
            'source1': 'cpu', 'source21': 'gpu', 'dualEnabled1': 'true',
            'source2': GROUP_AVG, 'groupSensors2': json.dumps(['cpu', 'gpu']),
        }
        sensors = [TemperatureSensor('cpu', 'CPU', 65), TemperatureSensor('gpu', 'GPU', 70)]
        settings_routes = routes_from_settings(_Settings(data))
        gui_routes = list(settings_routes)
        gui_routes[0] = FanSensorRoute(primary='cpu', secondary='gpu', dual=True)
        gui_routes[1] = FanSensorRoute(primary=GROUP_AVG, group_ids=('cpu', 'gpu'))
        agent = plan_sensor_telemetry(settings_routes, sensors, include_power=False)
        gui = plan_sensor_telemetry(gui_routes, sensors, include_power=False)
        self.assertEqual(agent.commands, gui.commands)
        self.assertIn('TEMP 1 650', gui.commands)
        self.assertIn('TEMP2 1 700', gui.commands)
        self.assertIn('TEMP 2 675', gui.commands)

    def test_resolution_evidence_matches_unfiltered_temperature_commands(self):
        from pc_app.sensor_pipeline import resolve_route_temperature

        readings = [TemperatureSensor('cpu', 'CPU Package', 40),
                    TemperatureSensor('gpu', 'GPU Hot Spot', 60),
                    TemperatureSensor('ssd', 'Storage', 80)]
        for assignment, expected, contributors in (
            (MAX_ALL, 80, ('Storage',)), (MAX_CPU_GPU, 60, ('GPU Hot Spot',)),
            (GROUP_MAX, 60, ('GPU Hot Spot',)), (GROUP_AVG, 50, ('CPU Package', 'GPU Hot Spot')),
            (GROUP_WEIGHTED, 55, ('CPU Package', 'GPU Hot Spot')), ('cpu', 40, ('CPU Package',)),
        ):
            with self.subTest(assignment=assignment):
                route = FanSensorRoute(primary=assignment, group_ids=('cpu', 'gpu'), weights={'gpu': 3})
                evidence = resolve_route_temperature(route.primary, readings, route.group_ids, route.weights)
                self.assertEqual(evidence.celsius, expected)
                self.assertEqual(sorted(sensor.name for sensor in evidence.contributors), sorted(contributors))
                plan = plan_sensor_telemetry([route] * 8, readings, include_power=False)
                self.assertEqual(plan.commands[0], f'TEMP 1 {expected * 10}')
        route = FanSensorRoute(primary=GROUP_WEIGHTED, group_ids=('cpu', 'gpu'), weights={'gpu': 3})
        evidence = resolve_route_temperature(route.primary, readings[:1], route.group_ids, route.weights)
        self.assertIsNone(evidence.celsius)
        self.assertEqual(evidence.contributors, ())
        self.assertEqual(evidence.missing_ids, ('gpu',))
        self.assertFalse(plan_sensor_telemetry([route] * 8, readings[:1], include_power=False).commands)

    def test_missing_sensor_clears_smoothing_and_only_valid_power_is_sent(self):
        routes = [FanSensorRoute(primary='cpu'), *[FanSensorRoute(primary='missing')] * 7]
        smoothing = SafeTemperatureFilter()
        warm = [TemperatureSensor('cpu', 'CPU', 70)]
        result = plan_sensor_telemetry(routes, warm, [], filter_engine=smoothing, smoothing=True, now=100)
        self.assertEqual(result.commands, ('TEMP 1 700', 'PWRDATA 65535 65535'))
        absent = plan_sensor_telemetry(routes, [], [], filter_engine=smoothing, smoothing=True, now=101)
        self.assertEqual(absent.commands, ('PWRDATA 65535 65535',))
        cool = [TemperatureSensor('cpu', 'CPU', 40)]
        result = plan_sensor_telemetry(routes, cool, [], filter_engine=smoothing, smoothing=True, now=102)
        self.assertEqual(result.commands[0], 'TEMP 1 400')

    def test_invalid_weight_does_not_block_other_fan_channels(self):
        routes = [FanSensorRoute(primary=GROUP_WEIGHTED, group_ids=('cpu',), weights={'cpu': 'bad'}),
                  FanSensorRoute(primary='cpu'), *[FanSensorRoute(primary='missing')] * 6]
        readings = [TemperatureSensor('cpu', 'CPU', 61)]
        self.assertEqual(plan_sensor_telemetry(routes, readings, include_power=False).commands,
                         ('TEMP 2 610',))

    def test_power_and_profile_decision_are_shared(self):
        m = lambda name, value, kind='power', unit='W': SimpleNamespace(
            name=name, value=value, kind=kind, unit=unit)
        metrics = [m('CPU Package Power', 110), m('GPU Board Power', 205),
                   m('GPU Utilization', 88, 'load', '%'), m('GPU Bad Load', float('nan'), 'load', '%')]
        result = plan_sensor_telemetry([FanSensorRoute(primary='missing')] * 8, [], metrics)
        self.assertEqual(result.commands, ('PWRDATA 110 205',))
        selector = AutoProfileSelector(dwell_seconds=0, min_change_seconds=0)
        self.assertIsNone(choose_automatic_profile(metrics, selector, hour=12, now=1))
        self.assertEqual(choose_automatic_profile(metrics, selector, hour=12, now=2), 'Performance')
        self.assertEqual(len(automatic_profile_commands('Performance')), 8)
        with self.assertRaises(ValueError):
            automatic_profile_commands('Nonexistent')


if __name__ == '__main__':
    unittest.main()
