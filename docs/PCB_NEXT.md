# PCB v2 / hardware hooks still requiring a schematic and component choice

Firmware features that need **physical circuits**, not just extra code:

- Eight independent **intelligent high-side fan supply switches**, properly sized for each motor and rated for the selected PWM frequency/current/inrush. Current firmware shares 25 kHz PWM with a conditioned signal path. **Confirm the chosen part's PWM frequency / dissipated heat from its datasheet before fabrication.** If unsuitable, add a separate lower-frequency PWM / DC buck stage.
- A hardware **FORCE_100 / bypass** selector that keeps 12 V fan power steadily ON in 4-pin PWM mode, **including during ESP32 reset** (external pull-ups / guaranteed default state). One optional MCP23017 provides eight bypass outputs and eight pin4 sense inputs.
- Protected 3.3 V-compatible sensing of the pin4 internal pull-up for automatic 4-pin detection. Do not apply 5 V directly to the MCP23017/ESP GPIO inputs. A 2-wire fan and a failed tachometer remain indistinguishable without additional identification hardware.
- An output or open-drain **diagnostic fault pin** from each smart key, preferably measurable current telemetry for 2-pin obstruction detection, and overload/short-circuit protection. Fan type detection does not substitute for overcurrent hardware.
- Fused 12 V fan power and fused 5 V ARGB rails. Use power and ground wiring rated for expected current; provide transients/ESD suppression and 74AHCT-series level shift for LED signals.
- Optional local 2- or 4-channel NTC thermistor ADC modules (with dividers), DS18B20 temperature sensors, coolant thermistor and flow sensor. Firmware thermal fail-safe currently relies on temperatures streamed from the PC; autonomous control would require these sensors and a software module.
- 12 V and 5 V power monitoring via correctly scaled/protected voltage dividers and ADC or I2C monitors; ESP ADC pins are **not 12 V tolerant**.

**Do not blindly tie the 4-pin PWM contact to the smart-switch logic input.** There are two different electrical interfaces and a bypass rule; see [FAN_MODES.md](FAN_MODES.md).

## Remaining hardware-verification tasks

1. Confirm ESP32-S3 module and board revision and the availability of GPIO33/34.
2. Select the exact smart switch, inspect maximum PWM frequency, drive polarity, short-circuit behavior, thermal behavior, diagnostic type, and off-state on reset.
3. Draw and review one fan channel schematic, then replicate it x8.
4. Verify on an oscilloscope that pin4 receives 25 kHz PWM with 3.3/5 V open-collector behavior, while the smart switch remains permanently ON.
5. With 2/3-wire load and no pin4, verify smart switch's output duty, motor starting behavior, TACH stability, EMI and switching losses; adapt frequency if needed.
6. Test power loss, unplugged fan, shorted PWM pin, shorted +12V fan supply, I2C expander disconnect, PC app crash and Wi-Fi outage. Fans should revert to safe behavior.
