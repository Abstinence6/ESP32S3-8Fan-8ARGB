# Windows application for ESP32-S3 Fan & ARGB Controller

Requirements: Windows 10/11; Python 3.11+; optional Libre Hardware Monitor for actual PC temperatures. This is a Python/PySide6 GUI, not a browser UI. No cloud telemetry.

## Install and run

```powershell
cd pc_app
py -3 -m pip install -r requirements.txt
py -3 main.py
```

Enable **Options → Remote Web Server → Run** in [LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/releases). Default local sensor endpoint is `http://127.0.0.1:8085/data.json`; keep access to localhost where possible and do not expose the endpoint to the internet. Depending on hardware/driver, Libre Hardware Monitor may need to run as administrator to detect all sensors. The application shows **every Temperature sensor detected** by Libre Hardware Monitor; it cannot invent unavailable readings.

Connect the **COM port** of the ESP32-S3 at **115200 baud**. The GUI reads all eight stored fan curves, displays current duty/RPM and gives each fan a temperature sensor selector. The default selector is MAX of all available temperatures; an individual CPU, GPU, motherboard or disk sensor may be selected instead. Select a fan on the right and **drag the five dots** to edit the temperature/PWM curve. Click **Save curve in ESP** to store it in flash (NVS).

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
