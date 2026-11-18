import unittest
from pc_app.autonomy_protocol import (
    parse_profile,parse_airflow,parse_fan,aircfg_command,
)

class OfflineAndAirflowTests(unittest.TestCase):
    def test_profile_status(self):
        p=parse_profile("PROFILE ACTIVE=2 BOOT=1 SLOTS=110")
        self.assertIsNotNone(p)
        self.assertEqual(p.active,2)
        self.assertEqual(p.saved,(True,True,False))
        self.assertIsNone(parse_profile("PROFILE ACTIVE=3 BOOT=1 SLOTS=110"))
        self.assertIsNone(parse_profile("PROFILE ACTIVE=4 BOOT=0 SLOTS=111"))

    def test_airflow_data_validated(self):
        x=parse_airflow("AIRFLOW IN10=700 OUT10=500 BALANCE=29 VALID=1 UNKNOWN=0 TREND=intake-biased")
        self.assertIsNotNone(x)
        self.assertEqual(x.intake_cfm,70.0)
        self.assertIsNone(parse_airflow("AIRFLOW IN10=700 OUT10=500 BALANCE=200 VALID=1 UNKNOWN=0 TREND=intake-biased"))
        self.assertIsNone(parse_airflow("AIRFLOW IN10=700 OUT10=500 BALANCE=0 VALID=0 UNKNOWN=2 TREND=intake-biased"))
        self.assertEqual(aircfg_command(1,1,2000,900,80),"AIRCFG 1 1 2000 900 80")
        self.assertEqual(aircfg_command(1,0,0,0,1),"AIRCFG 1 0 0 0 1")
        with self.assertRaises(ValueError):
            aircfg_command(1,1,0,900,80)
        self.assertEqual(parse_fan("AIRCFG CH=1 DIR=2 RPM=2000 CFM10=900 RESTRICT=80").direction,2)

if __name__=="__main__":
    unittest.main()
