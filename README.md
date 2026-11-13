## ESP32-S3 settings are managed from Windows (v8)

Open the **ESP32** page in `FanARGBControl.exe` to read, change, save
and verify Wi-Fi (including SSIDs/passwords with spaces), MQTT broker/login,
Home Assistant Discovery, 8 ARGB strips, and the fan's TACH/thermal limits.
The controller, not Windows, stores persistent hardware settings in NVS.
Secret fields are masked and do not appear in logs. All configuration
changes require USB and firmware v8+; no Serial Monitor is needed.

See [PC configuration](docs/PC_CONFIGURATION.md). GPIO/power MOSFET
hardware and optional DC PWM/DS18B20/PWR_SW compiler flags remain
hardware-qualified and cannot be changed arbitrarily from the PC.

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
| 1 | GPIO21 | GPIO47 | GPIO48 | 30 |
| 2 | GPIO35 | GPIO36 | GPIO37 | 30 |
| 3 | GPIO39 | GPIO40 | GPIO41 | 30 |
| 4 | GPIO42 | GPIO2  | GPIO1  | 30 |
| 5 | GPIO6  | GPIO5  | GPIO4  | 30 |
| 6 | GPIO16 | GPIO15 | GPIO7  | 30 |
| 7 | GPIO10 | GPIO9  | GPIO46 | 30 |
| 8 | GPIO14 | GPIO13 | GPIO12 | 30 |

**This is the user's wiring, not the old DevKitC reference pinout.** GPIO35/36/37 are occupied on ESP32-S3 variants with **Octal PSRAM/Flash**, so this binary is **not safe for those variants**; reassign these three signals to free pins on the physical PCB. GPIO46 for ARGB7 is a **strapping pin**: it can be an output after startup, but the connected ARGB driver must not assert a conflicting level during reset/firmware download. GPIO48 may be shared with an onboard RGB LED on specific DevKit boards. Check the actual module and reset/bootstrap circuitry. The default build leaves `PC_POWER_ENABLED=0` and `FAN_DC_PWM_VALIDATED=0` (DC fans held at 100%). Do not enable either feature without the required hardware checks.

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

The desktop app is in [`pc_app`](pc_app/README.md) with a five-point **interactive PWM-vs-temperature graph**. It reads **available CPU/GPU/SSD temperature sensors locally** using a bundled NWinfo CLI (built-in CPU/GPU/SMART providers; no LHM application or web server), allows assigning one sensor or maximum of all temperatures to each of the eight fans, sends values over USB serial, and controls ARGB color/rainbow/brightness. An offline Windows `.exe` is built by GitHub Actions (`Windows desktop application` workflow).

The ESP32-S3 firmware now has **21-point independent PWM/RPM calibration per fan** (0%, 5%, ..., 100%) and five-point temperature PWM curves stored in **Preferences/NVS flash**. Startup defaults to 100% fan PWM, and any AUTO-mode channel without a temperature update for **10 seconds** returns to 100% duty. Pressing CAL in the desktop app starts a sweep *on the ESP32*; it keeps running even when the GUI temporarily stops responding. The ESP32 only saves data on successful calibration or explicit curve save, not continuously.

**Important:** the bundled NWinfo sensor engine and the GUI (or background agent) must be running to feed available CPU/GPU temperatures; the ESP32 does *not* measure CPU/GPU temperature by itself. Access to low-level CPU sensors may require approved Windows driver permissions. Without temperature updates, the fans run at 100% for safety. Manual overrides are also subject to the thermal watchdog in v4. This is a reference firmware requiring real hardware tests before permanent unattended use.

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

### v4.2: TACH observation

`SELFTEST` is a non-invasive 5-second counter check; GUI button also available.

## v5: 2/3-pin DC drive, Home Assistant / MQTT and Windows COM sharing

**This section supersedes earlier 2/3/4-pin text in this README.** The firmware
supports **only 2-pin and 3-pin fans**. Four-wire fan control has been removed.
DC supply PWM uses a **250 Hz reference** instead of 25 kHz, with firmware
interlock **OFF by default** (`FAN_DC_PWM_VALIDATED=0`): all fans are demanded
at 100% pending electrical validation of the high-side power circuit and
hardware fail-ON at MCU reset. `TYPE 4` is rejected; new v5 NVS migration keeps
temperature curves and resets obsolete RPM calibration/PID state.

