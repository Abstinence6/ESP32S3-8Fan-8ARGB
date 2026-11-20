"""Guardrails for N16R8 USB diagnostics, not a physical watchdog repro."""
import configparser
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class N16R8DiagnosticBuildTests(unittest.TestCase):
    def test_n16r8_specific_memory_and_usb_settings(self):
        pio = configparser.ConfigParser(interpolation=None)
        pio.read(ROOT / "platformio.ini")
        env=pio["env:esp32s3_n16r8_usb_diag"]
        self.assertEqual(env["extends"].strip(),"env:esp32s3_native_usb")
        self.assertEqual(env["board_upload.flash_size"].strip(),"16MB")
        self.assertEqual(env["board_build.arduino.memory_type"].strip(),"qio_opi")
        self.assertEqual(env["board_build.psram_type"].strip(),"opi")
        self.assertEqual(env["board_build.flash_mode"].strip(),"qio")
        self.assertEqual(env["board_build.f_flash"].strip(),"80000000L")
        self.assertEqual(env["board_build.partitions"].strip(),"default_16MB.csv")
        self.assertIn("BOARD_HAS_PSRAM=1",env["build_flags"])
        self.assertIn("ARDUINO_USB_CDC_ON_BOOT=1",env["build_flags"])

    def test_diagnostic_never_initializes_existing_cooling_pins(self):
        pio = configparser.ConfigParser(interpolation=None)
        pio.read(ROOT / "platformio.ini")
        filt=pio["env:esp32s3_n16r8_usb_diag"]["build_src_filter"]
        self.assertIn("-<*>",filt)
        self.assertIn("+<NativeUsbN16R8Diagnostics.cpp>",filt)
        source=(ROOT/"src/NativeUsbN16R8Diagnostics.cpp").read_text()
        for forbidden in (
            "#include \"FanController.h\"", "pinMode(", "ledcSetup(",
            "ledcAttachPin(", "gpio_set_level(", "Adafruit_NeoPixel",
            "#include \"ArgbController.h\"", "Preferences ",
            "analogWrite(", "digitalWrite(",
        ):
            self.assertNotIn(forbidden,source)
        board=(ROOT/"include/BoardConfig.h").read_text()
        self.assertIn("kN16R8Fan2Rerouted ? 8 : 35", board)
        self.assertIn("kN16R8Fan2Rerouted ? 11 : 36", board)
        self.assertIn("kN16R8Fan2Rerouted ? 17 : 37", board)
        self.assertIn("#define FANARGB_N16R8_FAN2_REROUTED 0", board)
        self.assertIn("!kN16R8Safe || ch != 1U || kN16R8Fan2Rerouted", board)
        # Operational fan/ARGB firmware is NOT safe on Octal PSRAM modules.


class N16R8ValidatedDcBuildTests(unittest.TestCase):
    def test_dc_validation_is_isolated_to_explicit_native_usb_variant(self):
        pio = configparser.ConfigParser(interpolation=None)
        pio.read(ROOT / "platformio.ini")
        name = "env:esp32s3_n16r8_native_usb_dc_validated"
        env = pio[name]
        self.assertEqual(env["extends"].strip(), "env:esp32s3_n16r8_native_usb")
        self.assertEqual(env["build_flags"].splitlines()[1:], [
            "${env:esp32s3_n16r8_native_usb.build_flags}",
            "-D FAN_DC_PWM_VALIDATED=1",
        ])
        dc_opt_in_environments = {
            name, "env:esp32s3_n16r8_native_usb_fan2_rerouted_dc_validated"
        }
        for section in pio.sections():
            if section not in dc_opt_in_environments:
                self.assertNotIn("FAN_DC_PWM_VALIDATED",
                                 pio[section].get("build_flags", ""))
        rerouted = pio["env:esp32s3_n16r8_native_usb_fan2_rerouted"]
        self.assertEqual(rerouted["extends"].strip(),
                         "env:esp32s3_n16r8_native_usb")
        self.assertIn("FANARGB_N16R8_FAN2_REROUTED=1", rerouted["build_flags"])
        board = (ROOT / "include/BoardConfig.h").read_text()
        for setting in ("FAN_DC_PWM_VALIDATED", "PC_POWER_ENABLED", "HARDWARE_TEMP_ENABLED"):
            self.assertIn(f"#define {setting} 0", board)
        self.assertIn("FANARGB_N16R8_SAFE=1",
                      pio["env:esp32s3_n16r8_native_usb"]["build_flags"])
        self.assertIn("FANARGB_N16R8_FAN2_REROUTED=1",
                      pio["env:esp32s3_n16r8_native_usb"]["build_flags"])
        self.assertNotIn("FAN_DC_PWM_VALIDATED",
                         pio["env:esp32s3_n16r8_native_usb"]["build_flags"])


if __name__ == "__main__":
    unittest.main()
