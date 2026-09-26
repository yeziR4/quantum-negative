"""Deterministic media synthesis — the classical half of the pipeline.

Everything here is a pure function of its inputs: same notes and seed produce
byte-identical audio. That is deliberate. The submission's claim is that a
quantum process drove the creative choices, so the pipeline around it must not
inject any randomness of its own — otherwise the claim is unverifiable.

Only numpy is required. WAV writing uses the standard library `wave` module so
no audio codec dependency is needed.
"""

from __future__ import annotations

import math
import struct
import wave

import numpy as np

__all__ = [
    "Note",
    "quantise_notes",
    "render_additive",
    "render_fm",
    "apply_decay",
    "convolve_ir",
    "normalise",
    "write_wav",
    "spectral_centroid",
    "rms",
]


class Note:
    """One musical event. `pitch` is a MIDI note number, not a frequency."""

    __slots__ = ("pitch", "start", "duration", "velocity", "pan")

    def __init__(self, pitch: int, start: float, duration: float,
                 velocity: float = 0.8, pan: float = 0.0):
        self.pitch = int(pitch)
        self.start = float(start)
        self.duration = float(duration)
        self.velocity = float(velocity)
        self.pan = float(pan)

    def to_dict(self) -> dict:
        return {"pitch": self.pitch, "start": round(self.start, 6),
                "duration": round(self.duration, 6),
                "velocity": round(self.velocity, 4), "pan": round(self.pan, 4)}

    def __repr__(self) -> str:
        return (f"Note(pitch={self.pitch}, start={self.start:.3f}, "
                f"dur={self.duration:.3f}, vel={self.velocity:.2f}, pan={self.pan:+.2f})")


def midi_to_hz(pitch: float) -> float:
    return 440.0 * (2.0 ** ((pitch - 69.0) / 12.0))


def _as_sequence(value, count: int) -> list:
    """Accept either a scalar (repeated for every note) or a per-note sequence."""
    if value is None:
        return [None] * count
    if isinstance(value, (int, float)):
        return [float(value)] * count
    items = list(value)
    if len(items) < count:
        items = items + [items[-1]] * (count - len(items))
    return items[:count]


def quantise_notes(pitches, start: float = 0.0, spacing: float = 0.25,
                   duration: float = 0.22, velocity=None, pan=None,
                   pan_range: float = 0.6) -> list[Note]:
    """Turn a sequence of pitch values into timed notes.

    `velocity` and `pan` take either a scalar (applied to every note) or a
    per-note sequence. When `pan` is omitted, notes spread across the stereo
    field by their position, so the spatial image comes from the sequence
    itself rather than from noise.
    """
    notes: list[Note] = []
    count = len(pitches)
    vels = _as_sequence(velocity, count)
    pans = _as_sequence(pan, count)
    for i, pitch in enumerate(pitches):
        vel = 0.8 if vels[i] is None else float(vels[i])
        if pans[i] is not None:
            p = float(pans[i])
        elif count == 1:
            p = 0.0
        else:
            p = pan_range * (2.0 * i / (count - 1) - 1.0)
        notes.append(Note(int(round(float(pitch))), start + i * spacing,
                          duration, vel, p))
    return notes


def _envelope(n: int, attack: float, decay: float, sr: int) -> np.ndarray:
    """Percussive AD envelope: short attack, exponential decay."""
    t = np.arange(n) / sr
    a = max(attack, 1e-5)
    env = np.where(t < a, t / a, np.exp(-(t - a) / max(decay, 1e-5)))
    return np.clip(env, 0.0, 1.0)


def render_additive(notes: list[Note], sr: int = 22050, duration: float | None = None,
                    partials: int = 6, attack: float = 0.005,
                    decay: float = 0.35, harmonics: str = "odd") -> np.ndarray:
    """Additive synthesis into a stereo buffer of shape (2, n_samples).

    `harmonics` picks the partial series: "odd" gives a hollow, clarinet-like
    timbre (1,3,5,...), "all" gives a fuller organ-like one, "oct" favours
    octaves — the three characters our quantum operators select between.
    """
    end = max((nt.start + nt.duration for nt in notes), default=0.0)
    total = duration if duration is not None else end + decay + 0.25
    n = int(total * sr)
    buf = np.zeros((2, n), dtype=np.float64)

    for note in notes:
        if harmonics == "odd":
            series = [(2 * k + 1) for k in range(partials)]
        elif harmonics == "oct":
            series = [2 ** k for k in range(partials)]
        else:
            series = list(range(1, partials + 1))
        f0 = midi_to_hz(note.pitch)
        length = int(note.duration * 1.6 * sr) + 1
        env = _envelope(length, attack, decay, sr)
        sig = np.zeros(length)
        for h in series:
            freq = f0 * h
            if freq >= sr / 2:              # respect Nyquist
                break
            sig += (1.0 / h) * np.sin(2 * np.pi * freq * np.arange(length) / sr)
        sig *= env * note.velocity

        start = int(note.start * sr)
        stop = min(start + length, n)
        if start >= n:
            continue
        seg = sig[: stop - start]
        # Constant-power panning keeps perceived loudness steady across the field.
        left = math.sqrt((1.0 - note.pan) / 2.0)
        right = math.sqrt((1.0 + note.pan) / 2.0)
        buf[0, start:stop] += seg * left
        buf[1, start:stop] += seg * right
    return buf


