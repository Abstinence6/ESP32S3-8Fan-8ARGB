# External hardware temperature sensor: DS18B20 (1-Wire)

Optional: ESP32-S3 can read a **physical DS18B20** without Windows/NWinfo
and use it as a local or backup input for any of its eight fan curves.

## Electrical safety and enablement

Disabled by default. Select a physically **unallocated, verified 3.3 V GPIO**
of your actual ESP32-S3 module/PCB. Example **GPIO18, only if really free**:

```ini
build_flags =
  -D HARDWARE_TEMP_ENABLED=1
  -D HARDWARE_TEMP_GPIO=18
```

Wiring (normal three-wire supply, NOT parasite power):

| DS18B20 | ESP32-S3 / supply |
|---|---|
| VDD | 3.3 V |
| GND | GND |
| DQ | chosen GPIO + **4.7 kOhm** pull-up from DQ to 3.3 V |

Do NOT connect DS18B20 data to 5 V; do NOT reuse GPIOs occupied by
PWM/TACH/ARGB, USB, bootstrapping, flash/PSRAM or PC Power. The firmware
checks configured pin collisions at compile time, but cannot verify the
physical board's additional wiring. Max recommended cabling depends on
topology/noise. This initial implementation reads **the first sensor** on
one bus; do not rely on stable address selection when several are attached.

## Serial protocol (921600 baud)

- `HTEMP?` → `HTEMP ENABLED=1 VALID=1 TEMP=265 AGE_MS=100`.
  `TEMP` is in tenths of a degree Celsius and only valid if `VALID=1`.
- `HTMODE? 1` → `HTMODE 1 PC` (or `LOCAL` / `BACKUP`).
- `HTMODE 1 LOCAL` → persist DS18B20 as channel 1's **primary** source.
- `HTMODE 1 BACKUP` → use PC temperature when fresh, physical DS18B20
  after 6 s without a PC update.
- `HTMODE 1 PC` → only temperature commands from PC.

Modes persist in ESP32 NVS **only after an explicit change**. At boot,
power switching remains hardware-interlocked to 100% until a fresh
temperature is received. If the DS18B20 is absent, stale or invalid, the
normal **10-second 100% fan fail-safe** remains intact. DS18B20 updates
do not fabricate a fresh temperature.

Two-source (`DUAL`) cooling still requires a separate fresh secondary
source. For fully offline local control, disable DUAL on that fan.
The controller returns sensor state to the Windows GUI through `HTEMP?`.
The Windows agent is optional for the LOCAL source.

**Bench test temperature sensors and MOSFET driver before relying on this
for autonomous PC cooling.** `FAN_DC_PWM_VALIDATED=0` remains the default;
changing sensors does not bypass this safety guard.
