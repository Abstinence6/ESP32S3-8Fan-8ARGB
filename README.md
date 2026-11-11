# ESP32-S3 8-Fan / 8-ARGB Controller

Starter firmware for **8 independent 2/3/4-pin PC fans (3-pin default)** and **8 independent 5 V addressable RGB strips** on an **ESP32-S3**. Built with **PlatformIO, Arduino-ESP32 2.0.17, and Adafruit NeoPixel**.

**Status:** starter/reference code, not yet tested on physical hardware. The sample pin assignment targets ESP32-S3-DevKitC-1 and MUST be checked against your actual ESP32-S3 module and PCB before powering peripherals.

## Features

- 8 independent **25 kHz / 8-bit PWM** channels via LEDC, 0..100%.
- 8 TACH inputs, **RPM** measured using falling-edge interrupts (default 2 pulses/revolution).
- 8 independent WS2812B / SK6812-RGB (3-channel) LED data outputs with OpenRGB E1.31 pixel streaming (via Windows companion).
- Independent static colors / brightness / rainbow animation, plus off.
- Non-blocking ASCII command + binary ARGB parsing over Serial at **921600 baud**.
- Modular C++ code, host-side smoke tests and a GitHub Actions PlatformIO build.

## Quick start

1. Open the folder in VS Code with the PlatformIO extension.
2. Review `include/BoardConfig.h` and `docs/WIRING.md` before connecting anything.
3. Adjust `kArgbLedCounts[]` (default 30 on every output).
4. Build: `pio run -e esp32s3`.
5. Optional host smoke test: `./test/native/run.sh` (Linux/macOS or WSL with g++).
6. Upload: `pio run -e esp32s3 -t upload`.
7. Open serial monitor: `pio device monitor -b 921600`.

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
- The firmware stores fan calibration and PWM-temperature curves in NVS. The companion UI supplies PC temperatures; ESP-S3 does not independently measure CPU/GPU temperature. Wi-Fi RGB integration is optional. Power switching for 2/3-pin fans requires the user-supplied smart key and physical DC/PWM jumper.

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

## v2: Calibration, temperature curves and Windows control app

The desktop app is in [`pc_app`](pc_app/README.md) with a five-point **interactive PWM-vs-temperature graph**. It reads **all available** Temperature sensors from LibreHardwareMonitor's local `data.json` endpoint, allows assigning one sensor or maximum of all temperatures to each of the eight fans, sends values over USB serial, and controls ARGB color/rainbow/brightness. An offline Windows `.exe` is built by GitHub Actions (`Windows desktop application` workflow).

The ESP32-S3 firmware now has **21-point independent PWM/RPM calibration per fan** (0%, 5%, ..., 100%) and five-point temperature PWM curves stored in **Preferences/NVS flash**. Startup defaults to 100% fan PWM, and any AUTO-mode channel without a temperature update for **10 seconds** returns to 100% duty. Pressing CAL in the desktop app starts a sweep *on the ESP32*; it keeps running even when the GUI temporarily stops responding. The ESP32 only saves data on successful calibration or explicit curve save, not continuously.

**Important:** the computer must be running LibreHardwareMonitor and the GUI to feed CPU/GPU temperatures; the ESP32 does *not* measure CPU/GPU temperature by itself. Without temperature updates, the fans run at 100% for safety. Manual overrides are also subject to the thermal watchdog in v4. This is a reference firmware requiring real hardware tests before permanent unattended use.

For full details, see [`docs/PROTOCOL.md`](docs/PROTOCOL.md) and [`pc_app/README.md`](pc_app/README.md).


## v3: AVG of sensor groups and OpenRGB E1.31

**Temperature groups:** each fan can use a single sensor, MAX of all sensors, **AVG of an explicitly chosen sensor group**, or MAX of that group. Sensor membership is configured in the Windows desktop GUI and persisted with QSettings; the PWM-temperature curve itself remains on ESP32 NVS. Missing group members prevent new temperature updates, activating the ESP fan fail-safe after 10 seconds.

