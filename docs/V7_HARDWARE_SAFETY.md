# FanARGB v7: hardware fail-ON verification

**Physical hardware has NOT been validated.** Passing firmware/software tests does not prove that the fans remain powered during ESP32 reset or loss of power.

## Bench checks (power fans independently of the running computer)

1. Use a current-limited 12 V bench supply, a real fan load, and an oscilloscope at the MOSFET gate **and the fan supply terminals**.
2. Remove ESP32 power and hold its reset line low; the independent driver circuit must still apply rated fan supply (fail-ON). An MCU output left floating is not a safe default.
3. Enter bootloader, reconnect/disconnect USB, crash the Windows agent, and simulate missing CPU temperature packets. Verify actual 12 V fan-supply behavior at every transition.
4. Repeat with all eight channels, normal ARGB load, and worst-case fan startup surge. Check power rail sag, MOSFET heating, GPIO boot strap behavior, and tach noise.
5. With explicitly enabled DS18B20 test firmware, disconnect each mapped probe and confirm that the fan never silently picks a different ROM address.
6. Validate logic levels, 25 kHz PWM operation, switching transients, safe thermal limits and the independent gate pull circuitry before ever enabling DC duty below 100%.

## Preserved defaults

- All 24 PWM/TACH/ARGB pins remain exactly as wired in the user PCB.
- `FAN_DC_PWM_VALIDATED=0`, `PC_POWER_ENABLED=0`, `HARDWARE_TEMP_ENABLED=0` in the standard build.
- GPIO35–37 may conflict with Octal PSRAM; GPIO46 is a strapping input.
- DS18B20 needs a verified spare 3.3 V GPIO with 4.7 kOhm pull-up, not a 5 V data signal.

**Never infer physical fail-ON safety from compiler output, mocks or CI.** A 12 V high-side key must be tested in its actual hardware failure modes.
## v8.2 software watchdog note

The ESP32 loop task attempts to register an 8-second task watchdog and feeds
it only after fan control, temperature sampling, network, MQTT and ARGB servicing.
A failure to arm it produces a serial warning. This only helps restart a
stalled MCU task: **it is not an electrical fail-ON guarantee** while the ESP
is resetting, unpowered or in its boot ROM. `FAN_DC_PWM_VALIDATED=0` remains
the default until real MOSFET/TACH/power testing. The `HEALTH` command now
provides `SOURCE` (usb, ds18b20, mqtt, none), `AGE_MS` and `FAILSAFE`
(sensor, overheat, fault, dc_lock, none) for each channel.
