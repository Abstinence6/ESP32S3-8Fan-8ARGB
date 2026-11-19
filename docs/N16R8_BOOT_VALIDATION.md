# N16R8 native-USB: first physical boot acceptance

This procedure checks the **standard** `esp32s3_n16r8_native_usb` image on
ESP32-S3-WROOM-1-N16R8 (16 MB QSPI Flash / 8 MB Octal PSRAM). It is not a
firmware change and **is not evidence of hardware validation** until someone
performs and documents the measurements and boot observations.

## 0. Do not power a damaged board without inspection

The external USB-UART chip has failed. Leave **all fan 12 V and ARGB 5 V
peripherals disconnected**, and first inspect the failed chip and board for
shorts. With power removed, check resistance/continuity of USB 5 V and 3.3 V
rails to GND; with a current-limited bench supply, check that 3.3 V is stable
before connecting native USB to a PC. Do not connect a board with a suspected
short directly to a PC USB port. Check BOOT/EN and GPIO46 strapping loads.

GPIO35/36/37 are wired to Octal PSRAM even with external traces removed.
FAN2 PWM/TACH and ARGB2 **must remain disabled**. GPIO19/20 are native USB.
Do not use the opt-in `..._dc_validated` firmware for this baseline test;
its compile-time DC unlock is not proof of qualified motor-power hardware.

## 1. Obtain the correct matched release

Use the **standard** artifact `ESP32S3-N16R8-NativeUSB-FULL` from the successful
PlatformIO workflow, not the diagnostic or the DC-unlocked opt-in artifact.
Extract the ZIP; keep `ESP32S3-N16R8-NativeUSB-FULL.bin` and `manifest.json`
together. The file includes all four components at fixed offsets:

| Flash offset | Contents |
| --- | --- |
| `0x0000` | bootloader |
| `0x8000` | partitions |
| `0xE000` | boot_app0 |
| `0x10000` | application |

Read-only check (from the extracted artifact directory, if it includes the
packaged preflight script):

```powershell
py .\preflight_n16r8_image.py --image .\ESP32S3-N16R8-NativeUSB-FULL.bin --manifest .\manifest.json
```

This checks offsets, SHA-256, target environment and disabled-channel metadata,
and refuses application-only files and the opt-in DC-unlocked candidate. It
**does not flash**. A matching manifest is unsigned and cannot independently
establish authenticity. Compare its commit to the expected GitHub Actions run.

The earlier confirmed standard image at commit `fe81b5828814eab790d12d5df1f77fc7e562ddc6`
was 893616 bytes with SHA-256
`62b35a6207d50b98db95443983fcc8f67bc208bb3d8a1ba6b0262c5f097ccc0c`.
If using that exact older standalone image with no manifest, pass that hash
using `--expected-sha256` instead of `--manifest`.

## 2. Save settings and flash ONLY after electrical clearance

The merged image is a contiguous file from **0x0** to the end of the app;
its `0xFF` gap from `0x9000` through `0xDFFF` **overwrites NVS** (saved
Wi-Fi/MQTT profiles, fan curves, ARGB geometry, credentials, etc.).
Do not erase the entire flash as a troubleshooting shortcut. Replace `COM7`
with the actual native USB ROM port in Device Manager.

Enter ROM download mode: hold BOOT, tap EN, release BOOT. With esptool installed:

```powershell
py -m esptool --chip esp32s3 --port COM7 --baud 115200 flash-id
py -m esptool --chip esp32s3 --port COM7 --baud 115200 read-flash 0x0 0x1000000 backup-before-fullflash.bin
py -m esptool --chip esp32s3 --port COM7 --baud 115200 write-flash --flash-mode qio --flash-freq 80m --flash-size 16MB 0x0 ESP32S3-N16R8-NativeUSB-FULL.bin
```

**NEVER** flash a standalone `firmware.bin` at `0x0`: that is the earlier
confirmed cause of the corrupted boot layout. A standalone application belongs
at `0x10000`, only when the resident bootloader and partition table match.

For read-back diagnosis, capture the esptool output and use its flash
verification/read-back facilities before changing application code. Flash
mode/size settings can affect the image header; compare the actual bytes or
hashes with care rather than assuming a different read-back hash means bad flash.

## 3. Observe boot and Native USB, with peripherals still disconnected

Press EN, then record the USB port enumeration and all available serial logs.
ROM messages may be on UART0 rather than the same native USB COM port; absence
of early ROM text on CDC alone is not proof of a bad boot. Test the application
protocol through the new COM port:

```text
PING
VERSION?
STATUS
HEALTH 2
```

Expected: repeated `PING` responses, `VERSION?` reporting `N16R8=1 CHMASK=253`,
and channel 2 reported unavailable (`AVAILABLE=0`). Power-cycle and reset a few
times, observing for `SHA-256 comparison failed`, `TG0WDT_SYS_RST`, unexpected
ROM download mode, PSRAM errors, USB disconnects, or thermal fault behavior.
A stable application needs more than one successful `PING` after boot.

**Pass for this stage:** successful verified write, stable native USB startup,
several normal cold and warm resets, and repeatable protocol responses with
channel 2 disabled. Record the exact CI commit, binary SHA, boot/reset logs,
measured rail voltages and reset reason. No fans or LEDs are qualified by this.

**Fail:** if SHA mismatch or watchdog reset repeats on the full matched image,
stop changing fan/ARGB logic and investigate BootROM, flash read integrity,
flash mode/frequency, Octal PSRAM, USB lines, strapping and 3.3 V supply first.
Do not treat CI success as board-level proof.