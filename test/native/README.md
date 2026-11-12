# Native smoke tests

Run from the project root:

```sh
bash test/native/run.sh
python -m unittest discover -s pc_app/tests -v
```

The C++ runner builds the firmware source files (with lightweight mocks for Arduino, Adafruit NeoPixel and Preferences). It tests initial PWM, inversion, RPM, automatic fan curves, sensor loss full-speed fail-safe, calibration, NVS persistence across simulated reboots and malformed Serial commands. Python tests validate LibreHardwareMonitor sensor tree parsing and curve/temperature protocol framing.

These are **host smoke tests**, not an actual ESP32-S3 build or electrical validation. GitHub Actions runs the PlatformIO cross-compiler. Hardware behavior, fan stall/current, thermals and signal integrity require bench testing.

The runner compiles an additional safety-guard executable **without** `FAN_DC_PWM_VALIDATED`: 2/3-pin channels must be clamped at 100% with unvalidated smart keys, and 4-pin types must be rejected. Other native tests use the compile-time validation switch strictly as a test fixture; shipping firmware defaults to 0.

Additional tests validate v3 NVS migration into 2/3-pin-only v4 profiles, invalid old RPM maps, short TACH glitches, and MQTT serial configuration (not a live network broker). The MQTT network task and hardware timing require PlatformIO/board tests.
