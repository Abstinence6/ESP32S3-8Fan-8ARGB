# Serial protocol v5 (921600 baud, ASCII control + binary ARGB)

## v8 — PC-managed ESP32 settings, USB protocol v5

Windows PC GUI is the supported provisioning interface. It reads stored
Wi-Fi/MQTT/ARGB config, writes validated changes and waits for firmware
acknowledgement plus readback. No secret is included in status output.

- `WIFI CONFIG?`: `WIFI_CONFIG ENABLED=<0|1> CONNECTED=<0|1> SSID_HEX=<hex|-> PASSWORD_SET=<0|1> IP=<ip|->`.
- `WIFI SETHEX <ssidHex> <passwordHex|KEEP|->`: UTF-8 bytes encoded in HEX.
  `KEEP` only for same SSID; `-` is an explicitly open Wi-Fi network.
- `MQTT CONFIG?`: `MQTT_CONFIG ENABLED=... CONNECTED=... HOST_HEX=... PORT=... USER_HEX=... AUTH=... DISCOVERY=... TOPIC=...`.
- `MQTT BROKER <host> <port>` saves broker without implicitly enabling MQTT.
  `MQTT AUTHHEX <userHex|-> <passwordHex|->` saves credentials.
  `MQTT HA ON|OFF` persists Home Assistant Discovery selection.
  `MQTT ON|OFF` and `MQTT CLEAR` explicitly activate or erase the broker.
- `STRIPCFG? <1..8>`: returns `STRIPCFG CH=1 LEDS=... REVERSE=... BRIGHT=...`.
  Existing `CONFIG <ch>`, `ARGBSTATUS`, `HTLIST?`, `HTMAP?` and
  `HTMODE?` provide the remaining editable settings.

Wire HEX is delimiter-safe but **not encryption**; USB must be trusted and
unencrypted TCP MQTT remains for trusted LAN only. Power-critical GPIO and
DC safety interlocks are compile-time/physical and intentionally not
writable by arbitrary Windows commands. See [PC_CONFIGURATION.md](PC_CONFIGURATION.md).
All regular commands and responses are single-line ASCII, except for multiple-line status/calibration result streams. ARGB pixel frames use binary packets on the **same** serial connection. Fan channel numbers are **1..8**. Send only one command per line, terminating with `\n`. Other MCU replies may arrive asynchronously while a calibration is running.

## Commands

| Command | Example | Effect |
|---|---|---|
| `PING` | `PING` | Response `PONG 2` |
| `LEDS` | `LEDS` | Response `LEDCOUNTS <n1> ... <n8>` for physical ARGB pixel counts |
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

## E1.31 bridge and USB binary RGB frames (v3)

See [OpenRGB setup](OPENRGB.md). OpenRGB transmits eight E1.31 universes (UDP 5568) to the desktop GUI, one universe per output. The GUI reads RGB data from sACN DMX channels 1–510 (DMX start code 0) and sends it to the ESP with a compact binary frame. **Thermal ASCII control remains active on the same serial port.**

Wire bytes (little-endian counts/CRC):

```
A5 5A | output 1..8 | count_lo count_hi | R0 G0 B0 R1 G1 B1 ... | crc_lo crc_hi
```

`count` is **1–170 RGB pixels**, no more than the `kArgbLedCounts` for the output. The CRC is **CRC-16/CCITT-FALSE** (poly 0x1021, init 0xFFFF), calculated over the output byte, 2 count bytes, and RGB bytes only (excluding sync marker and CRC bytes). The ESP drops an invalid CRC packet. It also safely discards oversized/incomplete frames; unfinished binary frames expire after 300 ms idle. The USB baud rate is **921600** for RGB streaming. On `LEDS` the ESP returns eight lengths, allowing the GUI to crop frames to the exact physical strip lengths; it refuses to stream until counts are known.

Example: output 3, two RGB pixels `(255,0,0)` and `(0,255,0)`:

```
A5 5A 03 02 00 FF 00 00 00 FF 00 D0 ED
```

The ESP displays incoming RGB values in **External** mode and automatically uses brightness 255 on first external frame. External packets affect only lighting, never fans. Legacy `LED`, `RAINBOW`, `OFF` commands remain available.

