# Serial protocol v2 (115200, ASCII, LF-terminated)

All commands and responses are single-line ASCII, except for multiple-line status/calibration result streams. Fan channel numbers are **1..8**. Send only one command per line, terminating with `\n`. Other MCU replies may arrive asynchronously while a calibration is running.

## Commands

| Command | Example | Effect |
|---|---|---|
| `PING` | `PING` | Response `PONG 2` |
| `STATUS` | `STATUS` | Returns 8 `CH ...` lines |
| `TEMP <fan> <deciC>` | `TEMP 1 487` | Update fan 1's measured temperature to 48.7 °C, refreshing 10 s heartbeat |
| `CURVE? <fan>` | `CURVE? 1` | Read 5 curve points from flash |
| `CURVE <fan> <temp pwm> ... x5` | `CURVE 1 20 30 30 40 45 60 60 80 75 100` | Validate and store an ordered five-point curve in NVS |
| `CAL START <fan>` | `CAL START 3` | Start one asynchronous 21-step calibration |
| `CAL CANCEL` | `CAL CANCEL` | Stop current calibration without saving |
| `CAL GET <fan>` | `CAL GET 3` | Read last completed calibration stored in NVS |
| `AUTO <fan>` | `AUTO 3` | Return fan to automatic curve mode |
| `ALLAUTO` | `ALLAUTO` | Automatic mode on all 8 fans |
| `FAN <fan> <percent>` | `FAN 3 60` | Manual PWM override (ignores temp watchdog) |
| `ALLFAN <percent>` | `ALLFAN 100` | Manual override on all channels |
| `LED`, `ALLLED`, `OFF`, `ALLOFF`, `RAINBOW`, `BRIGHT` | `LED 3 255 0 0` | ARGB commands (unchanged) |

Temperatures must be integers from 0 to 1250 (0.0–125.0 °C). Each curve has five temperature points in 0–125 °C, strictly ascending, and PWM 0–100%, nondecreasing. NVS is written only on successful `CURVE` or completed calibration, never by streaming temperatures or `STATUS`.

## Replies

- `OK`, `OK CURVE_SAVED`, or `ERR ...` for a command.
- `CH 1 FAN=55% RPM=1270 TEMP=487 MODE=auto SENSOR=ok` — current fan state, temperature in deci-Celsius. `SENSOR=stale` means fail-safe PWM=100% in auto mode; `MODE=manual` intentionally overrides temperature control.
- `CURVE 1 20 30 30 40 45 60 60 80 75 100` — stored curve.
- `CAL_STARTED 3` — calibration started.
- `CAL_POINT 3 5 400` — current calibration's step 5% PWM -> 400 RPM.
- `CAL_SAVED 3` — complete calibration was written to ESP32 NVS.
- `CAL_ERROR 3 NO_TACH` or `CAL_ERROR 3 STORAGE` — no calibration saved.
- `CAL_CANCELLED 3` — stop without saving.
- `CAL_RESULT 3 5 400` — saved calibration samples emitted by `CAL GET 3` (21 lines), followed by `CAL_END 3`.

The computer collects temperatures using LibreHardwareMonitor (or another user-space provider) and streams selected values every ~2 seconds. A channel that receives no fresh temperature for >10 seconds automatically goes to 100% duty. PC sensor selection is saved on the PC, curves and calibration are saved on the ESP.

## Calibration algorithm

1. Warm up the selected fan at 100% PWM for 1.2 s.
2. Sweep from 0 to 100% at 5% intervals (21 points), holding each point 3.5 s to allow RPM to settle and measuring RPM with the TACH input.
3. At each point, emit `CAL_POINT` and keep the measurement in RAM.
4. After the final sample, reject if **all** RPM values are zero; otherwise write one calibrated profile to NVS and emit `CAL_SAVED`.
5. Other fan channels continue in their previous operating modes. The calibrated channel returns to its previous Manual or Automatic mode.

The calibration is an empirical duty-to-RPM table, not a closed-loop RPM controller yet. A fitted acoustic curve and stall threshold can be added later. RPM accuracy depends on the correct pulses-per-revolution setting, the TACH wiring, and settling time.
