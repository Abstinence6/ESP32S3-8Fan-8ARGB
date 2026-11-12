# Wiring reference — ESP32-S3 8 Fan / 8 ARGB

This is a **wiring interface description, NOT a validated circuit schematic**.

## Fan 2-pin / 3-pin (12 V) — repeated ×8

| Contact | Function | Wiring |
|---|---|---|
| 1 | GND | Common system ground, never switched by the low-side fan key |
| 2 | +12 V | Through a correctly rated, protected high-side power switch |
| 3 (3-pin only) | TACH | Open-collector TACH to ESP32 via ~10 kΩ pull-up to 3.3 V |

ESP32 PWM GPIO must drive an interface matched to the **selected high-side key**, not a bare 12 V MOSFET gate. Current driver polarity is set at build time by `FAN_OUTPUT_INVERTED`.
The production PCB must enforce fan **ON** on loss of MCU power/reset, independent of firmware. A lone ULN2803 sink + P-MOSFET pull-up to +12 V does **not** satisfy this: it defaults OFF.
No 4-pin PWM fan control is supported. No type-detection pin or DC/PWM jumper.

## 5 V addressable ARGB strips ×8

- Use 5 V WS2812B / SK6812 RGB strips (not 12 V analog RGB).
- A 74AHCT125/74AHCT245 or equivalent 5 V logic buffer for data is recommended; put 220–470 Ω in series near each DIN and provide decoupling.
- Provide a separate fused 5 V power rail and power injection. Do not supply LED current through the ESP32 USB connector.
- 8 × 30 pixels at full white can draw about 14.4 A @ 5 V at ~60 mA/pixel. The software budget is only an **estimate**.

## ESP32-S3 board notes

- Re-check GPIO38; some DevKitC-1 revisions use it for the on-board RGB LED.
- Keep GPIO19/20 for native USB if used, GPIO43/44 for UART0, GPIO0/3/45/46 for boot straps, and flash/PSRAM pins reserved.
- Use board-specific pin validation before building a PCB. See `include/BoardConfig.h` and [PCB_NEXT.md](PCB_NEXT.md).
