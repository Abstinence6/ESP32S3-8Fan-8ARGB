# Optional PC PWR_SW / power-state control

The ESP32-S3 controller can optionally emulate the case power button without
blocking fan PWM, temperature fail-safe, MQTT, OpenRGB or serial streaming.

**OFF BY DEFAULT.** GPIO1 is already ARGB channel 1 and must not be reused.
There are no universal safe spare pins across ESP32-S3 board/module variants.
Choose **two physically available, unallocated GPIOs** after checking your PCB
and the module's flash/PSRAM, USB, strapping and boot pin assignments.

Add (example only, replace with electrically checked pins) to the
`platformio.ini` environment build flags:

```ini
build_flags =
    -D PC_POWER_ENABLED=1
    -D PC_POWER_GPIO=<verified_free_output_gpio>
    -D PC_SENSE_GPIO=<verified_free_input_gpio>
```

Build-time checks reject the default unassigned pins, identical pins,
out-of-range pins, GPIOs already allocated to fan PWM/TACH or ARGB, USB pins,
strap pins, UART0 pins and flash/PSRAM-reserved pins. GPIO33/34 can also be occupied on some\nmodules; they are allowed by the compile-time guard only for a hardware\nconfiguration that has explicitly confirmed these pins are free.\nGPIO selections must
still be verified against the actual board schematic.

## Electrical connections

- **PWR_SW**: `PC_POWER_GPIO` uses **3.3 V open-drain**. LOW means a button
  press; HIGH means high impedance (release). Prefer an **isolated optocoupler**
  or correctly designed open-collector transistor connected **in parallel**
  with the case PWR_SW contacts. Do **not** inject 3.3 V into the motherboard
  header, and do not assume the motherboard PWR_SW voltage is GPIO-safe.
  When directly wiring, verify maximum voltage, pull-ups and common GND.
- **Sense**: `PC_SENSE_GPIO` must receive a clean **0–3.3 V digital signal**
  through suitable isolation/level translation from PLED or another valid
  power-state indicator. **Never connect 5 V or 12 V PLED directly** to ESP.
  The input needs external bias to a known OFF level.
- ESP32 must have an independent standby supply that remains powered
  whenever motherboard standby voltage is present. Use a suitable protected
  power source; do not count on a USB port that shuts off with the PC.
- If power-state sensing is unavailable, requests remain disabled.
  On boot the open-drain output is released; no simulated click occurs.
  A physical external pull-up/driver design must prevent a false press
  before firmware starts.

## Serial commands (921600 baud)

- `PC STATUS`: read `PC disabled|unknown|on|off BUSY=0|1`.
- `PC ON`: 300 ms simulated press only if sensed OFF.
- `PC OFF`: 300 ms simulated press only if sensed ON.
- `PC FORCE`: 6 s hold only if sensed ON.
- Requests are rejected when disabled, state unknown, already busy, or
  for at least 1 second after the previous press.
- Power-state filtering: ON after 100 ms, OFF after 2 seconds.
  This is *status*, not a guarantee the motherboard accepted the command.
- The feature never rewrites fan settings, resets the ESP or issues an
  automatic power command on boot, COM connect, Wi-Fi loss or API outage.

This is a companion to the user's ESPHome example adapted for the **ESP32-S3
firmware**, not an ESPHome configuration for the ESP32-C3. It is accessible through Serial, the Windows companion and, when enabled,
MQTT/Home Assistant Discovery. The MQTT bridge publishes a PC Power binary
sensor and three **momentary buttons** (On, Off, Force Off) with guarded
commands via `<device-base-topic>/pc/set`. MQTT must be explicitly configured
on a trusted local broker; do not publish retained commands to that topic.
The Power On/Off commands are guarded by the sensed current state.
Avoid exposing the MQTT broker to untrusted network clients.
