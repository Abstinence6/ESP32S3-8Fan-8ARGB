# Fan groups (Windows user configuration)

The Windows GUI **Fans -> Fan groups** stores versioned named groups in the
user's QSettings `fanGroupsV1`. A physical fan 1..8 may belong to at most
one group. Group metadata is local and does not change ESP NVS or wiring.

The firmware accepts `FANMASK MANUAL <mask> <percent>` and
`FANMASK AUTO <mask>`, where mask is 1..255 (bit 0 = fan 1).
All selected channels are validated before any changes. Existing per-fan
temperature freshness, stall, overheat, startup, hardware PWM interlock and
calibration safety are unchanged. Without a qualified high-side 12 V
driver, the firmware rejects any request below 100% as usual.

A successful Serial write means the bytes were queued, not that the ESP
confirmed a transition; inspect the returned `OK FANMASK` and `STATUS`
to verify hardware state. This feature cannot make the power stage fail-ON.
