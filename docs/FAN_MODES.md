# Universal 2-, 3- and 4-pin PC fan headers (PCB revision, provisional)

**Status:** the firmware supports the types and a hardware mode-selection interface; the new power-switch PCB is **not built or validated**. `kEnableFanModeExpander` defaults to `false`, so the existing PCB remains 4-pin PWM only. Do not enable DC modes until the actual intelligent high-side switch's datasheet has been checked.

## One PWM channel, two conditioned electrical destinations

Each fan uses **one independent ESP32-S3 LEDC channel** on `kFanPwmPins[ch]` at 25 kHz. The same *logical duty cycle* controls either the 4th signal contact or the switched power. It must **not** be connected to both electrical destinations unconditioned.

```text
 ESP32-S3 PWM[ch] ──┬── NPN/OD transistor ──────────────> fan pin4 PWM (4-pin only)
                    │   (transistor INVERTS GPIO)
                    └── inverter/buffer -> OR gate ──────> smart HIGH-SIDE key IN
                                         ^
                    MCP23017 GPA[ch] ────┘ FORCE_100% / BYPASS

                         +12V ──> smart high-side key ────> fan pin2 (+12V)
                         GND ────────────────────────────> fan pin1 (GND)
                         fan pin3 (TACH) ── pull-up 3.3V ─> ESP32 GPIO_TACH[ch]
                         fan pin4 (PWM) ── protected sense ─> MCP23017 GPB[ch]
```

**For 4-pin:** `FORCE_100%=1` holds the *power switch* continuously ON; only fan pin4 is PWM controlled, with fan supply steady at 12 V. **For 2/3-pin:** `FORCE_100%=0`; the fan has no pin4 and the power switch follows the correctly polarized PWM. At 100% the power switch is continuously ON. An open-collector signal output is required at pin4; do not apply 12 V there.

The intelligent key has to be explicitly rated for its current/inductive motor loads, startup/inrush, diagnostics, heat sinking, and **PWM operation at 25 kHz**. Many automotive/industrial intelligent high-side switches are NOT rated for such fast modulation; if its datasheet gives a lower frequency, use a separate lower-frequency supply PWM generator (or DC voltage converter) rather than tying the two PWM streams. Do not infer suitable PWM frequency from its current rating alone.

**Fail-safe hardware design is mandatory:** an MCU reset, unpowered MCP23017, loose I2C cable or floating digital input must leave the +12 V smart switch in fully ON mode for cooling. Provide a pull-up, suitable logic gating, proper 3.3 V supply sequencing and a fault-tolerant default state in the discrete hardware. Software alone cannot guarantee this. Use current-limit/fault outputs of the specific smart switch once chosen. A schematic review is required before connecting fans.

## Optional MCP23017 (`kEnableFanModeExpander = true` after wiring)

| Pins | Purpose | Reset-safe requirement |
| --- | --- | --- |
| `GPA0..7` | `FORCE_100%` / power bypass for fan 1–8 | External pull-UP to force steady fan power |
| `GPB0..7` | Detect an internal PWM pull-up on fan contact 4 | A **protected 3.3 V logic sense circuit**; do not feed 5 V directly |
| ESP GPIO33/34 | I2C SDA/SCL (provisional) | Verify accessibility on your specific S3 module/PCB |

MCP23017 address `0x20`, BANK=0 register layout. Adjust as needed in `BoardConfig.h` and verify 3.3 V I2C pull-ups. The firmware does not read a raw 5 V PWM pin directly. Port B inputs must have a defined low state when pin4 is unconnected, while presenting suitably high impedance to the fan's PWM input pull-up.

## Automatic type detection — conservative

1. All outputs start at **100%**, high-side power switches bypassed.
2. After three consecutive 1-second samples with 4th contact's internal pull-up present: classify **4-pin**, keep power ON and use 25 kHz pin4 PWM.
3. With pin4 absent and credible TACH over three samples: classify **3-pin**, enable supply PWM.
4. No pin4 and no TACH is **unresolved**: could be 2-pin, failed 3-pin, disconnected fan or a nonstandard fan. Remain at full supply voltage. The user must confirm `TYPE n 2` after testing.

`TYPE 1 AUTO` enables auto detection **only if the expander and sense circuits are working**. `TYPE 1 2`, `TYPE 1 3`, `TYPE 1 4` set explicit wiring type and persist it to ESP NVS. Switching type clears an old calibration curve **PWM→RPM**, because power PWM and 4-wire PWM are not interchangeable.

- 4-pin: RPM feedback, open-loop PWM and calibrated closed-loop RPM/PID.
- 3-pin: RPM feedback can work at stable full power; pulsing the supply may interrupt/corrupt TACH transitions. Closed-loop RPM/calibration require validation with the specific fan/key/power electronics.
- 2-pin: no TACH. PWM-percent regulation only; **no measured RPM, no PID, no stall detection based on TACH**, and no PWM→RPM calibration. Key's current/fault diagnostics can later add blocked-rotor protection, but cannot measure RPM directly.

If the I2C expander is disabled/absent, firmware rejects `TYPE n 2`, `TYPE n 3`, and `TYPE n AUTO`. Existing 4-pin fans remain supported as before. Every 2/3-pin type requires a valid external high-side power-control stage; no ESP GPIO is allowed to source fan motor current.

## Commands

- `TYPE? 1` — reports persisted type, detected type, RPM capability and DC hardware availability.
- `TYPE 1 AUTO` — conservative automatic detection (requires expander + sense inputs).
- `TYPE 1 2` / `TYPE 1 3` / `TYPE 1 4` — manually choose fan wiring.
- `CONFIG 1` and `STATUS` — append `TYPE`, `DETECTED`, `RPM_OK` fields.

Numerical type codes: `0=AUTO`, `2=2-pin`, `3=3-pin`, `4=4-pin`, `255=UNKNOWN/unresolved`.

### References

- Intel four-wire PWM fan specification: pin4 25 kHz (21–28 kHz), open-drain/open-collector.
- Analog Devices, *Why and How to Control Fan Speed for Cooling Electronic Equipment* — 2/3-wire supply control vs 4-wire PWM and tachometric feedback.
- Microchip MCP23017 datasheet, BANK=0 IODIRA=0x00, GPIOB=0x13, OLATA=0x14.
