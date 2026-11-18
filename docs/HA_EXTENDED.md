# Extended Home Assistant integration (firmware v13)

ESP32 remains the sole cooling safety arbiter. With a trusted local MQTT
broker configured and MQTT Discovery enabled, the new HA entities are:

- `Offline cooling/ARGB profile` select: Base, Profile 1, Profile 2,
  Profile 3. Profiles need explicit USB capture before being selected.
- Fan N Temperature sensor (°C). For aged/missing sources it reports
  `unknown`, never a fabricated fresh reading.
- Fan N Fault problem binary sensor.
- Estimated Intake Airflow, Estimated Exhaust Airflow, Estimated Airflow
  Balance and Estimated Airflow Tendency. Without reliable tachometer
  data for every configured fan, these report unavailable/unknown.

Direct MQTT commands:

| Topic relative to `<base>` | Payload | Meaning |
| --- | --- | --- |
| `profile/set` | `Base` or `Profile 1..3` | Select saved offline cooling/RGB profile |
| `light/N/effect/set` | `OFF/RAINBOW/EFFECT/REACTIVE/AUDIO` | Change on-device RGB mode |
| `audio/set` | `bass,mid,treble,peak` (0..255 each) | Supply numeric audio bands, fresh for 1.2s |
| `reactive/N/set` | bounded nonnegative integer, tenths | Update an existing reactive slot |
| `fan/N/temp/set` | temperature in 0.1 °C | Only if external temp explicitly allowed |

The base topic is discovered through `MQTT?` (not necessarily
`esp32fan/esp32s3`). To publish audio without the Windows app,
send unretained updates more often than every 1.2 seconds. Publishing
misleading temperature telemetry is dangerous: isolate MQTT on a trusted
LAN with explicit account/topic ACLs. ESP still treats missing temperature
after 10 seconds as full-power cooling, and never bypasses hardware PWM
validation.
