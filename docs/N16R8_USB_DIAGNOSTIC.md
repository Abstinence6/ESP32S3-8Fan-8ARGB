# Native USB diagnostic for ESP32-S3-WROOM-1-N16R8

**Diagnostic image only — NOT a fan controller.** It deliberately excludes
normal `main.cpp`, FanController, CoolingController, ARGB, Wi-Fi, MQTT and
all user GPIO handling. The diagnostic firmware will NOT run your fans.
It is designed to distinguish a broken normal firmware/boot from SPI
flash/PSRAM/power problems on a damaged USB-UART development board.

## Why this differs from the old Native USB build

N16R8 has **16 MB QSPI flash** and **8 MB Octal PSRAM**. The previous
`esp32s3_native_usb` build inherits the generic DevKitC-1-N8 board
settings and does NOT explicitly configure 16 MB flash or Octal PSRAM.

The full application's default pins are physically invalid on N16R8:

- FAN2 PWM = GPIO35 (Octal PSRAM DQ6)
- FAN2 TACH = GPIO36 (Octal PSRAM DQ7)
- ARGB2 data = GPIO37 (Octal PSRAM DQS)

Do NOT run the normal fan/ARGB firmware on this module with its existing
GPIO map. A hardware-specific wiring map must be confirmed before
compiling an operational N16R8 image. This diagnostic avoids those pins.

This diagnostic build sets `qio_opi`, 16 MB flash, OPI PSRAM,
DIO flash mode at 40 MHz for conservative boot recovery, a 16 MB partition
layout, and the ESP32-S3 hardware USB CDC/JTAG interface. No USB-UART
chip is needed.

## Safety checks BEFORE connecting USB

Disconnect all 12 V fan/ARGB supplies and fan cabling. The damaged
USB-UART chip may be electrically shorted. With all power disconnected,
measure 5 V-to-GND and 3.3 V-to-GND for shorts. Do not expose a USB
host to a board with a shorted rail. Do not use this diagnostic to
operate cooling hardware, and do not assume a physical fan fail-ON exists.

## Non-destructive integrity test first

Enter ESP32-S3 ROM mode using **BOOT held, press/release EN/RST,
release BOOT**, then connect to the native USB connector. Find the COM
port, replace COM7 below with yours, and extract this ZIP:

```powershell
py -m pip install -U esptool
py -m esptool --chip esp32s3 --port COM7 --baud 115200 flash-id
py -m esptool --chip esp32s3 --port COM7 --baud 115200 read-flash 0x10000 0x1000 first-4k.bin
```

The ROM image SHA mismatch and `TG0WDT_SYS_RST` must be distinguished:
an SHA failure reported by the bootloader occurs before the user's
application can run, whereas changing GPIO35..37 affects normal
application behaviour later. A matching file hash in a downloaded ZIP
does not prove flash reads are reliable.

## Install diagnostic image

First try the **application-only** image if your existing partition
table still has a factory app at 0x10000:

```powershell
py -m esptool --chip esp32s3 --port COM7 --baud 115200 write-flash --flash-mode dio --flash-freq 40m 0x10000 firmware.bin
```

If bootloader or partition layout are incompatible, preserve a backup
of the existing flash/NVS first. Then use all four files to install
a matched 16 MB image set (the original 8 MB partition layout may be
overwritten; this does not automatically erase NVS, but partition
locations can change and data can become inaccessible):

```powershell
py -m esptool --chip esp32s3 --port COM7 --baud 115200 write-flash --flash-mode dio --flash-freq 40m --flash-size 16MB 0x0 bootloader.bin 0x8000 partitions.bin 0xe000 boot_app0.bin 0x10000 firmware.bin
```

**Do not run `erase-flash`** and do not enable PWM or power the PC case
fan rails during this experiment. Verify the written application data
with an esptool verify-flash command appropriate to your installed
esptool version, or read back the region and compare its SHA256.

After reboot, open a serial monitor on the **native USB** COM port at
115200. There is NO `PING`/fan control protocol in this diagnostic.
Every second it prints:

```text
N16R8_DIAG uptime_ms=... reset_reason=... flash_bytes=16777216 psram_bytes=8388608 psram_present=1 psram_test=PASS free_internal_heap=...
```

If its uptime steadily increases, the minimal 16MB/8MB image boots and
the USB path works. If you still see SHA failures in ROM logs or it
resets before printing, first suspect flash read/write or supply integrity.
If PSRAM test fails, inspect the PSRAM configuration / hardware. This
diagnostic cannot prove the damaged board is electrically safe.
