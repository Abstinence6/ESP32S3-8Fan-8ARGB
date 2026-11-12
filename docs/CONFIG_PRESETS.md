# Configuration presets and OpenRGB setup reference

The Windows companion provides a **configuration preset** consisting of eight
independent five-point fan temperature curves plus eight ARGB scene selections.
This is separate from the existing Silent/Balanced/Performance cooling-only selector.

## Included configurations

- Cooling: **Silent**, **Balanced**, **Performance**.
- Lighting: **Off**, **Static warm**, **Static cool**, **Rainbow**, **OpenRGB**.
- Any combination can be selected, then explicitly applied to the ESP32.
- Export the selected configuration to a versioned JSON file; import a JSON file
  to review and apply it later. Import alone does not write to the device.
- Apply sends `CURVE` commands and scene commands. Existing ESP calibration,
  fan type, sensor assignments, high-side switch validation and safety watchdog
  are unchanged. Applying fan curves writes the new curves to ESP NVS.
- An **OpenRGB** scene intentionally sends no static RGB output. Live pixel frames
  from OpenRGB via E1.31 take control of each output when they arrive.

## OpenRGB

The firmware already receives OpenRGB-compatible **sACN / E1.31** via direct
Wi-Fi (UDP 5568) or via the Windows companion over USB. It does **not**
implement automatic OpenRGB USB device discovery or the OpenRGB SDK protocol.
A GUI action exports `openrgb_e131_reference.json`, with eight zones and the
actual LED counts reported by the board; this is a **setup reference**, not an
importable OpenRGB profile. Configure the eight devices manually in OpenRGB.

USB bridge: OpenRGB -> 127.0.0.1:5568 -> Windows companion -> USB -> ESP.
Wi-Fi: OpenRGB -> ESP's LAN IP:5568 -> ESP. For Wi-Fi use a trusted LAN;
the UDP lighting protocol is not authenticated.

See [OPENRGB.md](OPENRGB.md) for E1.31 settings, electrical safety and
the 170 RGB pixels per-zone limit. The ARGB current-budget limiter remains
active for both USB and network frames.
