# Windows application for ESP32-S3 Fan & ARGB Controller

## v6.1 reliability hardening

- Automatic Gaming/Work/Night profiles **pause** when live GPU utilization
  is missing. No missing sensor can trigger a time-of-day Silent switch.
- Any explicitly applied fan curve/profile/configuration disables automatic
  profile switching so it does not overwrite the user's manual settings.
- A failed or partial Serial write reports failure instead of claiming a
  successful curve update.
- In-app firmware flashing **blocks** if PC state is ON. When PC power state
  is unknown/disabled/stale, it requires an independently isolated bench,
  its confirmation checkbox, and a typed `СТЕНД` confirmation. The selected
  binary is SHA-256 checked again immediately before writing (including in
  the worker). Firmware flashing still requires a physically fail-ON
  cooling power stage; do not flash while the PC is powered.
- The Windows tray displays ESP/device health and, when opted in,
  deduplicated/rate-limited messages for fan faults and stale temperatures.
  The alert option is under **Сервіс → Автоматизація Windows**.

## v6 additions

- Windows **Task Scheduler elevated autostart**, with explicit UAC consent,
  GUI or headless agent selection, task removal and status check.
- System tray with manual profiles and optional minimize-on-close.
- CPU/GPU MAX sensor source, immediate-rise/delayed-fall temperature filtering
  and opt-in Gaming/Work/Night profiles with 15-minute NVS write guard.
- NWinfo provider manager with adaptive retry and hardware diagnostics.
- ARGB Studio patterns for 1 or 8 zones, separate from OpenRGB.
- Four history graphs: PWM, RPM, temperature and CPU/GPU power.
- DS18B20 physical temperature and source selection via `HTEMP?` / `HTMODE`.
- Backup/restore of allowlisted QSettings without credentials.
- Guarded ESP32-S3 application-only firmware update via packaged esptool.
  **Do not flash while the computer cooled by ESP is powered on.**

Full instructions: [features](../docs/FEATURES_V6.md) and
[DS18B20 wiring](../docs/HARDWARE_TEMPERATURE.md).

## Dashboard interface

The desktop GUI uses seven focused pages instead of one large engineering panel:

- **Огляд**: eight live fan cards, ESP connection, NWinfo local sensors, E1.31, MQTT and PC Power status.
- **Вентилятори**: temperature-only source selection, curves, PWM/RPM and history.
- **Датчики**: searchable temperatures and other live CPU/GPU/RAM/SSD/Intel/AMD metrics.
- **ARGB**: single-zone or all-zone lighting presets; these send only LED
  commands and never overwrite fan curves. Live OpenRGB uses E1.31.
- **Живлення ПК**: monitored PC state and guarded power/force-off actions.
- **Сервіс**: calibration, hardware ARGB, searchable temperature/telemetry tabs, network setup,
  combined configuration presets and diagnostics.
- **Логи**: Serial output and advanced raw command entry.

The firmware protocol, channel numbering, NVS storage, fan power interlock
and stale-temperature fail-safe remain unchanged. A separate **offscreen GUI
smoke test** checks that pages construct, sensor updates reach fan cards and
PC power buttons obey the reported state.


Requirements: Windows 10/11 x64. The packaged EXE has a **bundled NWinfo sensor engine**: no separate LibreHardwareMonitor, LHM HTTP server or Python installation is needed. Source-code execution requires Python 3.11+, the Python requirements and NWinfo CLI in `pc_app/nwinfo/` or the `FANARGB_NWINFO_EXE` environment override. No cloud telemetry.

## Install and run

```powershell
cd pc_app
py -3 -m pip install -r requirements.txt
py -3 main.py
```

