# Operational full-flash image for ESP32-S3-WROOM-1-N16R8

This is the **normal ESP32S3-8Fan-8ARGB application**, not the diagnostic
image. It supports native hardware USB CDC, cooling control, MQTT, Windows
FanARGBControl and ESP32-rendered RGB scenes.

Target hardware: **16 MB QSPI flash, 8 MB Octal (OPI) PSRAM**.
Build: `esp32s3_n16r8_native_usb` in PlatformIO. Outputs 0x0 merged image.

## Hardware constraints / available channels

The PCB mapping for *logical channel 2* includes GPIO35 (FAN2 PWM),
GPIO36 (FAN2 TACH) and GPIO37 (ARGB2), which are **internal PSRAM** pins on
N16R8. Even if external traces are unsoldered, no firmware may use these
three pins for GPIO. This build **disables all three roles** and makes
no calls to LEDC, TACH interrupt or NeoPixel on those pins. The firmware
still reports eight logical channels for compatibility, with
`AVAILABLE=0` for channel 2. All other seven retain their old routing
and normal (still unvalidated!) safety interlocks. `VERSION?` includes
`N16R8=1 CHMASK=253`.

Do not reattach external circuits to GPIO35/36/37. FAN2/ARGB2 cannot work
until physically rerouted and the firmware reviewed for the new wiring.
The other channels are NOT claimed bench-qualified; default
`FAN_DC_PWM_VALIDATED=0` prohibits partial DC motor duty.

## DC-unlocked candidate (not hardware-validated)

The user previously reported checking the power stage, but this was not
independently electrically validated. The user now reports the controller is
damaged; the cause is unknown. The `esp32s3_n16r8_native_usb_dc_validated`
environment is a compile-time candidate name, not evidence of validation. It
inherits the N16R8 native-USB environment and adds **only**
`FAN_DC_PWM_VALIDATED=1`. Existing environments and `BoardConfig.h` still
default to DC validation off. This flag enables partial DC motor duty on every
available 2/3-pin fan channel, not just FAN1; it does not qualify hardware.

```sh
pio run -e esp32s3_n16r8_native_usb_dc_validated
build=.pio/build/esp32s3_n16r8_native_usb_dc_validated
cp ~/.platformio/packages/framework-arduinoespressif32/tools/partitions/boot_app0.bin "$build/boot_app0.bin"
python3 scripts/merge_flash_images.py --directory "$build" --output "$build/ESP32S3-N16R8-NativeUSB-DC-VALIDATED-FULL.bin"
```

The application is `$build/firmware.bin` at **0x10000**; the combined
`ESP32S3-N16R8-NativeUSB-DC-VALIDATED-FULL.bin` is at **0x0**, using the same
component offsets below. Merged flashing **still overwrites NVS**. Prefer an
application-only update with the matching existing bootloader/partition layout
when preserving settings. Building/merging does not flash or access hardware.
`VERSION?` should include `DC_READY=1`, `N16R8=1` and `CHMASK=253` after a later
verified installation. Missing/stale temperature, overheat, startup/restart and latched
fault protections still override manual requests, including 0% stop requests.

### Other disabled pins / features (not unlocked)

- **FAN2 PWM GPIO35, TACH GPIO36, ARGB2 GPIO37:** actual internal Octal PSRAM
  conflict, not a test gate. Channel 2 remains unavailable even with DC validated.
  The N16R8 pin-map guard also rejects GPIO33..37 for active channel assignments.
- **PC power button/sense:** `PC_POWER_ENABLED=0`, `PC_POWER_GPIO=-1`,
  `PC_SENSE_GPIO=-1`. Opt-in hardware feature with no confirmed wiring or free
  pins assigned, not a DC test gate. No output/sense GPIO is initialized.
- **Local DS18B20:** `HARDWARE_TEMP_ENABLED=0`, `HARDWARE_TEMP_GPIO=-1`.
  Opt-in hardware feature awaiting an explicitly verified spare pin and sensor;
  USB temperature telemetry remains available without it.
- **Pin-map restrictions:** GPIO19/20 stay dedicated to native USB; GPIO26..32
  to flash; GPIO22..25 are not usable ESP32-S3 GPIOs. GPIO43/44 (UART0) and
  GPIO0/3/45 (boot straps) remain conservatively reserved. GPIO46 is allowed
  only in its existing ARGB7 slot because of strapping risk; it is not disabled
  in that slot. Auxiliary pin checks also reject occupied fan/ARGB pins.
- **Fan features:** only 2/3-pin control exists; 4-pin mode and automatic fan-type
  detection are unsupported by this design, not test locks. RPM feedback is
  unavailable for 2-pin fans; calibration/PID still require their existing
  temperature, TACH and calibration qualifications. No additional channel is
  software test-blocked beyond the DC qualification and N16R8 channel-2 guard.

## One full BIN at address 0x0

File: `ESP32S3-N16R8-NativeUSB-FULL.bin`. It includes:

| Offset | Included contents |
| --- | --- |
| 0x0000 | native USB N16R8 bootloader |
| 0x8000 | 16 MB partition table |
| 0xE000 | boot_app0 |
| 0x10000 | operating application firmware |

**WARNING: FLASHING THIS SINGLE CONTIGUOUS BIN WILL ERASE THE EXISTING
NVS CONFIGURATION in the 0x9000..0xDFFF flash gap.**
This includes saved curves, MQTT credentials, temperature mappings and
ARGB scenes. Make a flash or NVS backup *first* if those settings matter.
We include four separate images in the ZIP for cases where preserving
NVS is required, but they are not needed to flash the merged file.
Do not use `erase-flash` unnecessarily.

## Flash via native USB ESP32-S3

Disconnect 12 V fans and 5 V ARGB supplies; inspect the failed USB-UART
converter for shorts and check 5 V/3.3 V rails before plugging the board
into a PC. Enter ROM bootloader (BOOT held, tap EN, release BOOT).

Using the installed Python esptool and the correct native USB COM:

```powershell
py -m esptool --chip esp32s3 --port COM7 --baud 115200 write-flash --flash-mode qio --flash-freq 80m --flash-size 16MB 0x0 ESP32S3-N16R8-NativeUSB-FULL.bin
```

The **entire combined image** must be written at **0x0**, never at 0x10000.
After flashing, tap EN/RST once and select the new native USB COM port
in the Windows FanARGBControl application. Read `VERSION?`, `PING`
and `STATUS`; you should see `N16R8=1 CHMASK=253`. FAN2 and ARGB2
will remain unavailable. If the earlier SHA or watchdog boot errors
persist with this complete matched bootloader set, suspect flash read
integrity, USB/PSRAM hardware, power supply or boot straps, not a
misplaced standalone `firmware.bin`. The software was compile/test
verified, not hardware-verified on the damaged board.
