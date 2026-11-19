# Optional N16R8 FAN2 / ARGB2 physical reroute

**NOT plug-and-play on the original PCB wiring.** Existing N16R8 environments remain 7-channel with CHMASK=253.

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

- esp32s3_n16r8_native_usb_fan2_rerouted: 8 channels, DC fan supply PWM interlock stays locked until hardware qualification.
- esp32s3_n16r8_native_usb_fan2_rerouted_dc_validated: 8 channels, opt-in partial DC fan supply PWM, thermal/fault/sensor guards unchanged.

**Legacy NVS warning:** a saved pinmap-v1 record referencing GPIO35/36/37 must be rejected on the rerouted build, because these are no longer valid active assignments. Back up settings and migrate the NVS pin map before applying an application-only update, or flash the merged image after backup (overwrites NVS).

## Single combined BIN

ESP32S3-N16R8-FAN2-REROUTED-DC-FULL.bin contains bootloader at 0x0, partitions at 0x8000, boot_app0 at 0xE000 and application at 0x10000. Flash this merged image at **0x0** only; it overwrites NVS.

Do not use this image if GPIO8/11/17 are not actually rewired. Standard 7-channel N16R8 images remain the safe choice until hardware is modified.
