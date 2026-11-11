# Native smoke tests

Run from the project root:

```sh
./test/native/run.sh
```

The test runner compiles the firmware classes (including `src/main.cpp`) with lightweight host mocks for Arduino and Adafruit NeoPixel. It checks initial PWM, inverted PWM duty, RPM math, independent ARGB channels, serial command handling and malformed inputs.

This is a **smoke test, not a real ESP32-S3 build**. PlatformIO CI compiles the actual firmware when the project is pushed to GitHub. Electrical behavior and timing still require hardware-in-the-loop testing.
