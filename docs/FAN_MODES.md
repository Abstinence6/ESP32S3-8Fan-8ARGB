# 2/3/4-pin fans: 3-pin-first PCB, no GPIO expander

**Status:** firmware compiles for 8 channels; the power circuit is a *proposed design*, not a tested schematic. The user will install intelligent high-side power switches. There is **no MCP23017, I2C mode switch or automatic 4th-contact detector**.

## GPIO budget

| Per channel | GPIO on ESP32-S3 | Operation |
| --- | --- | --- |
| `PWM[ch]` | 1 | One logical 25 kHz duty stream; used by either selected power-key path or pin4 PWM path |
| `TACH[ch]` | 1 | RPM pulse input with an external pull-up to **3.3 V** (2-pin has no feedback) |
| ARGB | 1 | Independent data line, with correct 5 V logic/interface hardware |

8 fans + 8 ARGB = **24 ESP32-S3 GPIO total**, no GPIO expander. Reserve USB, flash/PSRAM and strapping pins according to the exact ESP32-S3 module.

## Physical selection is a jumper, not firmware

```text
   ESP32 PWM[ch] ---> NPN open-collector ---> 4-pin connector contact 4
          |
          +---> conditioned/inverted PWM ---> [ DC  o--o  KEY_IN ]
                                               [ PWM o--o  ON_LEVEL ]
 +12 V ---> intelligent high-side switch ---> fan contact 2 (+12V)
 GND ---------------------------------------> fan contact 1 (GND)
 TACH contact 3 -- 10k pull-up to 3.3V ----> ESP32 TACH[ch]
```

**3-pin (default):** set the jumper to **DC**. The intelligent high-side key receives the properly conditioned PWM signal and controls fan +12 V. TACH comes from contact 3; its signal may be unreliable during power chopping, so test with an oscilloscope and compare RPM readings.

**2-pin:** same **DC** jumper, with no TACH. RPM feedback, stall detection by RPM, calibration and PI/PID are unavailable. Any fault diagnosis must come from a separate diagnostic interface of the chosen key (not yet connected).

**4-pin:** set jumper to **PWM**. The smart key receives a stable **ON level**, ensuring constant +12 V, while the open-collector PWM output drives contact 4 at 25 kHz. The MCU cannot change the jumper via a software command. Contact 4 must **not** see 12 V and must not be driven push-pull into the fan's internal pull-up.

The drawing is logical, **not a checked transistor schematic**. The key's IN polarity, threshold, current, PWM response and default-at-reset require a verified circuit. PWM must be conditioned so that `FAN 100` means a continuously ON key, **even at ESP reset or when firmware hangs**. A simple GPIO pull resistor alone may not guarantee that. Review the actual smart switch datasheet first.

## PWM frequency and safety interlock

The firmware currently uses a single 25 kHz LEDC stream per fan. **That is the intended 4-pin PWM frequency, not a guarantee that a DC high-side key supports 25 kHz**. Confirm the key allows PWM at this frequency at the motor's expected inrush/current/thermal load. If not, redesign the driving stage or configure separate compatible PWM frequencies/timers before enabling DC control; switching all fans' supply at 25 kHz without validation is unsafe.

By default, `include/BoardConfig.h` has `kDcSupplyPwmValidated = false`. 2/3-pin channels are deliberately locked at 100% duty until your hardware has passed validation. When it has, set `FAN_DC_PWM_VALIDATED=1` in the PlatformIO environment (or in the header) and **reflash** the ESP32; it then permits 0–100% on DC-mode channels. This is a compile-time acknowledgment of bench-tested hardware, not automatic detection.

Also test fans that stall at low duty. The firmware's thermal safety action can request 100%, but **independent hardware fail-safe must keep the key fully ON whenever ESP is reset/offline**. A 4-pin cable with a 3-pin jumper or a 3-pin cable with the PWM jumper is a mismatched wiring state; do not change jumpers while powered.

## Firmware commands and persistence

- Fresh NVS starts with `TYPE n 3` for all eight fans; existing 4-pin NVS settings remain unchanged when upgrading.
- `TYPE n 2`, `TYPE n 3`, `TYPE n 4` persist the **manual configuration**. Apply only after selecting the matching jumper with power off.
- `TYPE? n` prints `SET=<2|3|4> DETECTED=255 RPM_OK=<0|1> DC_HW=<0|1>`: `DETECTED=255` means **not sensed**; `DC_HW=0` means DC switching remains safety-locked.
- `TYPE n AUTO` is explicitly rejected. TACH is not a way to distinguish 3-pin from 4-pin, and its absence is not proof that a 2-pin fan is connected.
- Changing type invalidates the fan's PWM-RPM calibration and PI settings. Type 2 can still be temperature-controlled by PWM when the DC key is validated, but cannot measure RPM.

## Hardware validation checklist

1. Confirm exact ESP32-S3 board/module and all 24 free GPIOs.
2. Confirm smart key's rated PWM frequency, load/inrush limits, self-heating, and control polarity.
3. Scope the key IN and +12 V output at 0%, 50% and 100%, then test 3-pin TACH stability.
4. Scope the 4-pin PWM contact and ensure +12 V remains constant when jumper is set to PWM.
5. Disconnect the MCU / reset it / cut USB power: fans should default to maximum airflow by **hardware design**.
6. Test lost-PC-temperature watchdog, blocked fan, disconnected tach, reverse/misplugged fan and short-circuited load.
