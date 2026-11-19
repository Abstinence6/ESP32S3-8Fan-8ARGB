# ESP32-S3: recovery when the USB-to-UART chip has failed

This project supports an **independent Native USB CDC** firmware image
in addition to the original USB-to-UART build. The ESP32-S3 hardware
USB Serial/JTAG interface communicates directly over **GPIO19 (USB D-)**
and **GPIO20 (USB D+)**. The external CP210x/CH34x USB-to-UART chip is
not required for this connection.

## Before plugging into your PC

1. Disconnect **12 V fans**, external ARGB 5 V, the damaged UART connector
   and other external power supplies. The MCU must not reboot under
   an active PC cooling load unless the physical fan fail-ON is verified.
2. With power removed, check for **short circuits on 5 V, 3.3 V and GND**
   from the burnt converter. A shorted power rail can damage the PC USB
   port even while using the other connector. If damaged hardware remains
   electrically shorted, firmware cannot repair it.
3. Confirm your exact module is ESP32-S3 and the second connector is wired
   to native USB (often labelled **USB**, not **UART**). The default firmware
   still uses UART; choose only the `esp32s3_native_usb` image.

## Flash from the **native USB** connector (Windows)

Use a known working **data-capable** USB cable directly connected to the PC.

1. Hold **BOOT** on the ESP32-S3; press and release **EN/RST**; release
   BOOT. This enters the ROM download mode without the broken UART chip.
2. In Windows Device Manager, look for an **Espressif USB JTAG/serial debug
   unit** / serial port (for example `COM7`). If there is no native USB
   device, check the cable, D+/D- wiring and board power first.
3. Install [Python 3](https://www.python.org/downloads/) and esptool:

   ```powershell
   py -m pip install --upgrade esptool
   ```

4. Extract the `ESP32S3-8Fan-8ARGB-native-USB-CDC` ZIP. In PowerShell,
   change directory to the folder holding `firmware.bin` and flash the
   application using **your** COM number:

   ```powershell
   py -m esptool --chip esp32s3 --port COM7 --baud 460800 write_flash 0x10000 firmware.bin
   ```

   This firmware-only command assumes the board already contains the
   matching ESP32-S3 bootloader and partition layout. If the flash is
   blank or the partition layout is incompatible, use the four supplied
   images (this overwrites the existing bootloader/partition layout;
   do not erase NVS unless intentionally resetting configuration):

   ```powershell
   py -m esptool --chip esp32s3 --port COM7 --baud 460800 write_flash 0x0 bootloader.bin 0x8000 partitions.bin 0xe000 boot_app0.bin 0x10000 firmware.bin
   ```

5. Press **EN/RST** once after flashing. The native USB port should
   enumerate as a COM port. Open FanARGBControl.exe, refresh port list
   and select the new Espressif COM number. It uses the same line and
   binary RGB protocol over `Serial`. In a serial monitor, send
   `PING\n` to receive the existing `PONG` response.
6. If Windows does not show a COM port, disconnect, hold BOOT, press
   EN/RST and confirm the **ROM download** COM port appears again. This
   allows recovery even if the application firmware does not run.

### PlatformIO

```bash
pio run -e esp32s3_native_usb
pio run -e esp32s3_native_usb -t upload --upload-port COM7
```

This environment inherits the unchanged 8-fan/8-ARGB firmware and sets:

```ini
-D ARDUINO_USB_CDC_ON_BOOT=1
-D ARDUINO_USB_MODE=1
```

It uses the built-in **hardware CDC/JTAG** interface, not a second
software UART and not a different GPIO pin assignment. The original
`pio run -e esp32s3` build remains unchanged for boards whose external
USB-to-UART chip works.

### Safety/limitations

- USB CDC is a **communications** interface only. CPU/GPU temperatures
  from Windows still require FanARGBControl/agent or another configured
  source; without them the existing 10-second fail-safe requests 100%.
- The 2/3-pin high-side DC driver remains **unvalidated**, so
  `FAN_DC_PWM_VALIDATED=0` must stay in force. Physical fan fail-ON
  during MCU reset/brownout must still be provided by external hardware.
- This was verified by firmware compilation and host tests, **not** by
  physical testing on your damaged board. If GPIO19/GPIO20 or USB PHY
  are damaged, no firmware can make that native USB port work.

## N16R8 / 8 MB Octal PSRAM warning

**ESP32-S3-WROOM-1-N16R8 is NOT compatible with the generic 8-fan GPIO map.**
GPIO35/36/37 connect to the module's Octal PSRAM, but the default
firmware maps FAN2 PWM, FAN2 TACH and ARGB2 to those same pins. Do not
operate the ordinary Native USB build on this hardware until the PCB
wiring is verified and remapped. Use the isolated, output-free
[N16R8 USB diagnostic](N16R8_USB_DIAGNOSTIC.md) to verify boot and
USB/Flash/PSRAM first.
