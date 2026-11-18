# Airflow Assistant: estimated balance, not case pressure

This **passive** ESP32 component computes an estimate of intake and exhaust
air volume rates based on user-supplied rated fan RPM, rated free-air CFM and
an approximate 1–100% installation restriction coefficient. It uses only
reliable measured TACH RPM, not commanded PWM.

For a channel, configure:
- Direction 0 = unspecified (exclude), 1 = intake, 2 = exhaust
- Rated maximum RPM = 300..25000
- Rated free-air throughput in **0.1 CFM** = 1..3000
- Restriction 1..100% = estimated fraction of free-air flow in this case

```text
AIRCFG 1 1 2000 900 80
AIRCFG 2 2 2000 700 80
AIRCFG? 1
AIRFLOW?
```

For a 2000-RPM, 90-CFM rated fan at 1500 RPM with 80% estimated
restriction the simple model predicts about 54 CFM. It is a coarse
assumption and not a measured performance curve. A zero/invalid/unseen
TACH, missing intake/exhaust group or unconfigured profile produces
`VALID=0 TREND=unavailable`. No claim of actual positive/negative
static pressure in Pa is made without a pressure sensor, and the sign of
the approximate CFM balance is **not** a pressure measurement.

The v13 firmware stores settings in `airflow-v1/channels` with a CRC
and writes only after an explicit user configuration change. It has
no API that changes fan PWM, modes or temperature settings.

Windows GUI: **Fans → Airflow Assistant…**. MQTT publishes
`<base>/airflow/intake`, `exhaust`, `balance` and `trend` for HA
read-only display. Real flow measurements require calibrated flow
sensors and duct/case geometry; pressure requires a differential
pressure sensor and an appropriate measurement setup.
