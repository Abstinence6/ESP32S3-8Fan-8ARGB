# FanARGB v6: integrated Windows + ESP32-S3 features

This is an **opt-in feature update**, not a board validation certificate.

## Quick guide

1. Use the latest packaged \`FanARGBControl.exe\` (no separate Python/LHM).
2. On **Датчики**, select NWinfo CPU/GPU/SMART/DIMM/INTEL/ZEN/DISK
   providers. Unavailable providers use adaptive 8–120 s retry backoff.
3. On **Вентилятори**, select \`MAX(CPU,GPU)\` to react only to available
   CPU/GPU temperatures (not SSD/DIMM). Temperature smoothing retains
   immediate rises, a hold period before decreases and a bounded fall rate.
4. On **Сервіс → Автоматизація Windows**, optionally enable Gaming/Work/Night
   profiles; no automatic curve changes until you confirm. Gaming when GPU
   utilization ≥70%, Work/Balanced in ordinary use, Night/Silent 23:00–07:00.
   Each choice needs 40 s stability and curve writes are at least 15 min
   apart. Profile automation works in the GUI and in the connected headless
   agent, never simultaneously controlling the COM port.
5. On **ARGB**, use ARGB Studio for Gradient/Wave/Breathe/Chase/Static,
   selected zone or all eight. It streams the existing binary RGB protocol;
   OpenRGB E1.31 and ARGB Studio do not own LEDs concurrently. Hardware RGB
   current limit still applies.
6. On **Сервіс**, see health diagnoses (read-only HEALTH), four time-series
   charts (PWM/RPM/temperature/CPU–GPU power), configuration backups, and
   guided firmware-only flashing. Some functions require a connected ESP32.
7. Choose **Згортати в трей** to keep temperature updates running after
   closing the main window. The tray context menu opens the GUI and offers
   profiles with explicit confirmation.

## Autostart with administrator privileges

At **Сервіс → Автоматизація Windows**, choose **GUI** or **headless agent**,
then click **Увімкнути автозапуск (адмін)**. A Windows **UAC dialog** appears
and must be accepted. Task Scheduler registers \`FanARGBControl Elevated\` as
an **Interactive current-user** task with \`RunLevel Highest\` at logon.
No passwords, SYSTEM task, UAC bypass or registry autorun hacks are used.
The **Вимкнути автозапуск** button removes just this named task, again via
UAC. Installation/removal status must be **rechecked**, not assumed.

Keep the EXE at a trusted, stable location with appropriate file write
permissions; running a replaceable binary elevated on every logon is risky.
Do not enable both this scheduled task and the older
\`register_agent.ps1\` task at once. When choosing **headless**, the Windows
GUI can connect through the existing local serial proxy; stop that agent
before using the firmware flasher because it owns the COM port.

## Optional physical temperature sensor

See [HARDWARE_TEMPERATURE.md](HARDWARE_TEMPERATURE.md).

DS18B20 has three per-fan modes:

- **PC**: use only PC temperatures supplied by GUI/agent.
- **LOCAL**: use the wired DS18B20 even if Windows is offline.
- **BACKUP**: use PC temperature while live; switch to DS18B20 when PC
  updates stop for 6 seconds.

DS18B20 is **disabled by default** because no free ESP32-S3 pin has been
confirmed for the actual PCB. GPIO18 is a **conditional example** only.
The device needs 3.3 V supply plus 4.7 kΩ DQ pull-up, not 5 V.
Modes are persisted to NVS only on explicit change. The physical sensor's
conversion is nonblocking; missing/invalid readings never reset the
10-second fail-safe. \`DUAL\` still needs a fresh second source.

\`HTEMP?\`, \`HTMODE? ch\`, and \`HTMODE ch PC|LOCAL|BACKUP\` are new read/write
serial commands; GUI exposes them on the **Датчики** page.

## Firmware update + backups

\`Сервіс\` offers export/import of the **PC app's settings** (profiles,
sensor assignments, animation presets and automation settings) without
passwords or executable paths. This is **not** a full ESP32 NVS backup.

The firmware tool accepts a **user-selected ESP32 image** and writes only
the application partition at **0x10000** using bundled esptool. It
does not replace the bootloader, partition table or erase NVS. It refuses
to flash when the PC Power state explicitly says the PC is ON, and requires
manual confirmation even when state is unknown. During flashing the serial
connection is closed, **temperature telemetry stops**, and only an
independently verified physical fail-ON fan driver can guarantee cooling.
Never flash while the computer being cooled is running. Use a safe isolated
bench or power the fans independently, and verify flash layout/module first.

\`VERSION?\` reports firmware interface v6 and whether DC PWM and DS18B20
are compiled in. An older firmware might still support fan/RGB control,
but cannot process the new DS18B20 commands.

## Verification and limitations

GitHub Actions runs host C++ safety tests, Python model tests, offscreen
PySide6 navigation tests, regular PlatformIO firmware build and an
additional compile for optional DS18B20 enabled on example GPIO18. Windows
CI bundles NWinfo and esptool and verifies Python modules in the final EXE.

Neither CI nor software can verify actual **PWM high-side MOSFET fail-ON,
GPIO35–37 PSRAM conflicts, GPIO46 boot strapping, DS18B20 wiring, CPU
ring-0 driver access, or Serial port reassignment** on your computer.

\`FAN_DC_PWM_VALIDATED=0\` and \`PC_POWER_ENABLED=0\` remain the shipping
defaults. **Do not override safety guards just to see lower PWM values**.