def render_fm(notes: list[Note], sr: int = 22050, duration: float | None = None,
              carrier_ratio: float = 1.0, mod_ratio: float = 2.0,
              index: float = 3.0, attack: float = 0.004,
              decay: float = 0.4) -> np.ndarray:
    """Two-operator FM synthesis — brighter and more metallic than additive."""
    end = max((nt.start + nt.duration for nt in notes), default=0.0)
    total = duration if duration is not None else end + decay + 0.25
    n = int(total * sr)
    buf = np.zeros((2, n), dtype=np.float64)

    for note in notes:
        f0 = midi_to_hz(note.pitch)
        length = int(note.duration * 1.8 * sr) + 1
        t = np.arange(length) / sr
        env = _envelope(length, attack, decay, sr)
        modulator = np.sin(2 * np.pi * f0 * mod_ratio * t)
        carrier = np.sin(2 * np.pi * f0 * carrier_ratio * t + index * modulator)
        sig = carrier * env * note.velocity

        start = int(note.start * sr)
        stop = min(start + length, n)
        if start >= n:
            continue
        seg = sig[: stop - start]
        left = math.sqrt((1.0 - note.pan) / 2.0)
        right = math.sqrt((1.0 + note.pan) / 2.0)
        buf[0, start:stop] += seg * left
        buf[1, start:stop] += seg * right
    return buf


def apply_decay(buf: np.ndarray, tail: float = 0.97) -> np.ndarray:
    """Gentle exponential fade so the piece does not end on a hard edge."""
    n = buf.shape[1]
    if n == 0:
        return buf
    ramp = tail ** (np.arange(n) / max(n - 1, 1))
    return buf * ramp


def convolve_ir(buf: np.ndarray, ir: np.ndarray, wet: float = 0.35) -> np.ndarray:
    """Convolve with an impulse response to place the piece in a space.

    Uses FFT convolution via numpy. The Atlas `retrocausal-echo-v1` engine does
    this on quantum-derived impulse responses; this is the local equivalent so
    the pipeline is complete without the API.
    """
    if ir.ndim == 1:
        ir = np.stack([ir, ir])
    n = buf.shape[1] + ir.shape[1] - 1
    out = np.zeros((2, n))
    for ch in range(2):
        out[ch] = np.fft.irfft(np.fft.rfft(buf[ch], n) * np.fft.rfft(ir[ch], n), n)
    dry = np.pad(buf, ((0, 0), (0, n - buf.shape[1])))
    return (1.0 - wet) * dry + wet * out


def make_ir(seed: int, sr: int = 22050, seconds: float = 1.6,
            decay: float = 0.35) -> np.ndarray:
    """A deterministic synthetic impulse response — a small, dark room."""
    rng = np.random.default_rng(seed)
    n = int(seconds * sr)
    t = np.arange(n) / sr
    env = np.exp(-t / decay)
    noise = rng.standard_normal((2, n)) * env
    # Two early reflections give the space a sense of size.
    for ch in range(2):
        for delay, gain in ((0.013, 0.5), (0.029, 0.3)):
            idx = int(delay * sr * (1 + 0.2 * ch))
            if idx < n:
                noise[ch, idx] += gain
    return noise


def normalise(buf: np.ndarray, peak: float = 0.89) -> np.ndarray:
    """Scale to a target peak. Deterministic and lossless when already quiet."""
    if buf.size == 0:
        return buf
    current = float(np.max(np.abs(buf)))
    if current < 1e-12:
        return buf
    return buf * (peak / current)


def write_wav(path: str, buf: np.ndarray, sr: int = 22050) -> str:
    """Write a stereo 16-bit PCM WAV. Returns the path."""
    if buf.ndim == 1:
        buf = np.stack([buf, buf])
    clipped = np.clip(buf, -1.0, 1.0)
    pcm = (clipped * 32767.0).astype("<i2")
    # Interleave channels: L0 R0 L1 R1 ...
    interleaved = pcm.T.reshape(-1)
    with wave.open(path, "wb") as fh:
        fh.setnchannels(2)
        fh.setsampwidth(2)
        fh.setframerate(sr)
        fh.writeframes(interleaved.tobytes())
    return path


def rms(buf: np.ndarray) -> float:
    if buf.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(buf ** 2)))


def spectral_centroid(buf: np.ndarray, sr: int = 22050) -> float:
    """Brightness in Hz: the magnitude-weighted mean frequency.

    A single number that summarises timbre, and the sanity check that a
    timbre-selecting quantum parameter actually changed the sound.
    """
    if buf.size == 0:
        return 0.0
    mono = buf.mean(axis=0) if buf.ndim == 2 else buf
    spectrum = np.abs(np.fft.rfft(mono))
    freqs = np.fft.rfftfreq(len(mono), 1.0 / sr)
    denom = float(spectrum.sum())
    if denom < 1e-12:
        return 0.0
    return float((freqs * spectrum).sum() / denom)