- TACH: current-window plausibility validation (`TACH_VALID`) prevents stale
  or obviously noisy pulse counts from feeding PID or RPM calibration.
- ARGB: commands only enqueue changes; at most one strip is shown per ~6 ms
  pass to avoid an uninterrupted eight-strip transfer starving fan control.
- Windows: a headless agent owns COM, and the GUI connects to its **localhost
  serial proxy**, falling back to direct COM if no agent owns the port.
- **MQTT with Home Assistant Discovery** is built into ESP32 over Wi-Fi:
  8 fan controls, 8 RPM sensors and 8 RGB light controls; no Windows host
  required for these functions. Configure through serial `MQTT HOST`,
  `MQTT AUTH`, `MQTT ON` or the GUI button. MQTT control cannot bypass
  the DC power safety interlock.

Setup and security: [docs/MQTT.md](docs/MQTT.md) · hardware constraints:
[docs/FAN_MODES.md](docs/FAN_MODES.md), [docs/PCB_NEXT.md](docs/PCB_NEXT.md).

**Hardware qualification is pending.** Host tests validate software guards,
not MOSFET switching, motor tachometer integrity, or PC cooling reliability.

## Configuration presets and OpenRGB setup helper

The Windows GUI now provides **full configuration presets** combining one of
**Silent / Balanced / Performance** cooling curves with **Off / Static warm /
Static cool / Rainbow / OpenRGB** lighting scenes across all eight outputs.
Profiles can be exported as versioned JSON and imported after validation.
Changes are sent to the device only after explicit confirmation. Existing
fan-type selection, DC PWM safety interlock, watchdog, and calibrations are
not overwritten by these presets.

The **OpenRGB E1.31 settings** button generates a JSON *reference* of all eight
zones, using the real LED counts from `LEDS`. It helps configure the existing
OpenRGB E1.31 Devices manually for local USB bridging or direct ESP Wi-Fi;
it is not a native OpenRGB profile import or USB auto-discovery.
See [configuration preset documentation](docs/CONFIG_PRESETS.md).

## v7: Native OpenRGB, multi-DS18B20, safer USB, TACH and history

The v7 application adds an optional localhost OpenRGB SDK controller with
8 independently addressable zones (connect OpenRGB to `127.0.0.1:6743`),
conservative USB identity reconnect, priority Serial writer, multiple DS18B20
sensors with 64-bit ROM bindings, passive TACH fault alerts, 30-day SQLite
history, and stronger ESP32-S3 firmware file verification.

See [features](docs/FEATURES_V7.md) and
[hardware fail-ON checklist](docs/V7_HARDWARE_SAFETY.md).

## v6: Integrated automation, diagnostics, firmware update and DS18B20

The Windows GUI adds ARGB Studio effects, CPU/GPU-specific smart cooling,
temperature smoothing, Gaming/Work/Night automatic profiles, separate
hardware sensor health, performance graphs, tray mode, an opt-in **elevated
Windows logon task via UAC**, read-only fan diagnostics, configuration
backup/restore and a guided (safe-bench-only) ESP32 firmware updater.

An **optional DS18B20** connected directly to a spare verified ESP32-S3
GPIO can supply LOCAL or BACKUP temperatures without Windows. It is
**disabled in the standard binary**, until the physical pin and 3.3 V
wiring have been verified. The new `HTEMP?` and `HTMODE` commands are
available in the v6 firmware; the Windows GUI displays their state.

[All v6 features and safety notes](docs/FEATURES_V6.md) ·
[DS18B20 wiring instructions](docs/HARDWARE_TEMPERATURE.md).

## Optional PC PWR_SW integration

The ESP32-S3 can optionally control a PC case power switch using a **separate
open-drain output** and **3.3 V-safe sensed PC power indicator**. It adds
nonblocking 300 ms On/Off and 6-second Force Off presses, with ON/OFF
state gating, startup release and debounce. **Disabled by default** until
free GPIOs and a safe electrical interface are explicitly configured.
GPIO1 is occupied by ARGB1, and the ESP32-C3 ESPHome pin map must NOT
be copied to this ESP32-S3 firmware. Commands are available through Serial
(`PC STATUS|ON|OFF|FORCE`), the Windows companion and MQTT/Home Assistant
Discovery (when enabled). Full wiring, safeguards and compile-time GPIO
configuration: [docs/PC_POWER.md](docs/PC_POWER.md).
