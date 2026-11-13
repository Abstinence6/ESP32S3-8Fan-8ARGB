import unittest

from pc_app.config_backup import export_settings, validate_backup, restore_settings


class Settings:
    def __init__(self, items=None):
        self.data = dict(items or {})
    def allKeys(self):
        return list(self.data)
    def value(self, key):
        return self.data[key]
    def setValue(self, key, value):
        self.data[key] = value
    def sync(self):
        pass


class BackupTests(unittest.TestCase):
    def test_exclude_credentials_and_untrusted_fields(self):
        src = Settings({
            "source1": "nwinfo/gpu/radeon/temperature",
            "groupWeights1": '{"gpu":1.0}',
            "mqttPassword": "secret",
            "wifiPassword": "secret2",
            "sacnEnabled": True,
            "startExe": "C:\\attacker.exe",
        })
        backup = export_settings(src)
        serialized = str(backup)
        self.assertNotIn("secret", serialized)
        self.assertNotIn("attacker", serialized)
        dst = Settings()
        self.assertEqual(restore_settings(dst, backup), 3)
        self.assertEqual(dst.data["source1"], src.data["source1"])

    def test_malformed_key_rejected_before_writes(self):
        destination = Settings({"autoProfiles": "false"})
        backup = {"schema": 1, "application": "FanARGBControl",
                  "settings": {"autoProfiles": "true", "exec": "bad"}}
        with self.assertRaises(ValueError):
            restore_settings(destination, backup)
        self.assertEqual(destination.data["autoProfiles"], "false")


if __name__ == "__main__":
    unittest.main()
