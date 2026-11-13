import unittest

from pc_app.device_config_protocol import (
    decode_value, encode_value, fields, mqtt_commands, wifi_command,
)


class DeviceConfigurationTests(unittest.TestCase):
    def test_utf8_space_wifi_and_password_transport(self):
        command = wifi_command("Мій Wi-Fi 5G", "секретний ключ 123")
        parts = command.split()
        self.assertEqual(parts[:2], ["WIFI", "SETHEX"])
        self.assertEqual(decode_value(parts[2], 32), "Мій Wi-Fi 5G")
        self.assertEqual(decode_value(parts[3], 64), "секретний ключ 123")
        self.assertNotIn("секрет", command)
        self.assertEqual(
            wifi_command("Мій Wi-Fi 5G", "", previous_ssid="Мій Wi-Fi 5G", configured=True),
            f"WIFI SETHEX {encode_value('Мій Wi-Fi 5G', 32)} KEEP",
        )
        with self.assertRaises(ValueError):
            wifi_command("new WiFi", "", previous_ssid="old", configured=True)
        self.assertEqual(wifi_command("Cafe WiFi", "", open_network=True).split()[-1], "-")

    def test_reject_invalid_hex_length_nul_and_utf8(self):
        for item in ("XYZ", "AA0", "00", "FFFF" * 20, "FF"):
            with self.assertRaises(ValueError):
                decode_value(item, 32)
        with self.assertRaises(ValueError):
            encode_value("abc\x00def", 32)
        with self.assertRaises(ValueError):
            wifi_command("x", "short")

    def test_mqtt_disabled_does_not_enable_by_setting_broker(self):
        cmds = mqtt_commands(
            host="192.168.1.7", port=1883, username="home assist",
            password="secret key!", enabled=False, discovery=False,
            current={"enabled": False, "discovery": True},
        )
        self.assertEqual(cmds[0], "MQTT BROKER 192.168.1.7 1883")
        self.assertIn("MQTT AUTHHEX", cmds[1])
        self.assertNotIn("secret key!", " ".join(cmds))
        self.assertEqual(cmds[-1], "MQTT HA OFF")
        self.assertNotIn("MQTT ON", cmds)

    def test_mqtt_password_keep_and_enable(self):
        cmd = mqtt_commands(
            host="mqtt.local", port=1883, username="ha", password="",
            enabled=True, discovery=True,
            current={"host": "mqtt.local", "port": 1883, "username": "ha",
                     "enabled": False, "discovery": True},
        )
        self.assertEqual(cmd, ["MQTT ON"])
        with self.assertRaises(ValueError):
            mqtt_commands(host="mqtt.local", port=1883, username="new",
                          password="", enabled=True, discovery=True)
        self.assertEqual(
            mqtt_commands(host="", port=1883, username="", password="",
                          enabled=False, discovery=True, current={}), ["MQTT HA ON", "MQTT OFF"],
        )

    def test_parses_machine_readable_status(self):
        data = fields("WIFI_CONFIG ENABLED=1 SSID_HEX=4D792057696669 IP=1.2.3.4", "WIFI_CONFIG")
        self.assertEqual(decode_value(data["SSID_HEX"], 32), "My Wifi")


if __name__ == "__main__":
    unittest.main()
