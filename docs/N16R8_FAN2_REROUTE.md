# N16R8 FAN2 / ARGB2 pinout for standard eight-channel firmware

**Standard firmware now exposes all eight channels without an extra opt-in flag.** `esp32s3_n16r8_native_usb` reports `CHMASK=255`, and FAN2/ARGB2 use GPIO8/11/17 in firmware. Electrical signal wiring must use those pins for the physical channel to function.

## Physical remap (only after wiring)

| Signal | Original (PSRAM) | Proposed free GPIO | WROOM-1 module pad |
| --- | ---: | ---: | ---: |
| FAN2 high-side driver logic input (PWM) | 35 | **8** | 12 / IO8 |
| FAN2 TACH input | 36 | **11** | 19 / IO11 |
| ARGB2 LED data output | 37 | **17** | 10 / IO17 |

ESP32-S3-WROOM-1-N16R8 internally uses GPIO35/36/37 for 8 MB Octal PSRAM. Never connect external loads or probe those pins as general-purpose I/O.

GPIO8/11/17 are currently unused by this repository's static pin map, but the actual assembled PCB and connector routing were NOT physically inspected. Check all three candidate pads with a continuity meter while power is disconnected.

1. Locate the real FAN2 PWM driver logic input, FAN2 TACH return and ARGB2 data connection on the actual board.
2. Isolate the old GPIO35/36/37 connections completely; do not move any 12 V supply to the ESP32 pin.
3. Connect driver logic input to GPIO8, compatible 3.3 V tachometer signal to GPIO11 and LED data/level shifter input to GPIO17.
4. Check 5 V/3.3 V/12 V rails for shorts. Check fan high-side fail-ON at reset, 12 V inrush/transients and TACH pull-up. Keep fan and ARGB external power off for initial boot.
5. Use this opt-in environment only after the physical reroute. Validate VERSION? (N16R8=1 CHMASK=255), STATUS, HEALTH 2 and physical FAN2/ARGB2 operation. CI is not a hardware test.

## Build environments

- `esp32s3_n16r8_native_usb`: primary default, 8 enabled channels, DC interlock on.
- `esp32s3_n16r8_native_usb_dc_validated`: 8 channels, DC PWM interlock explicitly off, other protections unchanged.
- Older `*_fan2_rerouted` names remain as compatibility aliases and are not required.

**Legacy NVS warning:** a saved pinmap-v1 record referencing GPIO35/36/37 must be rejected on the rerouted build, because these are no longer valid active assignments. Back up settings and migrate the NVS pin map before applying an application-only update, or flash the merged image after backup (overwrites NVS).

## Single combined BIN

The ordinary `ESP32S3-N16R8-NativeUSB-FULL.bin` is now the eight-channel image. It contains bootloader at 0x0, partition table at 0x8000, boot_app0 at 0xE000, and application at 0x10000. Flash this merged image at `0x0`; it overwrites NVS.

Hardware cannot be rerouted solely by flashing; external power should remain disconnected until the signal connections are made.
