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
