# Wiring reference / апаратна частина

This is an **interface description, not a validated PCB schematic**.

## Four-wire fans (x8)

Common PC fan connector pinout (VERIFY connector orientation and vendor datasheet):

1. GND — common system ground.
2. +12 V — appropriate fan power rail; do not source it from ESP32.
3. TACH — open collector/open drain from the fan; connect to the configured ESP32 input with a separate pull-up (~10 kOhm) to **3.3 V**.
4. PWM — **5 V pulled-up logic input** inside the fan; drive with an NPN/NMOS open-collector/open-drain stage, not directly with an ESP32 GPIO. Do not add a pull-up to 12 V.

Example NPN topology, repeated x8:

```text
ESP32 GPIO_PWM --[1k..4.7k]--> NPN base
                              NPN emitter ------ GND
                              NPN collector ---- FAN PWM (pin 4)
                               (optional base pull-down to GND)
FAN TACH (pin 3) ----+---------> ESP32 GPIO_TACH
                     +--[10k]--> 3.3 V
FAN GND (pin 1) ----------------- GND
FAN +12V (pin 2) ---------------- +12 V PSU
```

With this transistor, a GPIO high level *pulls the fan PWM input low*. `kPwmDriverInverts=true` handles this inversion in software. The PWM input is released (logic HIGH) on MCU reset/disconnection, normally asking the fan to run at full speed.

**Do not switch the 12 V fan supply using the PWM logic transistor.** Fan supply switching requires a separately rated MOSFET/high-side circuit.

## ARGB strips (x8)

- Assume **5 V addressable RGB** such as WS2812B or SK6812 RGB, with single-wire DI. Not compatible with 12 V analog RGB or 4-pin non-addressable RGB.
- Use a 5 V 74AHCT125/74AHCT245 data buffer, referenced to the same ground, between GPIO data pins and strip DIN.
- Use ~220-470 ohm resistor in series with each data line (often near the strip), and bulk + local decoupling of 5 V.
- Power strips from a dedicated 5 V supply with proper fusing/power distribution. Do not push strip current through the microcontroller PCB/USB connector.
- The sample controls **RGB (3-channel)** LEDs. SK6812 RGBW needs an RGBW pixel type and buffer handling changes.

## MCU / board variants

- Verify ESP32-S3-DevKitC-1 board revision and module; GPIO38 drives the on-board LED on some v1.1 boards.
- Do not use GPIO35-37 if the module has octal PSRAM.
- Reserve native USB D-/D+ on GPIO19/20 if using native USB.
- Reserve boot strap pins GPIO0, GPIO3, GPIO45, GPIO46 for safe flashing.
- Keep UART0 GPIO43/44 available if you intend to use USB-to-UART `Serial`.
