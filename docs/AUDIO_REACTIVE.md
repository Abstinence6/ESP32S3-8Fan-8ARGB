# Audio Reactive ARGB (firmware v13)

ESP32 directly renders four modes per independent ARGB strip:

1. VU bar using the current peak/bass.
2. Four-band horizontal spectrum.
3. Bass pulse using a local nonblocking timebase.
4. Audio-reactive travelling wave.

The device receives four bounded integers, **not a PCM audio stream**:

```text
AUDIO 90 50 15 100
AUDIOCFG SET 2 2 100 64 0 150 255 255 40 100
AUDIOCFG? 2
AUDIOCFG BOOT 2 0
AUDIOCFG SAVE
```

The AUDIO command is bass/mid/treble/peak, each 0..255. The last input
expires in **1.2 seconds**, producing black RGB scene data until the next
sample. System safety warning pixels remain visible and global power
estimation applies. Settings persist in CRC-checked
`argb-v4/audio` NVS only after explicit SAVE; boot defaults to OFF.

Alternatively publish `90,50,15,100` (no retained flag) to
`<base>/audio/set` over trusted local MQTT. ESP handles animation even
when the audio source is external, never requiring full-frame RGB over
USB. To run independently from Windows without a remote publisher, a
new separate I²S microphone, digital audio decoder, or Ethernet/MQTT
audio envelope source must be physically integrated. No spare GPIO
assignment for I²S is defined in this firmware.

## Windows WASAPI loopback (explicit opt-in)

Open **ARGB → Звукова підсвітка**, select a scene and enable
`Зчитувати системний звук Windows`. The sampler captures only local
system playback, calculates approximate FFT band energy and publishes
four numeric values. It does **not** persist raw sound, transmit PCM,
or open a network audio endpoint. The capture checkbox is off by default;
the user's explicit preference persists and can be resumed by their
headless user-session agent. When GUI owns the serial proxy, agent capture
is stopped so two samplers cannot compete. Capturing may require working
WASAPI drivers and system loopback permissions.

CPU fan PWM, thermal watchdog, TACH/PID and hardware interlock are
untouched. All RGB sample handling is passive and time-bounded.
