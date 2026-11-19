# Native smoke tests

Run from the project root:

```sh
bash test/native/run.sh
python -m unittest discover -s pc_app/tests -v
```

The C++ runner builds the firmware source files (with lightweight mocks for Arduino, Adafruit NeoPixel and Preferences). It tests initial PWM, inversion, RPM, automatic fan curves, sensor loss full-speed fail-safe, calibration, NVS persistence across simulated reboots and malformed Serial commands. Python tests validate LibreHardwareMonitor sensor tree parsing and curve/temperature protocol framing.

These are **host smoke tests**, not an actual ESP32-S3 build or electrical validation. GitHub Actions runs the PlatformIO cross-compiler. Hardware behavior, fan stall/current, thermals and signal integrity require bench testing.

The runner compiles an additional safety-guard executable **without** `FAN_DC_PWM_VALIDATED`: 2/3-pin channels must be clamped at 100% with unvalidated smart keys, and unsupported 4-pin mode is rejected. Other native tests use the compile-time validation switch as a test fixture; existing firmware environments still default to 0. The explicit `esp32s3_n16r8_native_usb_dc_validated` environment is the only opt-in exception for the user's bench-qualified power stage. The N16R8 isolation test runs both with and without DC validation; the validated variant also verifies partial duty, zero-duty requests under stale/overheated/faulted conditions, and stall fault latching without enabling channel 2 or auxiliary GPIO features.