**External ARGB:** OpenRGB (or xLights/other E1.31 transmitters) streams **per-LED RGB** data through 8 manual E1.31 devices (universe 1..8), received by the Windows program at **127.0.0.1:5568** and forwarded over the **same USB COM connection** as the fan commands at 921600 baud. ESP verifies binary packets using CRC-16 and renders each strip independently. This is *not* OpenRGB automatic USB detection, and the PC app must run for RGB streaming. Native built-in effects (solid, rainbow) remain available for offline/manual use.

[OpenRGB configuration, limits and troubleshooting](docs/OPENRGB.md). The protocol is documented in [docs/PROTOCOL.md](docs/PROTOCOL.md); GUI setup is in [pc_app/README.md](pc_app/README.md). **Update both PC app and firmware** when upgrading to v3 due to changed baud rate.

## v4: 3-pin main fan mode, universal fan connector

All eight fan outputs share one **PWM GPIO + one TACH GPIO per fan**, with eight ARGB data GPIOs (24 total); no MCP23017 or additional I/O expanders. Fresh NVS profiles use **3-pin mode**. The jumper on each fan channel selects **DC power switching** (2/3-pin via the intelligent smart key) or **steady 12 V + PWM on contact 4** (4-pin). The software `TYPE n 2|3|4` must match the jumper; it cannot operate the jumper. **Automatic type detection is unavailable and TYPE AUTO is rejected**, since TACH alone cannot prove 2/3/4 contacts.

**Safety interlock:** `FAN_DC_PWM_VALIDATED=0` by default; until the selected smart switch is proven suitable for 25 kHz power PWM and a hardware fail-safe ON state, 2/3-pin channels stay at **100%**. Enabling PWM control requires an explicit firmware rebuild after bench testing. See [docs/FAN_MODES.md](docs/FAN_MODES.md) and [docs/PCB_NEXT.md](docs/PCB_NEXT.md).

## v4 modules added

- Smarter calibration with reverse sweep and safe temperature/watchdog abort, PID RPM option and automatic stall-retry logging.
- Secondary temperature curve, weighted selected-sensor averages, CSV trends and named PC cooling profiles.
- Optional Wi-Fi E1.31/DDP, ARGB brightness/current-budget limiter, editable LED count/reversal and 3-second external frame timeout.
- A Windows `--headless` user-logon agent (not a boot-time service) that owns the USB COM port.
- Provisional 2/3/4-pin fan modes with manual jumper selection; no GPIO expander or auto-detection. The 3-pin DC stage remains hardware-unverified and is safety-locked to full power by default.

Docs: [Fan modes](docs/FAN_MODES.md), [future PCB](docs/PCB_NEXT.md), [Windows app](pc_app/README.md).

### v4.1: no-key safety diagnostics

The no-key build retains `FAN_DC_PWM_VALIDATED=0` and the 3-pin default. Commands `HEALTH` / `HEALTH 1` expose read-only fan state, `TACH=seen|unseen|na`, thermal freshness, and whether DC power PWM is validated. `ALLFAN` is now all-or-nothing: invalid fan duties return an error without changing any channel. Stall monitoring remains active after PC sensor loss if the TACH was previously confirmed. The desktop GUI includes **Діагностика 8 вентиляторів** and **Журнал аварій** buttons. No power-key chip is selected and **no new hardware is required to build or run these software diagnostics**.

### v4.2: Fan TACH observation without a power key

`SELFTEST` collects falling TACH edges for 5 seconds on all eight fans and reports `OK`, `NO_TACH`, `NA` (2-pin) or `INCONCLUSIVE` if the operating point changed. The command **does not change PWM duty or fan operating modes**. A **Тест TACH (5 с)** button is available in the Windows GUI. This is useful for validating wiring, while power PWM on 2/3-pin fans remains locked at 100% until the actual smart key is selected and bench-qualified. See [`docs/PROTOCOL.md`](docs/PROTOCOL.md).
