# Validation plan for consolidated main

The source tree in `main` is the active firmware and Windows companion.
Older branch implementations remain accessible through Git history, but are
**not automatically enabled by ancestry merging**. This is a reference
project: no hardware qualification is implied by a successful CI run.

## Automated validation

1. `sh test/native/run.sh` — native C++ unit/safety smoke tests.
2. `python -m unittest discover -s pc_app/tests -v` — Windows companion
   helpers, profile validation, sACN parsing and serial protocol.
3. `python -m compileall -q pc_app` — Python syntax validation.
4. `pio run -e esp32s3` — ESP32-S3 PlatformIO build.
5. Confirm GitHub Actions passes at the **consolidated main commit**, not
   only at a previous version or an unrelated feature branch.

## Hardware-only validation — not yet performed

1. Verify GPIO mapping against the actual ESP32-S3 module and PCB; do
   not assume reference pins are safe on a different module.
2. With an oscilloscope verify the real 12 V high-side output and driver
   polarity (`board::kPwmDriverInverts`), including reset, ESP unpowered,
   brownout, cold boot and COM reconnect. A safe PC cooling deployment
   needs **fan power on** on MCU failure, guaranteed by hardware.
3. Keep `FAN_DC_PWM_VALIDATED=0` until the specific 2/3-pin motor and
   DC power switch have passed 250 Hz switching, startup/inrush,
   thermal stress, transient and fault testing. Software 100% commands
   alone cannot make a power stage fail-safe.
4. Measure the 3-pin TACH signal when fan supply is PWM-chopped.
   Validate pulse integrity, spurious edges, disconnected motor,
   stale-window handling and RPM plausibility. Two-pin fans have no TACH.
5. Verify every fan channel behaves safely if PC temperature telemetry
   stops, LHM crashes, Wi-Fi disconnects, or MQTT commands arrive
   while DC power PWM remains unvalidated.
6. Verify all eight LED outputs at the actual strip lengths, including
   5 V power injection, level shifters, current consumption and total
   ARGB current budget, then stress OpenRGB E1.31 traffic.
7. Test local E1.31 over the companion bridge and direct Wi-Fi
   separately. Confirm UDP cannot modify fan-control safety guards.
8. Test MQTT/Home Assistant discovery, eight fan controls and sensor
   reporting with a real broker, including loss/recovery and invalid
   commands. Keep the broker on a trusted network.
9. Test Windows GUI + background agent together. Exactly one process
   must own the USB port, while fan sensor updates continue.

## v8.2 software reliability checks

- [x] Host tests verify that USB and DS18B20 temperatures preempt MQTT and that
  telemetry reports SOURCE, AGE_MS and FAILSAFE without changing fan output.
- [x] MQTT staging tests cover no NVS writes before COMMIT, exactly one write,
  simulated write failure, retry, reboot persistence, cancel and no-op updates.
- [x] Python diagnostics parser tests cover source attribution, age and malformed
  input, retaining compatibility with older HEALTH responses.
- [ ] On real hardware, confirm WDT reset after a deliberately stalled loop,
  log reboot reason, verify fan power is full speed **during** reset,
  and validate boot GPIO/12 V gate behavior under brownout.
- [ ] Qualify MOSFET driver TACH and all eight 12 V channels on the intended PCB.

## Controller reliability regression checks

- A saved GPIO mapping with corrupt CRC/length must stop startup before any
  PWM/TACH/ARGB output is initialized; fresh NVS without `pins` uses the
  factory map. Restore NVS only while the cooled PC is safely off.
- GUI and headless agent must send the same valid CPU/GPU `PWRDATA` values;
  missing metrics use the `65535` sentinel.
- Eight ARGB zones are coalesced and sent with a bounded 60 kB/s RGB rate,
  leaving serial bandwidth and write priority for control commands.
- Reject ARGB budgets below the estimated total idle LED current; verify the
  actual physical current separately (software limits do not replace fuses).
- Stale temperatures must publish `unknown` to the retained MQTT topic.


## Shared PC sensor and adaptive RGB regression checks

- Foreground GUI and headless agent use the same eight-route sensor planner:
  missing/invalid primary or secondary sensors never fabricate temperatures.
- Both modes share validated CPU/GPU watt forwarding and GPU-load profile
  selection; NVS curve writes still depend on firmware acknowledgement.
- E1.31 and native OpenRGB share an adaptive scene budget (at most 25 FPS per
  changing zone, reducing the cap for eight 170-pixel strips at 60 kB/s).
- Identical frames are coalesced/suppressed, with an under-3-second keepalive
  while the source remains active. Disconnect/owner handoff drops old frames.
- RGB byte-rate limiting is still enforced in SerialTransmitter; control
  commands always have priority. Real USB and ESP rendering FPS require
  oscilloscope/bench measurement.

## New features regression checklist

- Named fan-group mask command is rejected without a qualified high-side
  driver; preflight is all-or-nothing and excludes nonmember channels.
- Background and foreground process policy chooses the same prioritized
  application, debounces changes and never logs command-line arguments.
- `RTCURVE` requires all eight valid curves before COMMIT, never writes NVS,
  expires after 20s without KEEPALIVE, and respects the existing 10s sensor
  timeout, calibration guard, TACH and thermal failsafe.
- Fan Health only flags verified 3-pin RPM trends with an explicit stable
  reference and never claims two-pin operation without a TACH sensor.
- Native effects run without Windows and use one existing RGB24 buffer per
  channel. Boot is OFF unless explicitly saved as opted in; malformed scene
  CRC restores safe defaults. Global current cap and safety overlay apply.
- Windows settings backup validates new group/application/Fan Health data and
  never imports arbitrary executable paths or authentication credentials.
