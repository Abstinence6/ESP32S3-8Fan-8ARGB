# PCB checklist — 8 × 2/3-pin fans and 8 × ARGB

Status: **schematic proposed only; no physical electrical validation.**

- 8 independent high-side +12 V fan power switches, with appropriate gate drivers and external protection. **No 4-pin PWM contacts or switch-position jumpers**.
- 8 PWM GPIO, 8 TACH GPIO (unused for 2-pin), and 8 ARGB GPIO = 24 ESP32-S3 pins. Verify exact ESP32-S3 variant/PSRAM/USB straps.
- Set `FAN_OUTPUT_INVERTED` to actual gate-driver polarity. The default matches an earlier prototype and is not evidence of correct 12 V behavior.
- Hardware **must keep cooling powered during ESP reset/unpowered**. A simple P-MOSFET pull-up-to-12V + ULN2803 input from ESP defaults OFF; do not treat that topology as fail-safe.
- Per-channel current/fuse, short protection, MOSFET transient protection and thermal design; 12 V and 5 V fused separately. 3-pin TACH pull-up ~10 kΩ to 3.3 V.
- 2-pin lacks TACH. A real stall/current fault indicator would require a suitable smart power switch plus an additional sense line / ADC/multiplexing arrangement, **not present in this firmware/PCB pin budget**. No inferred or fictional 2-pin fault monitoring.
- ARGB: dedicated 5 V supply, level shift to 5 V, per-channel protection, bulk decoupling and power injection.
- Scope test both switching frequency and speed telemetry before unlocking `FAN_DC_PWM_VALIDATED` or `FAN_DC_TACH_VALIDATED`.

See [FAN_MODES.md](FAN_MODES.md), [WIRING.md](WIRING.md) and [TEST_PLAN.md](TEST_PLAN.md).
