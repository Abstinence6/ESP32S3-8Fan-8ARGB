# Sensor-reactive, autonomous ESP32-S3 ARGB

Firmware v12 adds **per-zone, device-rendered reactive effects**. CPU/GPU
load and hardware performance metrics are not accessible to a bare ESP32:
Windows NWinfo or Home Assistant/MQTT must supply these values. After the
value arrives, the **ESP32 alone generates every animation frame**, with
no PC-side RGB streaming or animation timers. Fan temperature and RPM
safety logic is not modified by this feature.

## Built-in numeric input IDs

All numeric data and limits are transmitted/stored in **tenths of the
physical unit**. For example, 73.5% = 735, 245.6 W = 2456, 1200 RPM =
12000, 62.3 °C = 623.

| IDs | Physical sources | Windows-independent? |
| --- | --- | --- |
| 1..8 | TACH RPM FAN1..FAN8 | Yes, when TACH is reliable |
| 9..16 | Effective fresh cooling temperature of FAN1..FAN8 | Yes if its selected source is local; USB/MQTT temperature still needs a sender |
| 17..24 | Direct DS18B20 probes #1..#8 | Yes, if DS18B20 support, GPIO and probes are configured |
| 25..32 | 8 generic numeric USB or MQTT slots | Only with a live Windows agent or MQTT publisher |
| 33..40 | Applied fan PWM FAN1..FAN8 | Yes |

The primary source must be 1..40. The optional fallback can be **0**
(disabled) or any local source from 1..24 or 33..40. A disconnected or
stale host source changes to the local fallback if fresh; otherwise the
zone displays amber warning pulses, not a misleading low/healthy value.

**DS18B20 caution:** numbered probe discovery indices may change if
devices are reconnected. For durable ROM-specific temperature selection,
use the existing `HTMAP` and `HTMODE LOCAL/BACKUP` fan configuration
and refer to its stable cooling-temperature source 9..16.

## Four mappings

1. **Color** — the whole zone blends between two RGB colors as value rises.
2. **Bar** — the number of lit LEDs represents the value; each illuminated
   segment may have a gradient across its physical position.
3. **Brightness** — the selected native effect gets brighter as the value
   increases.
4. **Speed** — the selected native effect speeds up as the value rises
   (choose Wave, Breathe or Chase for visibly animated patterns).

Existing native patterns Gradient, Wave, Breathe and Chase are reused.
Per-zone brightness and the global ARGB power estimate remain in force.
The hardware warning overlay still takes precedence over every scene.

## Native ASCII protocol

```text
RFX? 1
RFX SET 1 25 9 2 0 1000 2 0 100 255 255 0 0 3 64 0
RFX BOOT 1 0
RFX SAVE
RFX START 1
RFX STOP 1
RVAL 1 735
```

`RFX SET <zone> <source> <fallback> <style> <low*10> <high*10>
<pattern:1..4> <r1> <g1> <b1> <r2> <g2> <b2> <speed:1..10>
<brightness:0..255> <reverse:0|1>`

- `RFX SET` starts the scene immediately in RAM; **no flash writes**.
- `RFX SAVE` saves the eight scenes and boot preferences in a new
  CRC-checked `argb-v4/reactive` record. Old `argb-v4/config` and
  `effects` records remain untouched.
- `RFX BOOT <zone> 1` plus SAVE enables autonomous playback on reset.
  By default every zone stays OFF; if both FX and RFX boot flags are set
  for the same zone, RFX takes priority.
- `RVAL <slot> <value*10>` supplies **one positive bounded numeric input**
  into slot 1..8 (input source 25..32), with a seven-second freshness TTL.
- `RFX?` reports live source, mapping, limits, colors, boot and current
  freshness/value. `VERSION?` advertises `RFX=1`.

## Windows NWinfo: CPU/GPU, load, power, RAM and more

Open **Підсвітка → Реактивні датчики** in FanARGBControl.
Choose **ПК або MQTT: слот N** as the source, select a real NWinfo
metric or temperature (or MQTT-only), choose effect parameters and use
**Перегляд** then **Зберегти в ESP32**. Exact stable sensor IDs live in
Windows user settings `reactiveHostSourcesV1` and can be backed up.

The GUI and headless agent send at most eight `RVAL` values per normal
NWinfo poll, no RGB frames, and stop sending values for unavailable
sensors; their existing freshness/timeout safety features remain intact.
Native local sources and previously saved scenes keep running with the
GUI completely shut down. An unconnected PC cannot provide its CPU/GPU
load: select a local fallback or send the metric via MQTT instead.

## MQTT/Home Assistant: no Windows required

For a configured MQTT broker, ESP subscribes to:

```text
esp32fan/esp32s3/reactive/1/set
...
esp32fan/esp32s3/reactive/8/set
```

Example: publish `825` to slot 1 for 82.5%. In Home Assistant use a
template automation publishing
`{{ ((states('sensor.gpu_load') | float(0)) * 10) | round(0) | int }}`
to the topic (adapt to the real sensor entity); do not publish
retained old state on start. MQTT broker authentication and topic ACLs
should restrict publishers. Source 25..32 receives the same value
whether updated by USB or MQTT, with **last-arrival-wins** semantics.
The seven-second TTL also applies to MQTT outages.

The numerical ceiling is 10,000,000 tenths (1,000,000 physical units).
Very large IOPS counters outside this range are not representable.

## Safety and autonomy limits

No RFX/RVAL/MQTT reactive command changes fan mode, PWM, temperature
data, thermal watchdog, stall recovery, PID or 12V driver validation.
Software current calculation is still an **estimate**, not a fuse or
short-circuit protection. Live CPU/GPU information requires a running
Windows source or another external publisher; device-local RPM/PWM and
a qualified wired DS18B20 operate independently from both.
