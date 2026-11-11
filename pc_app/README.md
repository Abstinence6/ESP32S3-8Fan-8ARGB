# Windows application for ESP32-S3 Fan & ARGB Controller

Requirements: Windows 10/11; Python 3.11+; optional Libre Hardware Monitor for actual PC temperatures. This is a Python/PySide6 GUI, not a browser UI. No cloud telemetry.

## Install and run

```powershell
cd pc_app
py -3 -m pip install -r requirements.txt
py -3 main.py
```

Enable **Options → Remote Web Server → Run** in [LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/releases). Default local sensor endpoint is `http://127.0.0.1:8085/data.json`; keep access to localhost where possible and do not expose the endpoint to the internet. Depending on hardware/driver, Libre Hardware Monitor may need to run as administrator to detect all sensors. The application shows **every Temperature sensor detected** by Libre Hardware Monitor; it cannot invent unavailable readings.

Connect the **COM port** of the ESP32-S3 at **921600 baud**. The GUI reads all eight stored fan curves, displays current duty/RPM and gives each fan a temperature sensor selector. The default selector is MAX of all available temperatures; an individual CPU, GPU, motherboard or disk sensor may be selected instead. Select a fan on the right and **drag the five dots** to edit the temperature/PWM curve. Click **Save curve in ESP** to store it in flash (NVS).

Calibration: select one fan, click **Calibrate**, confirm temporary stop at low PWM, then watch 21 steps of PWM and measured RPM. On success the calibration is saved in NVS independently for each fan. **No calibration is saved when all RPM samples are zero** (missing TACH). Calibration/curve writes are not continuous, preventing unnecessary flash wear.

## Safety and persistence

- PC temperatures are streamed over USB every ~2 seconds; the **curve and calibration are stored on the ESP**. Sensor selection is stored locally in Windows QSettings because the PC sensor IDs belong to the host machine.
- A temperature sensor can disappear or LHM can stop: **the app stops sending that fan's temperature**. ESP automatically sets the fan to 100% within 10 seconds (for Auto mode). Manual override intentionally bypasses automatic safety control — use carefully.
- Without the GUI running, the ESP does **not** know CPU/GPU temperatures. Automatic mode remains at full speed by design; independent thermistors or coolant probes could later provide autonomous control.
- The app only reads LHM sensors; it never changes your motherboard's fan configuration.

## Package a Windows EXE

The GitHub Actions `windows-app.yml` workflow packages the app with PyInstaller and uploads the `.exe` as a downloadable workflow artifact. To build locally:

```powershell
py -3 -m pip install -r requirements.txt pyinstaller
py -3 -m PyInstaller --clean --noconfirm --windowed --onefile --name FanARGBControl main.py
```

Run `dist/FanARGBControl.exe`. Libre Hardware Monitor is a separate dependency.

## Sensor groups (AVG and MAX)

For **each** fan, the `Датчик для кривої` selector offers:

- `MAX усіх температур` (legacy default): highest available PC temperature.
- An individual CPU/GPU/SSD/other temperature sensor.
- `AVG групи` / `MAX групи`: average or maximum of an **explicitly selected group** of sensors.

Select a fan, press **Вибрати датчики групи**, check the desired sensor IDs, and choose AVG/MAX in its source selector. The group is saved **on the PC** using QSettings (stable LibreHardwareMonitor SensorIds), while the five-point fan curve itself remains in ESP32 NVS. If a group is empty **or any selected sensor disappears**, the GUI stops sending temperatures for that fan. The ESP then switches that automatic fan to 100% after the normal 10-second watchdog timeout. No fictional temperature, zero substitute, or silently partial average is used.

Sensor HTTP polling runs in a background thread so a nonresponsive LibreHardwareMonitor does not freeze the UI or OpenRGB lighting stream.

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

The packaged `FanARGBControl.exe --headless` runs a **headless companion** after Windows logon. It streams CPU/GPU/SSD temperatures and bridges OpenRGB E1.31 to USB. To register the built EXE in Task Scheduler: `powershell -ExecutionPolicy Bypass -File pc_app/register_agent.ps1`; remove with `pc_app/unregister_agent.ps1`. User must also run LibreHardwareMonitor web server in their session.

This is **not** a Windows Service that operates before user logon. It owns the COM port, so close the agent before opening the GUI. Logging is written to `%LOCALAPPDATA%\FanARGBControl\agent.log`. Missing LHM readings cause the ESP to fall back to 100% fan PWM.