**Important compatibility:** v3 desktop and firmware must be updated together; older serial applications running at 115200 baud will not communicate correctly.

## Universal 2/3/4-pin fan protocol (v4)

- `TYPE? <ch>` returns `TYPE <ch> SET=<2|3|4> DETECTED=255 RPM_OK=<0|1> DC_HW=<0|1>` (no connector sensing; DC_HW is compile-time validation, not measured presence).
- `TYPE <ch> 2|3|4` saves a user-confirmed connector mode; 3-pin is default on fresh NVS. `TYPE <ch> AUTO` is rejected (no hardware detector). 2/3-pin power PWM is held at 100% until the smart key is verified and `FAN_DC_PWM_VALIDATED=1` is built into firmware.
- `CONFIG <ch>` now contains `TYPE` and `DETECTED`; `STATUS` adds `TYPE` and `RPM_OK`.
- Type changes invalidate RPM calibration for that channel. A 2-pin fan has no TACH: RPM, PID and tach-based stall detection are unavailable.

See [FAN_MODES.md](FAN_MODES.md) for physical jumper wiring, frequency validation and limitations.

## v4.1: Operational safety and read-only diagnostics

- `ALLFAN <pwm>` is now **all-or-nothing**. It checks that every one of the eight channels can apply the requested duty before changing any channel; with the default `FAN_DC_PWM_VALIDATED=0`, `ALLFAN 35` returns `ERR fan control blocked` and changes nothing. `ALLFAN 100` remains permitted. A single disallowed `FAN n p` is rejected with the same error and does not enter Manual mode.
- `ALLAUTO` is also rejected while a calibration is running, preventing a partial mode change.
- `HEALTH` reports the state of all eight channels, terminated by `HEALTH_END`. `HEALTH <ch>` reports one channel (also terminated by `HEALTH_END`) without changing PWM, modes, GPIO, fan type or temperature settings.
- Health lines have the form `HEALTH 1 TYPE=3 DETECTED=255 PWM=100 RPM=0 TACH=unseen SENSOR=stale FAULT=0 DC_READY=0 MODE=auto`.
- `TACH=seen` means *some real tach pulses have been observed since this boot or type change*, **not** that the fan is currently rotating. `TACH=unseen` can mean a missing/broken tach connection, a stopped fan, or a not-yet-spinning fan. `TACH=na` is expected for 2-pin. `TYPE` is the user-selected logical mode; `DETECTED=255` remains unknown because no identification hardware exists. `DC_READY=0` means the DC-power PWM safety interlock is active.
- After TACH has actually been seen, a later tach failure can trigger stall recovery even if the PC stops providing temperatures. At that point the controller already commands 100% duty, but it still records a stall event and attempts a safe fan restart. To avoid false alarms on unconnected channels, stall detection is not armed before the first genuine TACH sample. For 2-pin, use smart-key fault telemetry in future hardware; no TACH means no RPM/stall feedback.
- In every mode, no recent temperature update means a fail-safe request of 100% duty. **Without a validated key and physical fail-safe circuitry, software cannot guarantee actual fan power when the MCU is resetting/unpowered.**

## v5: 2/3-pin-only supply drive and MQTT

**Supersedes older 4-pin sections above.** `TYPE <ch> 2|3` is the only valid
set command; `TYPE 4` and `TYPE AUTO` are rejected. The supply PWM reference
frequency is 250 Hz, **not** the old 4-pin 25 kHz pin-4 PWM signal.
`HEALTH` now includes `TACH_VALID=0|1` in addition to the historical
`TACH=seen|unseen|na` latch. A connected 3-pin fan with untrusted pulse timing
has `TACH_VALID=0` and cannot drive RPM PID; 2-pin always reports no RPM.

NVS profile format v4 migrates old v1/v2/v3 profiles by retaining the
five-point thermal curves, but dropping RPM calibration and PID settings
because PWM-driven motor behavior depends on the changed power hardware.

`MQTT?` prints current broker and state. `MQTT HOST <host> <1..65535>`,
`MQTT AUTH <user> <password>`, `MQTT AUTH CLEAR`, `MQTT ON|OFF` manage optional
local-broker MQTT. See [MQTT.md](MQTT.md) for topic and safety details.
