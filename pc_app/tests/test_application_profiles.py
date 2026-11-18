import unittest
from pc_app.application_profiles import (
    AppRule, ApplicationProfilePolicy, dumps, loads, runtime_commands,
)

class AppProfilesTests(unittest.TestCase):
    def test_priority_dwell_and_casefold(self):
        rules=[AppRule("Game.EXE","Performance",80),
               AppRule("Render.exe","Balanced",60)]
        self.assertEqual(loads(dumps(rules))[0].executable,"game.exe")
        policy=ApplicationProfilePolicy(dwell_seconds=4)
        self.assertFalse(policy.consider(rules,{"GAME.EXE"},now=0).ready)
        decision=policy.consider(rules,{"game.exe"},now=4.5)
        self.assertTrue(decision.ready)
        self.assertEqual(decision.profile,"Performance")
        self.assertFalse(policy.consider(rules,{"render.exe"},now=5).ready)
        self.assertEqual(policy.consider(rules,{"render.exe"},now=9.5).profile,"Balanced")
        self.assertFalse(policy.consider(rules,set(),now=10).ready)
        self.assertIsNone(policy.consider(rules,set(),now=15).profile)

    def test_invalid_rules_and_complete_volatile_transaction(self):
        with self.assertRaises(ValueError):
            loads('{"version":1,"rules":[null]}')
        with self.assertRaises(ValueError):
            loads('{"version":1,"rules":[{"executable":"game.exe","profile":"Silent","priority":50,"extra":1}]}')
        with self.assertRaises(ValueError):
            loads('{"version":2,"rules":[]}')
        with self.assertRaises(ValueError):
            dumps([AppRule("../bad.exe","Silent")])
        with self.assertRaises(ValueError):
            dumps([AppRule("x.exe","Silent"),AppRule("X.exe","Balanced")])
        commands=runtime_commands("Silent")
        self.assertEqual(len(commands),10)
        self.assertEqual(commands[0],"RTCURVE BEGIN")
        self.assertEqual(commands[-1],"RTCURVE COMMIT")
        self.assertEqual(len([c for c in commands if c.startswith("RTCURVE SET")]),8)

if __name__ == "__main__":
    unittest.main()