The bundled [NWinfo](https://github.com/a1ive/nwinfo) executable reads local
CPU, GPU, SSD, RAM and vendor-specific sensor data through independent
`CPU`, `GPU`, `SMART`, `DIMM`, `INTEL`, `ZEN` and `DISK` probes. The application
does **not** start LHM, a web server or external monitoring services. Each
provider has an independent timeout so an unsupported Intel/AMD/RAM/disk
driver does not prevent GPU/CPU telemetry.

### Expanded sensor catalog

In the dedicated **Датчики** page, the searchable tables are separated into:

- **Температури:** CPU package/core; AMD Zen Tctl/Tdie/Tccd (CCD), core/GFX/L3;
  Intel PCH/chipset, GT/eDRAM and package; GPU temperature; SSD SMART;
  RAM DIMM temperature where the RAM modules and driver actually expose it.
- **Інші показники:** CPU/GPU utilization and frequencies, CPU/GPU powers,
  voltage, GPU fan RPM, GPU memory usage, DIMM load, SSD life and disk I/O
  utilization, latency/IOPS (only when reported by NWinfo).

**Only true live temperature readings can be assigned to fan curves.**
Maximum/threshold/alarm temperatures (Tj Max, T-Control, SMART alarm) are
excluded. Loads, watts, voltages, clocks and RPM are informational only and
cannot accidentally become a temperature target.

Not all motherboard VRM, coolant, DIMM, SSD or GPU hotspot sensors are
exposed by NWinfo for every device. The program lists only values returned
by the detected hardware and drivers; absent sensors are not fabricated.
Additional low-level Intel/AMD/RAM monitoring may require administrator
permissions and approved drivers. The LHM/HWiNFO/GPU-Z providers are not enabled. GPU temperatures come from graphics-driver APIs (AMD ADL2, NVIDIA NVAPI, Intel IGCL). CPU package/core temperatures require privileged access to MSRs via an allowed hardware-access driver and may require running FanARGBControl as Administrator. Hardware/driver support varies. No temperature is invented or replaced with a guessed WMI thermal-zone reading.

Connect the **COM port** of the ESP32-S3 at **921600 baud**. The GUI reads all eight stored fan curves, displays current duty/RPM and gives each fan a temperature sensor selector. The default selector is MAX of all available temperatures; an individual CPU, GPU, motherboard or disk sensor may be selected instead. Select a fan on the right and **drag the five dots** to edit the temperature/PWM curve. Click **Save curve in ESP** to store it in flash (NVS).

Calibration: select one fan, click **Calibrate**, confirm temporary stop at low PWM, then watch 21 steps of PWM and measured RPM. On success the calibration is saved in NVS independently for each fan. **No calibration is saved when all RPM samples are zero** (missing TACH). Calibration/curve writes are not continuous, preventing unnecessary flash wear.

## Safety and persistence

- PC temperatures are streamed over USB every ~2 seconds; the **curve and calibration are stored on the ESP**. Sensor selection is stored locally in Windows QSettings because the PC sensor IDs belong to the host machine.
- If NWinfo cannot access a real temperature sensor: **the app stops sending that fan's temperature**. ESP automatically sets the fan to 100% within 10 seconds (for Auto mode). Manual override intentionally bypasses automatic safety control — use carefully.
- Without the GUI running, the ESP does **not** know CPU/GPU temperatures. Automatic mode remains at full speed by design; independent thermistors or coolant probes could later provide autonomous control.
- The app only reads NWinfo-reported hardware temperatures; it never changes your motherboard's fan configuration.

## Package a Windows EXE

The GitHub Actions `windows-app.yml` workflow packages the app with PyInstaller and uploads the `.exe` as a downloadable workflow artifact. To build locally:

```powershell
py -3 -m pip install -r requirements.txt pyinstaller
powershell -ExecutionPolicy Bypass -File .\build_windows.ps1
# This script downloads the pinned, SHA-256 verified official NWinfoLite zip,
# bundles its native CLI/drivers in the onefile EXE and checks embedded files.
```

Run `dist/FanARGBControl.exe`. No separate monitor or HTTP server is required. The GitHub Actions build verifies both the Python modules and bundled native `nwinfo.exe` inside the final executable. The `prepare_nwinfo.ps1` script pins the official NWinfoLite v1.6.6 SHA-256. Because low-level CPU sensor access depends on an approved Windows driver, the application may need elevated rights; do not disable Windows protections to make readings appear.

## Sensor groups (AVG and MAX)

For **each** fan, the `Датчик для кривої` selector offers:

- `MAX усіх температур` (legacy default): highest available PC temperature.
- An individual CPU/GPU/SSD/other temperature sensor.
- `AVG групи` / `MAX групи`: average or maximum of an **explicitly selected group** of sensors.

Select a fan, press **Вибрати датчики групи**, check the desired sensor IDs, and choose AVG/MAX in its source selector. The group is saved **on the PC** using QSettings (stable NWinfo-based device/attribute IDs), while the five-point fan curve itself remains in ESP32 NVS. If a group is empty **or any selected sensor disappears**, the GUI stops sending temperatures for that fan. The ESP then switches that automatic fan to 100% after the normal 10-second watchdog timeout. No fictional temperature, zero substitute, or silently partial average is used.

NWinfo runs as **independent asynchronous CPU/GPU/SMART/DIMM/INTEL/ZEN/DISK probes**. A slow
SMART disk or CPU driver can time out without hiding fresh GPU readings. The
GPU-only provider runs with `--driver=NONE` (vendor driver APIs do not need
NWinfo's ring-0 driver), while CPU is allowed a longer initialization window.
Each source has a retry delay. A reading older than **7 seconds** is discarded,
so the firmware's 10-second missing-temperature fail-safe still operates.
The GUI displays `частково` and per-provider errors if some readings fail.

If the application reports a CPU timeout but GPU temperatures are present,
try its **Сервіс → Оновити датчики** action. On Windows you can also test
`nwinfo.exe --format=JSON --driver=NONE --sensors=GPU` versus
`nwinfo.exe --format=JSON --sensors=CPU` using the official bundled tool.
Do not disable Windows driver security protections to gain CPU sensor access.

NWinfo runs in background workers so a nonresponsive provider does not freeze the UI or OpenRGB lighting bridge. The old LHM sensor IDs are **not equivalent** to NWinfo IDs: if you previously selected individual sensors, choose their NWinfo counterparts again. Until then the unavailable assignment prevents updates and the firmware retains its 10-second 100% fail-safe.

## OpenRGB and alternative E1.31 transmitters

OpenRGB **E1.31 Devices** send RGB pixels to the local companion over UDP 5568, with 8 individually configured E1.31 zones; the companion forwards per-pixel RGB to the ESP over USB at **921600 baud**, alongside fan-temperature commands. Check **E1.31 → USB, 8 zones** in the ARGB area of the GUI. Each sACN universe maps to the same-numbered ARGB output, using DMX start channel **1**. The GUI must own the ESP COM port; OpenRGB should NOT attempt to open it directly. Firmware returns physical strip lengths with `LEDS` before any binary RGB is forwarded.

This is **manual E1.31 integration**, not automatic HID/USB discovery in OpenRGB and not a native SignalRGB plugin. For a step-by-step OpenRGB configuration and limitations, see [docs/OPENRGB.md](../docs/OPENRGB.md).

## v4: enhanced cooling and optional fan connector types

- Choose a fan in the GUI and set **Type: 2-pin, 3-pin (default), or 4-pin**. One PWM and one TACH ESP32-S3 GPIO per fan. There is no GPIO expander or automatic type detector. The choice must match the physical DC/PWM jumper on the PCB; the type button asks for confirmation. 2/3-pin duty under 100% remains disabled until the intelligent high-side key is verified for 25 kHz motor PWM and `FAN_DC_PWM_VALIDATED=1` is explicitly enabled in firmware. See [`docs/FAN_MODES.md`](../docs/FAN_MODES.md).
- **Smart calibration** (requires valid temperatures and RPM feedback), optional PID and target RPM (not available on 2-pin), RPM/PWM live status, second temperature-based curve, and per-fan calibration migration across firmware versions.
- Sensor sources: MAX all, one sensor, AVG/MAX of a group and weighted average with per-sensor weights (set via **Вибрати датчики групи**).
- Named curve presets **Silent**, **Balanced**, **Performance**, and local **Custom**. Apply to all eight channels with confirmation. Curves are then stored in ESP NVS.
- PWM timeline and CSV export (records kept in memory for the current GUI session, maximum 3600 samples per channel).
- ARGB: per-strip LED count/reversal and a saved approximate global current limit, plus network E1.31/DDP where Wi-Fi credentials have been configured. The current limiter is a *software estimate*, not a replacement for fuses or power supply current limiting.

### Optional background user-logon agent

The packaged `FanARGBControl.exe --headless` runs a **headless companion** after Windows logon. It streams CPU/GPU/SSD temperatures and bridges OpenRGB E1.31 to USB. To register the built EXE in Task Scheduler: `powershell -ExecutionPolicy Bypass -File pc_app/register_agent.ps1`; remove with `pc_app/unregister_agent.ps1`. No separate LHM server is needed. The scheduled agent uses the same bundled NWinfo engine.

This is **not** a Windows Service that operates before user logon. It owns the COM port, so close the agent before opening the GUI. Logging is written to `%LOCALAPPDATA%\FanARGBControl\agent.log`. Missing temperature readings cause the ESP to fall back to 100% fan PWM.

## v5: background agent handoff and MQTT

When `FanARGBControl.exe --headless` is running and owns the selected COM port,
opening the GUI now uses a **localhost 127.0.0.1:42386** serial proxy to the
agent rather than competing for COM. The GUI streams sensor temperatures and
OpenRGB data while attached. When it disconnects, the agent resumes its own
background sensor and OpenRGB tasks; a crashed GUI connection also closes and
releases the proxy. If the agent is not active, GUI opens COM directly.

The GUI has a **Налаштувати MQTT…** dialog for a locally reachable broker.
MQTT runs on ESP32 over Wi-Fi, not on the PC; configure Wi-Fi first. MQTT
Home Assistant Discovery and security considerations are in
[docs/MQTT.md](../docs/MQTT.md). In firmware v5, only 2-pin and 3-pin fan types
are supported; old 4-pin UI descriptions above are historical.
