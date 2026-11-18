"""Opt-in, privacy-preserving system-audio loopback to ESP32 numeric bands.

Runs in a dedicated worker, never records or retains raw PCM, and only
offers the four latest 0..255-band envelopes to the serial owner. Missing
soundcard/driver/device leaves LEDs silent while cooling stays untouched.
"""
from __future__ import annotations

from threading import Event, Lock, Thread
import time


def audio_command(levels: tuple[int, int, int, int]) -> str:
    if (not isinstance(levels, tuple) or len(levels) != 4 or
            any(type(v) is not int or not 0 <= v <= 255 for v in levels)):
        raise ValueError("Four numeric audio bands (0..255) required")
    return "AUDIO " + " ".join(map(str, levels))


def analyze_pcm(samples, sample_rate: int, np) -> tuple[int, int, int, int]:
    """Four broad, approximate FFT energy bands; accepts float PCM frames.

    Intentionally does not store audio samples or transmit PCM. Scaling is
    conservative; the ESP applies per-zone gain and global LED current limits.
    """
    if sample_rate < 8000:
        raise ValueError("Invalid audio sample rate")
    data = np.asarray(samples, dtype=np.float32)
    if data.ndim == 2:
        data = data.mean(axis=1)
    if data.ndim != 1 or len(data) < 128:
        return (0, 0, 0, 0)
    data = np.nan_to_num(data, nan=0.0, posinf=0.0, neginf=0.0)
    data = np.clip(data, -1.0, 1.0)
    peak = min(255, int(round(float(np.max(np.abs(data))) * 255)))
    window = np.hanning(len(data))
    fft = np.abs(np.fft.rfft(data * window)) / max(1, len(data))
    bins = np.fft.rfftfreq(len(data), 1.0 / sample_rate)
    bands = []
    for low, high in ((40, 220), (220, 2400), (2400, 8500)):
        selected = fft[(bins >= low) & (bins < high)]
        rms = float(np.sqrt(np.mean(selected ** 2))) if selected.size else 0.0
        bands.append(min(255, max(0, int(round(rms * 1400)))))
    return (*bands, peak)


class LoopbackAudioCapture:
    def __init__(self) -> None:
        self._lock = Lock()
        self._stop = Event()
        self._thread: Thread | None = None
        self._bands: tuple[int, int, int, int] | None = None
        self._sample_time = 0.0
        self._serial = 0
        self._delivered = 0
        self._error = ""
        self._active = False

    @property
    def error(self) -> str:
        with self._lock:
            return self._error

    @property
    def running(self) -> bool:
        with self._lock:
            return self._active

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        with self._lock:
            self._error = ""
        self._thread = Thread(target=self._capture, name="AudioLoopback", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=0.2)
        with self._lock:
            self._active = False
            self._bands = None

    def read_latest(self, now: float | None = None) -> tuple[int,int,int,int] | None:
        now = time.monotonic() if now is None else now
        with self._lock:
            if (self._bands is None or self._serial == self._delivered or
                    now - self._sample_time > 0.8):
                return None
            self._delivered = self._serial
            return self._bands

    def _capture(self) -> None:
        try:
            import numpy as np
            import soundcard as sc
            speaker = sc.default_speaker()
            if speaker is None:
                raise RuntimeError("No default system playback device")
            microphone = sc.get_microphone(id=str(speaker.id), include_loopback=True)
            if microphone is None or not microphone.isloopback:
                raise RuntimeError("No loopback capture for the selected playback device")
            with microphone.recorder(samplerate=24000, blocksize=1024) as recorder:
                with self._lock:
                    self._active = True
                while not self._stop.is_set():
                    samples = recorder.record(numframes=1024)
                    bands = analyze_pcm(samples, 24000, np)
                    with self._lock:
                        self._bands = bands
                        self._sample_time = time.monotonic()
                        self._serial += 1
        except Exception as exc:
            with self._lock:
                self._error = str(exc)[:240]
        finally:
            with self._lock:
                self._active = False
                self._bands = None
