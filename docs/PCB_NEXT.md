# PCB checklist: universal 3-pin-first controller without I/O expanders

## Proposed fan channel

- **2 ESP32-S3 GPIO per fan**: PWM output and TACH input. Eight fans consume 16 GPIO; eight ARGB data lines consume another 8 = **24 total**.
- A 4-pin connector accepts 2-pin/3-pin/4-pin fans with correct keying/orientation. Use separate 12 V and 5 V fused PSU rails, suitable return paths and decoupling.
- The **user-supplied intelligent high-side switch** controls +12 V. A physical **DC/PWM jumper** selects whether its input follows PWM or is held permanently ON. Open-collector fan PWM contact 4 is a separate conditioned path; no extra GPIO selects it.
- **3-pin is the main mode** (DC jumper, PWM through key), 2-pin shares the same mode with no TACH, 4-pin needs jumper PWM (+12 V always on).
- Do not connect fan contact 4, GPIO or key input to uncontrolled 12 V. Never put 5/12 V directly on an ESP32 input. TACH uses a pull-up to 3.3 V.
- No MCP23017, GPIO expander, automatic type detector or in-circuit software bypass; no new I2C pins allocated.

## Before enabling DC PWM

The firmware's 2/3-pin duty is **100% only** by default (`FAN_DC_PWM_VALIDATED=0`). The selected smart switch must be checked for **25 kHz PWM motor switching**, supply-voltage transients, inductive energy, rated peak motor startup current, thermal derating and safety ON default when MCU is reset/unpowered. Many high-side switches cannot run 25 kHz power PWM. In that case, revise the circuit/software rather than merely setting the validation flag.

## Optional next PCB revision (not implemented)

- On-board NTC/DS18B20/coolant/flow inputs; they need protection, wiring and sometimes more pins, so current 24-GPIO budget must be rechecked.
- Sense 5/12 V through adequately scaled ADC dividers or a dedicated monitor (not connected to bare GPIO).
- Measure actual key fault/current status if available, especially important for 2-pin fans without TACH.
- ARGB overcurrent protection, power injection and 3.3-to-5 V logic interface suitable for chosen strip type.

See [FAN_MODES.md](FAN_MODES.md). No physical PCB has been validated by these firmware tests.
