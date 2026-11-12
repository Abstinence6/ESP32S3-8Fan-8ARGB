# Validation matrix — before deploying to real fans

## Automated tests

- `bash test/native/run.sh`: firmware mocks, rejected 4-pin, low-duty guard, TACH, migration, settings and serial parser.
- `python -m unittest discover -s pc_app/tests -v`: sensor parsing, serial protocol, OpenRGB and GUI↔agent IPC.
- `python -m compileall -q pc_app` then `pio run -e esp32s3` on CI.

## Bench-only electrical validation (NOT completed by these tests)

1. Oscilloscope: high-side switch output voltage at reset, ESP unpowered, +12 V brownout; must remain fail-safe ON for an active PC cooling setup.
2. Confirm `FAN_OUTPUT_INVERTED` matches the *installed* driver; verify 100% duty at physical output before enabling any partial power PWM.
3. Sweep 80–1000 Hz (start at 250 Hz) using chosen switch, all fan loads, initial and restart current, thermal limits and any audible motor whine.
4. 3-pin TACH: measure on/off duty RPM validity and noise, then enable `FAN_DC_TACH_VALIDATED` only if genuinely reliable.
5. 2-pin: recognize there is no RPM/current/stall feedback; real detection needs extra hardware and pins. Test blocked fan with a rated fuse/protection.
6. Cold boot, UART disconnect, USB reset, missing LHM sensors, Wi-Fi loss, MQTT broker failure and unexpected power loss; all cooling channels must independently become safe.
7. 8 ARGB outputs × max pixels; measure USB throughput, control-loop worst latency and power budget, and verify no fan-update starvation.
8. Test Home Assistant discovery and live fan commands with an actual broker, including retained-command replays, wrong credentials, network resets and multiple boards.
9. Windows headless agent and GUI run simultaneously; one USB owner, GUI starts without resetting board, and control continues after GUI closes.
