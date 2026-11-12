# Fan modes: 2-pin and 3-pin DC high-side only (v5)

**Reference firmware; the 12 V power stage has not been electrically validated.**
There is no 4-pin PWM mode, no connector jumper, no MCP23017 and no hardware type detection.

| Fan | GPIO (per channel) | Physical feedback | Limits |
|---|---|---|---|
| 2-pin | 1 PWM + 1 reserved TACH input | None | No real RPM, tach-based stall alarm or closed-loop RPM |
| 3-pin (default) | 1 PWM + 1 TACH input | TACH open collector to 3.3 V | TACH can be invalid while fan supply is PWM-chopped |

8 fans × 2 + 8 ARGB outputs = **24 GPIO**. The TACH input is unused for 2-pin.

## Hardware interface (proposed, NOT a build-ready circuit)

```text
ESP32 GPIO PWM_i -> correctly designed high-side gate/logic interface -> switch +12V_i
+12V PSU ---------> high-side power switch ---------------------------> FAN_i +12V
GND -----------------------------------------------------------------> FAN_i GND
FAN_i TACH (3-pin only) ----+----------------------------------------> ESP32 TACH_i
                           +--[10k]--> 3.3V
```

The controller cannot drive a 12 V P-MOSFET gate safely **directly** from 3.3 V GPIO.
A single NPN/ULN2803 sink with a P-MOSFET pulled up to +12 V normally defaults to
**power OFF during MCU reset**, which is NOT a fail-safe cooling circuit. The final
hardware must explicitly implement power ON during reset/MCU power loss, appropriate
level shifting, gate clamp, motor flyback/transient protection, fuse/current limiting,
per-channel inrush protection, and PCB thermal design. Gate-driver polarity may differ.

## Firmware interlocks

- `FAN_DC_PWM_VALIDATED=0` **by default**: any request below 100% duty is rejected; all channels are held at 100%.
- `FAN_DC_PWM_HZ=250` **by default**: configurable only at build time, range 80–1000 Hz. This is a design starting point, not proof that a specific fan or switch works at 250 Hz.
- `FAN_OUTPUT_INVERTED=1` by default (legacy prototype output). Set to `0` **only if** the validated transistor/gate stage is non-inverting. Check both logic levels electrically before enabling the output.
- `FAN_DC_TACH_VALIDATED=0` **by default**: below 100% power, the RPM report becomes untrusted and calibration/closed-loop control remain disabled. Set to 1 only after confirming real TACH behavior across the duty range.
- `TYPE n 2|3` stores the logical type. `TYPE n 4` and `TYPE n AUTO` are rejected. 2-pin cannot provide TACH.
- New stored profiles are version 4. v1/v2/v3 migrate to 3-pin (or preserve explicit 2-pin), retain temperature curves but invalidate all old RPM calibration and PID settings.

No flag bypasses the physical need for a true fail-safe. **Do not set a validation flag merely to make a command work.**

## Bench acceptance checklist

1. Verify 12 V and GPIO voltage on/off/reset, correct pinout, clamp and flyback paths.
2. Confirm fan supply is **ON at reset and while ESP32 is unpowered**. Test the actual MOSFET/gate driver wiring.
3. Check PWM 80–1000 Hz across 0–100%, startup, minimum run speed, acoustic noise, and key temperature.
4. Measure TACH waveforms against real RPM while switching supply. If invalid, do not enable `FAN_DC_TACH_VALIDATED`.
5. Check inrush, stall, cable disconnect, short circuit, full eight-channel current and 5V ARGB load.
6. Verify loss of PC temperature forces 100% request in all modes, including after MQTT disconnect.

See [WIRING.md](WIRING.md) and [TEST_PLAN.md](TEST_PLAN.md).
