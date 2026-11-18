# Native ESP32 ARGB effects

Firmware runs heap-free RGB24 patterns directly on ESP32-S3:
1=Gradient, 2=Wave, 3=Breathe, 4=Chase.
Every zone has two RGB colors, speed 1..10, brightness 0..255 and
direction 0/1. Render jobs stay bounded, using the existing per-channel
pixel buffers, one-strip-per-visit scheduler and global current estimator.
The safety warning overlay takes precedence, including over OFF mode.

`FX? <channel>` reports scene state.
`FX SET <ch> <pattern> <r1 g1 b1> <r2 g2 b2> <speed> <brightness> <direction>`
previews a native scene without writing flash.
`FX START <ch>` resumes it; `FX STOP <ch>` sets LED output off.
`FX BOOT <ch> 0|1` sets the staged boot preference.
`FX SAVE` persists all eight scenes in a versioned CRC-checked record
under the existing `argb-v4` namespace without touching legacy config.

New and corrupted effect settings default to boot OFF; enabling a saved
scene at startup requires an explicit `FX BOOT ... 1` and `FX SAVE`.
OpenRGB USB or Wi-Fi streaming still overrides the scene temporarily,
and after 3s frame timeout output returns to OFF rather than resuming
unrequested effects.

No effect bypasses existing brightness/current estimation, thermal
warning overlay or control-loop priority. Hardware fuses are still required.
