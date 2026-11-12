# 2-pin and 3-pin only: DC supply switching

Firmware v5 **does not implement a 4-pin PWM signal**. Per fan: one 12 V
high-side switched power output and one optional TACH input, for a total of
16 native GPIO for fans plus eight ARGB data outputs. No MCU I/O expander or
fan-type auto-detector is required. `TYPE <channel> 2|3` only configures whether
TACH is expected. New and migrated profiles default to type 3.

## Electrical design constraints

```text
           +12 V --- [qualified HIGH-SIDE switch] --- FAN +12 V
                             ^                          |
ESP32 PWM GPIO --- [safe 3.3 V -> 12 V gate drive]       MOTOR
ESP32 GND ---------------------------------------- FAN GND
ESP32 TACH GPIO <---- [pull-up to 3.3 V] --------- FAN TACH (3-pin only)
```

**NEVER connect fan TACH directly to 12 V.** TACH open collector generally
requires pull-up to 3.3 V with a suitable resistor. Ground must be continuous
for tach measurement: do not PWM the fan's return/GND pin.

**No fan power stage has been validated on a real PCB.** Firmware keeps all
2/3-pin channels at 100% duty when `FAN_DC_PWM_VALIDATED=0` (shipping default).
It rejects 0..99% requests from Serial, the Windows GUI, MQTT and PID. A
compile-time flag is **not** a hardware-safety guarantee.

The reference power waveform is **250 Hz, 8-bit** for testing with a selected
high-side driver, not the 25 kHz control waveform used by 4-pin fans. Do **not**
assert `FAN_DC_PWM_VALIDATED=1` without validating switch turn-on/off times,
peak starting current, MOSFET heat, fan noise and startup, supply transients,
TACH integrity and the fan's full supply voltage during reset/MCU power loss.
Polarity is configured in `BoardConfig.h` (`kPwmDriverInverts=false` for
ESP-output HIGH -> ULN2803 sink -> P-channel MOSFET ON). A simple ULN2803 +
P-MOSFET with a gate pull-up typically **turns fan power OFF at MCU reset**:
that wiring is NOT fail-safe by itself. A separate, validated hardware
power-ON-at-reset arrangement is mandatory for critical cooling.

## Feedback rules

- `2-pin`: RPM is always unavailable (reported as zero). No RPM-based PID,
  calibration or TACH stall detection is possible; current/fault telemetry
  needs additional hardware if required.
- `3-pin`: TACH may be unreliable under chopped 12 V power. Firmware rejects
  implausible RPM samples and reports `TACH_VALID`, but that alone does not
  prove electrical correctness. Test scope captures at the intended PWM range.
- Calibration invalidates old RPM tables on firmware migration to v5.
- A missing PC/MQTT temperature still forces 100% demand after 10 s in every
  firmware mode. At reset, only correctly designed hardware can deliver power.

See [PCB_NEXT.md](PCB_NEXT.md), [MQTT.md](MQTT.md).
