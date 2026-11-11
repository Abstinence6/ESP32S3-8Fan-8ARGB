# OpenRGB / E1.31 RGB integration

This is a **real RGB pixel-stream integration**, not a fixed selection of ESP-side effects. OpenRGB (or xLights/other sACN transmitters) sends a complete RGB pixel frame for each output; the PC application forwards the latest frames over the **same USB serial port** it uses for fan temperatures and calibration. Each physical LED can have an independent color.

**Not plug-and-play USB detection:** the controller appears to OpenRGB as **eight manually configured E1.31 network devices** (locally on the same PC). The companion Windows app must remain running. The standard OpenRGB **E1.31 Devices** transmitter is used; do **not** install the OpenRGB **E1.31 Receiver** plugin for this path (that plugin controls existing OpenRGB devices from other software, the reverse direction).

## 1. Configure ESP32

- Hardware: eight 5 V addressable RGB / RGBW**not** supported; valid types WS2812B or SK6812 **RGB**. Use suitable 5 V PSU and 3.3-to-5 V logic level shifter.
- Set `kArgbLedCounts[8]` in `include/BoardConfig.h` to the real pixel counts (default **30 each**). **1–170 RGB LEDs per output** for the current protocol.
- Build/upload `pio run -e esp32s3 -t upload`. New firmware uses USB Serial at **921600 baud**; update the PC program together with firmware. The companion GUI reads actual counts from the firmware with `LEDS` before forwarding any ARGB frames.

## 2. Start the Windows companion

1. Start `FanARGBControl.exe` or run `python pc_app/main.py`.
2. Connect to the ESP32 COM port. Leave this program connected; **do not open the same COM port in OpenRGB**.
3. Under **ARGB / OpenRGB**, enable **E1.31 → USB, 8 zones**.
4. Status should say `127.0.0.1:5568`. On Windows this binds only to the local host (not the Internet/LAN). If another application owns UDP 5568, close it or disable the conflicting listener.
5. LibreHardwareMonitor is optional for ARGB streaming, but **required for PC-temperature-based automatic fans**. The GUI polls LHM asynchronously so RGB updates are not blocked by an unresponsive sensor service.

## 3. Add 8 devices in OpenRGB

In OpenRGB, open **Settings → E1.31 Devices** (wording may differ across versions). Add **eight E1.31 devices**, each configured as follows:

| OpenRGB name | Destination IP | Start universe | DMX start channel | RGB LEDs | Type |
|---|---|---:|---:|---:|---|
| ESP32 ARGB 1 | `127.0.0.1` | 1 | 1 | match output 1 | Linear |
| ESP32 ARGB 2 | `127.0.0.1` | 2 | 1 | match output 2 | Linear |
| ESP32 ARGB 3 | `127.0.0.1` | 3 | 1 | match output 3 | Linear |
| ESP32 ARGB 4 | `127.0.0.1` | 4 | 1 | match output 4 | Linear |
| ESP32 ARGB 5 | `127.0.0.1` | 5 | 1 | match output 5 | Linear |
| ESP32 ARGB 6 | `127.0.0.1` | 6 | 1 | match output 6 | Linear |
| ESP32 ARGB 7 | `127.0.0.1` | 7 | 1 | match output 7 | Linear |
| ESP32 ARGB 8 | `127.0.0.1` | 8 | 1 | match output 8 | Linear |

Choose **RGB color order**, use standard unicast E1.31, then save the configuration and re-scan devices as needed. Use **Direct** mode on the E1.31 devices for advanced software effects. Each zone can be driven separately by OpenRGB profiles/effects, including third-party OpenRGB effects plugins. If OpenRGB cannot generate a particular effect itself, the ESP firmware cannot invent it; it faithfully displays the pixel stream received.

The same settings (unicast `127.0.0.1`, UDP 5568, universe 1–8, first channel 1, RGB bytes) work with any other **E1.31 transmitting** program, e.g. xLights. The Windows companion does **not** implement native SignalRGB device autodiscovery or proprietary protocols.

## Limits and safety

- E1.31 contains up to 512 DMX data slots per universe; one RGB pixel consumes three slots. Hence at most **170 RGB pixels** on each of our eight universes.
- The bridge coalesces new frames and forwards up to about **25 full frames per second** at **921600 baud**, depending on USB UART speed, strip lengths and CPU load. sACN UDP is best effort: stale intermediate frames can be dropped.
- The UART binary format uses 0xA5 0x5A, channel, LED count, RGB pixel bytes, CRC-16/CCITT-FALSE. Malformed frames are discarded without changing output.
- While receiving external frames, the firmware switches that output to **External** mode with full digital brightness (RGB values supplied by OpenRGB define brightness). This may be **much brighter** than the original default and requires adequate LED 5 V power distribution.
- Stopping OpenRGB leaves the **last pixel colors** on the strip. `OFF <ch>` or the GUI button clears it; new incoming frames regain control. This does not affect fan thermal fail-safe logic.
- Local E1.31 port 5568 only: no Wi-Fi firmware needed. For standalone OpenRGB without this PC app, native USB plugin support or on-device network E1.31/Art-Net/DDP would be a separate implementation.

## Troubleshooting

1. No LEDs: use `LEDS` in the GUI Serial console and confirm `LEDCOUNTS N1 ... N8` arrives. Firmware & PC app must both be the updated version and use 921600 baud.
2. Device not visible in OpenRGB: manually add E1.31 devices; this is **not** an automatically discovered serial or HID device.
3. OpenRGB sends but nothing lights up: verify 127.0.0.1, UDP 5568, unicast, universe 1–8, channel 1, and that the GUI checkbox is enabled.
4. Colors wrong: verify 74AHCT level shifter, wiring, and whether your strip is GRB in hardware (the firmware encodes incoming RGB into NeoPixel GRB output).
5. All fans run at 100%: that is the designed temperature fail-safe if LHM or the companion is not feeding current temperatures. ARGB networking does not replace thermal telemetry.

Useful OpenRGB references: https://openrgb.org/ and https://gitlab.com/OpenRGBDevelopers/OpenRGB-Wiki/-/blob/stable/Device-Documentation/Serial-LED-Strips.md
