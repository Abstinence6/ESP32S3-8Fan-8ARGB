# N16R8 DC-unlocked candidate — release handoff

## Status and limits

This is a build-artifact handoff, **not a hardware-qualified release**. The
user previously said the power stage had been checked; that report was not
independently electrically validated. The user now reports the controller is
damaged. The cause is unknown, and this documentation does not attribute the
damage to firmware or any other cause. The candidate was not flashed or
runtime-tested by the agent; the native USB COM port was unavailable. No
physical flash or runtime test is claimed.

The environment name `esp32s3_n16r8_native_usb_dc_validated` and the macro
`FAN_DC_PWM_VALIDATED=1` describe a compile-time unlock only. They do not mean
the hardware has been validated or is safe. Do not reconnect or power the
damaged controller for this handoff. Electrical inspection and qualification
must precede any use; those are outside this release documentation scope.

## Candidate build

From the repository root, build and merge with the project's PlatformIO and
Python dependencies installed:

```sh
pio run -e esp32s3_n16r8_native_usb_dc_validated
build=.pio/build/esp32s3_n16r8_native_usb_dc_validated
cp ~/.platformio/packages/framework-arduinoespressif32/tools/partitions/boot_app0.bin "$build/boot_app0.bin"
python3 scripts/merge_flash_images.py --directory "$build" --output "$build/ESP32S3-N16R8-NativeUSB-DC-VALIDATED-FULL.bin"
```

The candidate inherits `esp32s3_n16r8_native_usb` and adds only
`FAN_DC_PWM_VALIDATED=1`. The macro enables partial DC duty on available 2/3-pin
fan channels. Standard environments and `BoardConfig.h` default to
`FAN_DC_PWM_VALIDATED=0`. A successful build establishes compilation only.

## Artifact manifest

| Artifact | Flash address | Size | SHA-256 |
| --- | ---: | ---: | --- |
| `.pio/build/esp32s3_n16r8_native_usb_dc_validated/firmware.bin` | `0x10000` | 828064 bytes | `b9910c01d4c12edfaac84137cf19899ccdf0e02585f161eea95593b7470b65e8` |
| `.pio/build/esp32s3_n16r8_native_usb_dc_validated/ESP32S3-N16R8-NativeUSB-DC-VALIDATED-FULL.bin` | `0x0` | 893600 bytes | `df9a4e65ad73dfcb29c3b7c89520718bc00a8f494402b9c75c2f936abafc97ee` |

The full image contains the bootloader at `0x0000`, partition table at `0x8000`,
`boot_app0` at `0xE000`, and application at `0x10000`. Verify locally that
artifact names, sizes, and SHA-256 hashes match this manifest before considering
any later authorized use; a mismatch means stop and investigate, not flash.

## Protections and locked pins

The DC unlock does not remove firmware thermal, startup/restart, or latched-fault
protections. Missing or stale temperature, overheat, and latched faults continue
to override manual requests, including a 0% stop request. DC unlock covers only
available channels and does not establish hardware fail-safe behavior.

GPIO35 (FAN2 PWM), GPIO36 (FAN2 TACH), and GPIO37 (ARGB2) remain disabled due to
the N16R8 internal Octal PSRAM conflict. Channel 2 remains unavailable
(`CHMASK=253`); these pins are **not unlocked** by the candidate. Do not attach
external circuitry to them. The existing native-USB, flash, boot-strap, and
other pin-map restrictions remain unchanged. PC power and local DS18B20 features
also remain disabled in this environment.

## Flashing and recovery cautions

These are artifact addresses, not an instruction to flash the damaged board.
Do not flash or power that controller as part of this handoff. If a separately
inspected and approved target is ever used, first confirm the exact board,
power stage, wiring, and matching bootloader/partition layout, and follow the
project's recovery procedure. The `firmware.bin` is an application-only image
for `0x10000` and requires the matching existing bootloader and partition layout.
The merged full image is written at `0x0`; it **overwrites NVS**, including
saved settings and credentials. Back up NVS/configuration first if preservation
matters. Do not erase flash unnecessarily. Building and merging artifacts do
not access or validate hardware.

## Checks performed / not performed

The coordinator independently recomputed both artifact SHA-256 hashes and sizes;
they match the manifest above. Native firmware tests passed. The Python suite
ran 178 tests successfully with 27 optional GUI/NumPy tests skipped because their
dependencies were absent. Documentation changes do not flash the board. No
physical flash or runtime test of this candidate, or electrical validation, was
performed. The reported controller damage has no established cause.
