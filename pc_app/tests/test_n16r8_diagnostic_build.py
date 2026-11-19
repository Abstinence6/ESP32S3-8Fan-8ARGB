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
        self.assertEqual(env["board_build.flash_mode"].strip(),"dio")
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
        self.assertIn("{21, 35, 39, 42",board)
        self.assertIn("{47, 36, 40, 2",board)
        self.assertIn("{48, 37, 41, 1",board)
        # Operational fan/ARGB firmware is NOT safe on Octal PSRAM modules.


if __name__ == "__main__":
    unittest.main()
