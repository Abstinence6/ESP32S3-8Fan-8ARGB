# MQTT and Home Assistant — ESP32-S3 v8

> **Windows configuration (v8):** Connect ESP32-S3 via USB to
> `FanARGBControl.exe`, open **ESP32 → MQTT / Home Assistant**, enter
> broker, port, username/password, choose MQTT and Discovery, then save.
> ESP32 confirms every operation and the GUI reads the stored state
> back. No Serial Monitor or manual commands are needed. See
> [PC configuration](PC_CONFIGURATION.md) for details.
>
> The serial commands shown below remain for testing and older firmware;
> v8 adds `MQTT CONFIG?`, `MQTT BROKER`, `MQTT AUTHHEX`,
> `MQTT HA ON|OFF`, and `MQTT CLEAR`.
MQTT is **optional and disabled until a broker is configured**. ESP32 must first connect to
Wi-Fi (existing `WIFI` serial configuration), and must be able to reach the
local MQTT broker. Transport uses TCP MQTT on port 1883 by default, through
PubSubClient 2.8; no separate MQTT gateway on the Windows PC is required.
The ESP32 uses MQTT even when the Windows GUI is not running.

## Setup (USB serial at 921600 baud)

```text
WIFI SET <ssid> <password>
MQTT HOST 192.168.1.10 1883
MQTT AUTH homeassistant your-password
MQTT ON
MQTT?
```

`MQTT HOST` also enables the MQTT client. Use `MQTT AUTH CLEAR` to clear saved credentials, `MQTT OFF` to disable MQTT.
`MQTT?` prints broker, port, authenticated flag, connection status and base topic,
**never the saved password**. The Windows GUI has a **Налаштувати MQTT…** button.
Configuration resides in ESP32 NVS; reconnect is automatic with a 10 s backoff.
If broker unavailable, cooling still runs using the last known temperature
until the existing 10 s stale-data safety threshold expires, then 100% duty.

**v8.1 MQTT temperature safety:** Remote `temp/set` and `temp2/set` are **disabled by default**, and are enabled only from the Windows ESP32 → MQTT checkbox (or `MQTT TEMP ON`). Even then they can update a channel only after its USB/local temperature has gone stale (10 s). Fresh USB and DS18B20 readings have priority and preempt MQTT. The setting is persisted separately in ESP NVS and reported as `TEMP_ALLOW` in `MQTT CONFIG?`.

Turning Home Assistant Discovery off now publishes empty retained payloads for all 8 fan, RPM and ARGB entities plus optional PC entities when MQTT remains connected. The pending cleanup is retried on MQTT reconnect; disabling MQTT or Wi-Fi prevents immediate broker cleanup.

**Security:** this is **unencrypted MQTT**. Use only on a trusted local LAN,
with an authenticated broker and ACL restricting device-specific topics. Do
not forward broker port 1883 to the internet. Local serial configuration also
transmits the password in plaintext. No TLS credentials are implemented yet.

## Topics

`MQTT?` returns the actual `<device>` base, such as `esp32fan/1234abcd`.
Each fan channel is 1–8:

| Topic suffix | Direction | Values |
| --- | --- | --- |
| `fan/1/pct` | state (retained) | applied PWM, 0–100 |
| `fan/1/rpm` | state | measured RPM, 0 if unavailable |
| `fan/1/state` | state | `ON`, `OFF` |
| `fan/1/mode` | state | `auto`, `manual` |
| `fan/1/fault` | state | `ON`, `OFF` |
| `fan/1/temp` | state | latest temperature, Celsius |
| `fan/1/set` | command | percentage 0–100 |
| `fan/1/power/set` | command | `ON` (100) or `OFF` (0) |
| `fan/1/mode/set` | command | `auto` |
| `fan/1/temp/set` | command | integer 0–1250, deci-Celsius |
| `fan/1/temp2/set` | command | integer 0–1250, deci-Celsius |
| `light/1/set` | command | `OFF`, `ON`, `RAINBOW` |
| `light/1/rgb/set` | command | `R,G,B` (0–255 each) |
| `availability` | state | `online`, `offline` (Last Will) |

At startup/reconnect ESP automatically publishes **Home Assistant MQTT Discovery**
for eight fans, eight RPM sensors and eight basic RGB light entities. With HA's
MQTT integration enabled, they should appear under one `ESP32-S3 Fan/ARGB`
device. The broker must accept retained discovery messages and the `homeassistant/`
topic prefix. Fan power modes are not forceable through discovery.

**Critical safety:** ALL setpoint and power commands pass through the same
`CoolingController` validation as USB Serial. As shipped with
`FAN_DC_PWM_VALIDATED=0`, any request below 100% is rejected. TACH/RPM for
2-pin fans are unavailable. `temp/set` is intended for a trusted external
sensor publisher; incorrect telemetry can reduce the requested fan speed,
so configure ACLs appropriately. If temperature updates stop for 10 s,
firmware demands 100% power. Software cannot guarantee fail-ON on MCU reset.

## v8.2: transactional provisioning

The Windows app uses serial protocol v7 when available. `MQTT TX START`
copies the live broker, credentials and options to RAM. `MQTT TX BROKER`,
`MQTT TX AUTHHEX` and `MQTT TX FLAGS <enabled> <discovery> <temperature>`
edit only this temporary copy. `MQTT TX COMMIT` validates and writes a
single CRC-protected `config_v2` NVS record; `MQTT TX CANCEL` discards
uncommitted secrets. Staging expires after 30 seconds. Any storage failure
keeps the previous live settings and makes COMMIT retryable.

Example (all values are illustrative and auth is hex, not plaintext):

```text
MQTT TX START
MQTT TX BROKER 192.168.1.30 1883
MQTT TX FLAGS 1 1 0
MQTT TX COMMIT
MQTT CONFIG?
```

Legacy v8 MQTT commands remain supported, but are not cross-field atomic.
An existing v8 NVS configuration is imported without a boot-time flash
write. From the first successful settings change onward, v8.2 uses
`config_v2`, and a corrupt new record disables MQTT instead of silently
reactivating older credentials. Downgrading to old firmware may read its
older, stale NVS settings. `STORAGE_OK=0` in `MQTT CONFIG?` flags a failed
write or corrupted saved record. Neither the USB protocol nor TCP/1883
provides transport encryption.
