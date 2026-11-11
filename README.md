# ESP32-S3 8-Fan / 8-ARGB Controller

Starter firmware for **8 independent 4-wire PWM PC fans** and **8 independent 5 V addressable RGB strips** on an **ESP32-S3**. Built with **PlatformIO, Arduino-ESP32 2.0.17, and Adafruit NeoPixel**.

**Status:** starter/reference code, not yet tested on physical hardware. The sample pin assignment targets ESP32-S3-DevKitC-1 and MUST be checked against your actual ESP32-S3 module and PCB before powering peripherals.

## Features

- 8 independent **25 kHz / 8-bit PWM** channels via LEDC, 0..100%.
- 8 TACH inputs, **RPM** measured using falling-edge interrupts (default 2 pulses/revolution).
- 8 independent WS2812B / SK6812-RGB (3-channel) LED data outputs.
- Independent static colors / brightness / rainbow animation, plus off.
- Non-blocking command parsing over Serial at **115200 baud**.
- Modular C++ code, host-side smoke tests and a GitHub Actions PlatformIO build.

## Quick start

1. Open the folder in VS Code with the PlatformIO extension.
2. Review `include/BoardConfig.h` and `docs/WIRING.md` before connecting anything.
3. Adjust `kArgbLedCounts[]` (default 30 on every output).
4. Build: `pio run -e esp32s3`.
5. Optional host smoke test: `./test/native/run.sh` (Linux/macOS or WSL with g++).
6. Upload: `pio run -e esp32s3 -t upload`.
7. Open serial monitor: `pio device monitor -b 115200`.

The default `Serial` uses the USB-to-UART interface. If using the ESP32-S3 native USB port, see the commented USB CDC flags in `platformio.ini`.

## Serial commands

Channel IDs are **1..8** (not zero-based).

```text
HELP
STATUS
FAN 1 45
FAN 8 100
ALLFAN 70
LED 1 255 0 0
LED 2 0 0 255
ALLLED 255 180 40
BRIGHT 2 80
RAINBOW 2
OFF 2
ALLOFF
```

`OFF` / `ALLOFF` control **only the ARGB outputs**; they never stop fans.

## Example pin map

| # | PWM fan | TACH fan | ARGB data | Default LED count |
|---|---:|---:|---:|---:|
| 1 | GPIO4 | GPIO8  | GPIO1  | 30 |
| 2 | GPIO5 | GPIO9  | GPIO2  | 30 |
| 3 | GPIO6 | GPIO10 | GPIO38 | 30 |
| 4 | GPIO7 | GPIO11 | GPIO39 | 30 |
| 5 | GPIO15 | GPIO12 | GPIO40 | 30 |
| 6 | GPIO16 | GPIO13 | GPIO41 | 30 |
| 7 | GPIO17 | GPIO14 | GPIO42 | 30 |
| 8 | GPIO18 | GPIO21 | GPIO47 | 30 |

**Caution:** GPIO38 is also connected to an on-board RGB LED on some DevKitC-1 v1.1 boards. The pin map is only an example, not a ready-to-wire production PCB. GPIO35-37 can be occupied by octal PSRAM, GPIO19/20 by native USB, and GPIO0/3/45/46 are boot strap pins.

## Hardware rules (required)

- **Never feed 5 V or 12 V to an ESP32-S3 GPIO.** Grounds must be common.
- Each PC 4-pin fan's PWM input should be driven by a **5 V tolerant open-collector/open-drain stage** (e.g. NPN or NMOS). The default software configuration assumes this stage INVERTS the GPIO logic. The fan's own PWM pull-up sets the high level. Do not add a 12 V pull-up to this signal.
- TACH is typically an open-collector output: add an **external ~10 kOhm pull-up to 3.3 V** for each input, not to 5/12 V.
- Supply fans from their own correctly rated **12 V rail** (or the voltage required by the fans). Supply ARGB from a properly rated **5 V PSU**, NOT the ESP32 5 V pin.
- Use a **74AHCT125 / 74AHCT245 level shifter at 5 V** for the 3.3 V ARGB data signals; series resistors and suitable PSU decoupling are strongly recommended.
- A WS2812B RGB pixel can draw up to **~60 mA at full white**. At 8 x 30 pixels that can reach **~14.4 A @ 5 V**, excluding controller losses. Size PSU, cabling and injection accordingly.
- PWM=0% does NOT guarantee that all 4-pin fan models fully stop. Power-off requires a separate switched power stage if needed. Startup defaults to 100% fan PWM (fan high speed) and ARGB off.

See `docs/WIRING.md` for details.

## Implementation notes

- ESP32-S3 has 8 LEDC channels, used here for independent fans.
- ESP32-S3 has only 4 RMT TX channels, but **Adafruit NeoPixel show() calls execute one by one and release the RMT channel** on Arduino-ESP32 2.x, so 8 independent strips are possible (not simultaneously updated).
- Rainbow effects update at most every 40 ms; actual FPS depends on the sum of all strip lengths and RMT transfer times.
- RPM is averaged over 1 s; tach signals need a suitable pull-up and clean edges.
- Firmware currently has no persistent settings, Wi-Fi, UI, fan curve, thermal sensors, or hardware power control. These are straightforward next modules.

## Structure

```text
include/BoardConfig.h      - pins, counts, timing and electrical logic
include/FanController.h    - fan API and tachometer state
include/ArgbController.h   - ARGB API and modes
include/SerialConsole.h   - serial command API
src/                    - implementation and main loop
docs/WIRING.md          - wiring and electrical safety
.github/workflows/      - CI PlatformIO build and smoke tests
test/native/            - native g++ smoke tests with hardware mocks
```
