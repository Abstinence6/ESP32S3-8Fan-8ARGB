# FanARGB v7: transport, sensors, native OpenRGB and history

## Implemented

- **Prioritized Serial writer:** immediate ASCII commands and latest-only coalesced RGB frames per zone. RGB has the existing CRC-16 but Serial writes are NOT application-level acknowledgements.
- **Conservative auto reconnect:** same unique USB serial+VID/PID, or same COM port+VID/PID if no serial number. Uncertain devices are rejected. Explicit disconnect or firmware flashing disables recovery.
- **Native OpenRGB SDK (experimental):** OpenRGB application connects as an SDK client to the opt-in **127.0.0.1:6743** server. It sees one virtual controller with eight linear ARGB zones. Basic OpenRGB SDK v0/v1 discovery, whole-device, zone and individual LED updates are supported. The GUI must be connected to ESP32 and have learned the LEDCOUNTS. Native mode, E1.31 and ARGB Studio are mutually exclusive. This does NOT install a native USB/HID plugin or automatically discover a device.
- **Passive TACH health:** flags repeated zero RPM or instability at unchanged PWM and logs/tray-alerts. It does not switch off a fan.
- **SQLite WAL history:** up to 30 days of fan samples, sensor metrics and events written in the background; CSV export in Service. Stale temperature is stored as NULL.
- **Up to 8 DS18B20 probes:** firmware lists CRC-checked 64-bit ROM IDs via HTLIST?, rescans via HTSCAN and persists per-fan ROM with HTMAP? and HTMAP. AUTO works only with exactly one physical DS18B20 present; ambiguous multi-device AUTO does not supply temperatures. PC/LOCAL/BACKUP modes retained.
- **Firmware image preflight:** chip ID ESP32-S3 (9), segment lengths, segment XOR checksum, embedded SHA256 and outer SHA256 checked. GitHub Actions validates the actual compiled BIN with the same code.

## Instructions

1. Install the v7 Windows EXE and connect ESP32-S3 USB/COM, waiting for LEDCOUNTS.
2. Open **ARGB**, enable **Native OpenRGB SDK · 8 zones**.
3. In OpenRGB, add a **Remote SDK server** with host **127.0.0.1** and TCP port **6743**. Do not also activate the E1.31 bridge or ARGB Studio.
4. Under **Датчики**, use DS18B20 **Сканувати 1-Wire**, then select the discovered 16-digit ROM for each fan and save it. This only works with opt-in, properly wired physical sensor firmware.
5. Under **Сервіс**, export historical fan measurements as CSV. Database defaults to %LOCALAPPDATA%/FanARGBControl/telemetry.sqlite3.

## Limitations and safety

- Native OpenRGB server is tested against a synthetic SDK socket client, not an actual installed OpenRGB GUI. Advanced SDK operations/protocol v2+ are not implemented.
- There is not yet a sequence-numbered command ACK/replay guard in firmware. A successful OS Serial write is not proof the ESP applied the command.
- No OTA / A-B partition rollback is installed: partition scheme, failsafe powering and rescue boot path must be validated first.
- Standard firmware still has HARDWARE_TEMP_ENABLED=0, FAN_DC_PWM_VALIDATED=0, PC_POWER_ENABLED=0.
- Hardware fail-ON and DS18B20 on a physical board have NOT been tested; see V7_HARDWARE_SAFETY.md.