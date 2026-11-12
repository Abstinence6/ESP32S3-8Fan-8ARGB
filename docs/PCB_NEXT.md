# PCB checklist for ESP32-S3 8x 2/3-pin fans and 8x ARGB

This is a **design checklist, not a tested schematic**. The present software
supports eight 12 V supply-controlled fan outputs and optional TACH feedback.
Four-wire fan PWM routing, the DC/PWM jumper and I/O expander are eliminated.

- 8 x high-side 12 V switching paths; do not interrupt fan ground. The chosen
  MOSFET and discrete/array gate drive must work at 3.3 V ESP IO levels.
- 8 x 3.3 V TACH inputs, pull-ups and ESD protection, not tied to 12 V;
  2-pin connectors leave TACH unused.
- **Fail-ON power circuitry independent of ESP GPIO**: during reset,
  bootloader, flashing, Wi-Fi failures, and MCU power loss the motors should
  still receive uninterrupted 12 V. Verify the actual schematic electrically.
- Validate with a scope: high-side rising/falling edges at candidate 250 Hz,
  gate Vgs limits, EMI, inductive spikes, motor startup and stalled current,
  MOSFET total thermal loss at all eight channels simultaneously.
- Do not unlock `FAN_DC_PWM_VALIDATED` just to silence the firmware safety guard.
- Protect both 12 V fan power and 5 V ARGB rails with appropriately rated
  fuses, reverse-polarity protection, decoupling and physical wiring separation.
- Use proven 3.3 V -> 5 V ARGB data level shifting, common ground and power
  injection for long strips. Software LED current budget is not a fuse.
- Reserve GPIO by reference (`BoardConfig.h`) and verify against exact module,
  flash/PSRAM package and USB pin assignments.
- Optional: channel current sensing/driver fault outputs for 2-pin stall
  diagnostics, onboard safety temperature sensing independent of Windows/MQTT.

See [FAN_MODES.md](FAN_MODES.md), [MQTT.md](MQTT.md).
