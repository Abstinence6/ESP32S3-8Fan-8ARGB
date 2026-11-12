# MQTT / Home Assistant — ESP32-S3 8 Fan / 8 ARGB

**Implementation:** MQTT client runs directly on ESP32-S3 Wi-Fi. It does not require the Windows program once Wi-Fi is configured; however, CPU/GPU temperature data still comes from the PC (USB) and disappears if the PC monitoring source is unavailable. MQTT transmits states and accepts **manual fan speed / AUTO**, ARGB controls. Temperature injection via MQTT is deliberately not accepted because a broker could replay stale retained values, defeating the thermal freshness watchdog.

MQTT is **disabled by default**, supports MQTT over TCP/1883 without TLS; restrict it to a trusted LAN/VLAN and use username/password plus broker ACLs. Credentials are stored in ESP NVS, not encrypted.

## Configure over USB serial or Windows GUI

The Windows GUI has an **MQTT / Home Assistant** dialog (in ARGB settings). Alternatively send these lines, substituting your own values:

```text
WIFI SET MyWifi MyWifiPassword
MQTT HOST 192.168.1.10 1883
MQTT AUTH my_mqtt_user my_mqtt_password
MQTT PREFIX esp32s3/fanargb
MQTT ENABLE 1
MQTT STATUS
```

Do not paste real credentials into logs or screenshots. SSID/password, broker names and MQTT auth cannot contain spaces in the current serial protocol. To disable: `MQTT ENABLE 0`. The `MQTT STATUS` response intentionally excludes the password. Broker and Wi-Fi configuration survive restarts in NVS.

## Topics (default prefix `esp32s3/fanargb`)

| Topic suffix | Direction | Format / meaning |
|---|---|---|
| `status` | ESP → broker | `online` / `offline` MQTT Last Will; retained |
| `fan/1/pwm` | ESP → broker | Applied duty in percent 0..100, retained |
| `fan/1/rpm` | ESP → broker | 0 when no trusted TACH reading, retained |
| `fan/1/temperature` | ESP → broker | Actual °C with one decimal (e.g. `45.5`), or `unknown` when sensor data are stale; retained |
| `fan/1/type` | ESP → broker | 2 or 3 |
| `fan/1/tach_valid` | ESP → broker | 1 only for fresh trusted 3-pin TACH |
| `fan/1/fault`, `fan/1/rejected` | ESP → broker | `1` for latched fault; `0` when no fault is latched (3-pin); `unknown` for 2-pin without current/stall feedback. Rejected = 0/1. |
| `fan/1/mode` | ESP → broker | `auto`, `manual`, `calibration`, `rpm` |
| `fan/1/state` | ESP → broker | `ON` / `OFF` |
| `fan/1/set` | broker → ESP | `AUTO` or numeric 0..100 (manual duty) |
| `fan/1/power/set` | broker → ESP | `ON` (100%) / `OFF` (0%) |
| `argb/1/state` | ESP → broker | `off`, `solid`, `rainbow`, `external` |
| `argb/1/set` | broker → ESP | `OFF`, `RAINBOW`, or `#RRGGBB` |
| `argb/1/brightness/set` | broker → ESP | Integer 0..255 |
| `dc_pwm_validated` | ESP → broker | 0 by default; explicit validated hardware compile flag only |

Replace `1` with 1..8. MQTT receives commands in a FreeRTOS network task and applies them in the regular control loop using the **same safety checks** as USB; rejected requests never bypass the DC PWM interlock.

**Important:** Never retain command messages (`fan/+/set`, `power/set`, `argb/+/set`); retained commands may replay after reconnect. Broker ACLs should grant control-write access only to trusted accounts. 2-pin has no independent feedback, so its `fault=0` means no *latched firmware fault*, NOT proof that a fan is rotating.

## Home Assistant

The broker receives retained MQTT discovery configurations under `homeassistant/` for 8 `fan` entities, 8 RPM sensors, 8 temperature sensors and 8 firmware-fault binary sensors, with stable per-device IDs derived from the ESP chip MAC. Ensure HA MQTT integration is connected to the **same broker** and discovery enabled. MQTT fan entities offer duty, power commands and availability; with the power-PWM guard unvalidated, speed changes below 100% are intentionally rejected. Home Assistant may briefly show previous retained states until the next firmware publish (~1 s).

Example Mosquitto command (no retained flag):

```sh
mosquitto_pub -h 192.168.1.10 -u my_mqtt_user -P 'my_mqtt_password' -t esp32s3/fanargb/fan/1/set -m AUTO
```

There is no TLS/mTLS, automatic OTA, or secure network provisioning in this revision. For remote access, use the LAN/VPN and broker controls instead of exposing TCP/1883 to the internet.
