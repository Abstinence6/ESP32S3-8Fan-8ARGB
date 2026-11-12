# Branch consolidation (2026-11-12)

The default branch is `main`. Historical branches were consolidated
using a **main-preferred multi-parent merge**: the original commit
histories are preserved as merge parents while the **active code** stays
on the most recent `main` implementation.

## Why a main-preferred resolution?

Older branches contain superseded implementations of 4-pin and 2/3-pin
fan modes, E1.31, Windows control, calibration and MQTT. Replacing the
current source files with their older versions could silently regress
the DC power safety interlock, the revised 2/3-pin-only control scheme,
MQTT/Home Assistant, the Windows serial proxy or OpenRGB configuration
presets. The consolidated commit therefore does **not** claim all
branch-only implementation variants are simultaneously active.

In particular, `feat/v5-mqtt-23pin-safety` provides an alternative
FreeRTOS-queued MQTT design, a different TACH edge filter and an
alternative `pc_app/ipc.py` transport. Those implementations conflict
with the current `MqttBridge`, `FanController` and
`pc_app/serial_owner.py` APIs. They are preserved in their historical
commit but intentionally **not substituted** into the active tree.
The hardware/bench validation plan from that branch is brought forward
as [TEST_PLAN.md](TEST_PLAN.md), updated for the current code.

`chatgpt/openrgb-config-presets` was previously squash-merged into
`main`; its file tree already matches the default branch. Other older
branches were also superseded by newer code. Do not infer that a
multi-parent merge alone validates hardware or imports every
alternative implementation.

All original branch commit IDs remain reachable via the multi-parent
merge even if their refs are later pruned. Verify CI on the final
consolidated commit before deploying firmware.
