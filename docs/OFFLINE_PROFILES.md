# ESP32 autonomous cooling and RGB profiles (firmware v13)

Up to **three user-defined slots** live entirely on the ESP32's NVS.
A slot captures each of eight previously **persisted** five-point cooling
curves, current ARGB mode and static color, and device effect/reactive
configuration. No PC, broker or cloud is required to select an existing
profile or keep it running. This does not replace a trustworthy source
of CPU/GPU temperature: if missing, fan control demands 100% after 10 s.

Commands:

```text
PROFILE?
PROFILE SAVE 1
PROFILE SELECT 1
PROFILE BOOT 1
PROFILE CLEAR
PROFILE BOOT 0
```

SAVE copies the current configuration to the requested slot and explicitly
writes one CRC-checked `offline-v1/bank` NVS record. It does NOT capture
temporary Windows runtime `RTCURVE` values; use `CURVE` to save them first
if needed. External per-pixel stream mode is captured as OFF (there is no
stream to replay without a PC). Audio scene uses its independently saved
`argb-v4/audio` configuration when selected; use `AUDIOCFG SAVE` for that.

SELECT applies the captured curves as an in-memory override and changes
the eight ARGB modes. No flash is written during profile switches. The
existing 20-second leased host `RTCURVE` overrides offline curves only
while fresh; on expiration the offline curve takes over. Individual manual,
fixed-RPM, overheat, lost-temperature, stall, calibration and DC driver
interlocks retain their existing priority. No function modifies hardware
PWM safety requirements.

BOOT 1..3 opts into replaying a saved slot after reset; BOOT 0 disables
this. On fresh, truncated or CRC-invalid NVS, zero slots are active, and
the existing default fan and ARGB boot policy is unchanged. The whole
record is verified before being accepted; failed writes leave live
configuration unchanged.

Windows GUI: **Fans → Автономні профілі ESP32…**.
MQTT/Home Assistant: `<base>/profile/set` accepts `Base` or `Profile N`
and reports `<base>/profile/state` once every 2 seconds.
