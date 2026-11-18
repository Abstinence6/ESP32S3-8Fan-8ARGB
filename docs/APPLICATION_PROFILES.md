# Temporary cooling profiles by running Windows applications

The Windows GUI and headless user-session agent share
`pc_app/application_profiles.py` to map active process names to
`Silent`, `Balanced`, or `Performance` curves. This is strictly opt-in.

Rules are local Windows `QSettings` entries:
`appProfileRulesV1` (JSON version 1) and `appProfilesEnabled` (boolean).
Only process executable names are inspected; never command lines, arguments
or network data. Highest priority wins, then lexicographical filename.
A four-second debounce avoids changes on transient processes.

**No automatic NVS writes.** The ESP accepts `RTCURVE BEGIN`, eight
`RTCURVE SET` commands, and `RTCURVE COMMIT`. The transaction applies
only in RAM, is required to include all eight channels, and expires after
20 seconds unless refreshed with `RTCURVE KEEPALIVE`. `RTCURVE CLEAR`
reverts to the separately saved curves; reboot also clears this state.

All physical fan power and sensor safety guards still apply. Existing
manual/fixed-RPM modes are not forcibly changed by runtime profiles.
The profile never unlocks `FAN_DC_PWM_VALIDATED=0`, so unqualified
hardware remains at demanded 100% supply PWM. A missing temperature
still causes 100% in every mode after 10 seconds.

An old GUI can ignore these commands; a new GUI checks the firmware
`VERSION?` capability `RTCURVE=1` before attempting any runtime profile.

If process enumeration fails (including insufficient permissions) the companion
abandons the previous application decision and asks ESP32 to clear its temporary
curve. If USB is unavailable, the lease still expires in 20 seconds.
The existing GPU-load profile automation is suspended while a process profile
is selected, preventing competing persistent NVS changes. A manual curve edit
remains higher priority and disables process rules.
