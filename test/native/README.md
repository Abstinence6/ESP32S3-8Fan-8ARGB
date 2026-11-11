# Native smoke tests

Run from the project root:

```sh
bash test/native/run.sh
python -m unittest discover -s pc_app/tests -v
```

The C++ runner builds the firmware source files (with lightweight mocks for Arduino, Adafruit NeoPixel and Preferences). It tests initial PWM, inversion, RPM, automatic fan curves, sensor loss full-speed fail-safe, calibration, NVS persistence across simulated reboots and malformed Serial commands. Python tests validate LibreHardwareMonitor sensor tree parsing and curve/temperature protocol framing.

These are **host smoke tests**, not an actual ESP32-S3 build or electrical validation. GitHub Actions runs the PlatformIO cross-compiler. Hardware behavior, fan stall/current, thermals and signal integrity require bench testing.
