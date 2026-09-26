"""Deterministic image and film synthesis.

The local counterpart to Atlas' image and shader engines (`tessa-image-v1`,
`blur-v1`, `entanglement-shader-v1`). Frames are built with numpy and encoded to
H.264 with ffmpeg, which is present on this machine.

Everything is a pure function of its inputs, so the film is byte-reproducible —
which is what makes the quantum provenance checkable after the fact.
"""

from __future__ import annotations

import os
import shutil
import subprocess

import numpy as np
from PIL import Image, ImageFilter

__all__ = [
    "quantum_field",
    "readout_texture",
    "correlation_field",
    "palette_from_angles",
    "tint",
    "smooth",
    "vignette",
    "entangle_frames",
    "ffmpeg_available",
    "write_mp4",
    "write_png",
]


def smooth(field: np.ndarray, radius: float = 9.0) -> np.ndarray:
    """Gaussian-smooth a float field in [0, 1].

    Used on the outcome-probability map: at 8 qubits that map is only 16x16, so
    upscaling it to the canvas otherwise reads as a tiled mosaic. Smoothing
    keeps it as a low-frequency body while the correlation layer supplies the
    fine detail.
    """
    data = (np.clip(field, 0.0, 1.0) * 255.0).astype(np.uint8)
    img = Image.fromarray(data, mode="L").filter(ImageFilter.GaussianBlur(radius))
    return np.asarray(img, dtype=np.float64) / 255.0


def vignette(frame: np.ndarray, strength: float = 0.45,
             power: float = 2.2) -> np.ndarray:
    """Darken toward the corners. Accepts grayscale or RGB float frames."""
    h, w = frame.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
    xx = xx / max(w - 1, 1)
    yy = yy / max(h - 1, 1)
    r = np.sqrt((xx - 0.5) ** 2 + (yy - 0.5) ** 2) / 0.7071
    mask = 1.0 - strength * np.clip(r, 0.0, 1.0) ** power
    if frame.ndim == 3:
        mask = mask[..., None]
    return np.clip(frame * mask, 0.0, 1.0)


def correlation_field(pair_information, qubit_marginals, size: int = 512,
                      harmonics: int = 7, seed: int = 0,
                      probability_map: np.ndarray | None = None) -> np.ndarray:
    """Build an interference image from the circuit's correlation structure.

    Input is the matrix of pairwise mutual information between qubits. Each pair
    contributes a wave whose spatial frequency comes from how strongly those two
    qubits are entangled.

    Orientation is the interesting part. Driving it from the pair index alone
    yields near-parallel lines, because real pair-information spectra are
    bimodal — a few strongly entangled pairs and the rest ~zero — so almost
    every wave ends up at a similar frequency. When a `probability_map` is
    given, its gradient is used as a direction field instead: waves run *along*
    the contours of the measurement distribution. That is both far richer and a
    more faithful picture of the state.

    This replaced a version that stretched the handful of qubit marginals into
    wide bands, which produced a coarse barcode-like image with obvious
    repetition.
    """
    info = np.asarray(pair_information, dtype=np.float64).ravel()
    marg = np.asarray(qubit_marginals, dtype=np.float64).ravel()
    if info.size == 0:
        info = np.array([0.0])
    if marg.size == 0:
        marg = np.array([0.5])

    peak = float(info.max())
    strength = info / peak if peak > 0 else np.zeros_like(info)

    yy, xx = np.mgrid[0:size, 0:size].astype(np.float64)
    xx /= size
    yy /= size
    field = np.zeros((size, size))

    used = strength[:harmonics]
    contours = None
    if probability_map is not None and getattr(probability_map, "shape", None) == (size, size):
        gy, gx = np.gradient(probability_map)
        norm = np.sqrt(gx * gx + gy * gy) + 1e-9
        # Perpendicular to the gradient == along the contours.
        contours = 2 * np.pi * (xx * (-gy / norm) + yy * (gx / norm))

    for index, s in enumerate(used):
        if s <= 1e-6:
            continue
        freq = 3.0 + 22.0 * s
        if contours is None:
            angle = np.pi * index / max(len(used), 1)
            phase = 2 * np.pi * (np.cos(angle) * xx + np.sin(angle) * yy) * freq
        else:
            phase = contours * freq
        field += s * np.sin(phase + index)

    # A radial term keeps the frame from reading as pure parallel lines.
    radius = np.sqrt((xx - 0.5) ** 2 + (yy - 0.5) ** 2)
    field += 0.9 * np.sin(2 * np.pi * radius * (2.5 + 11.0 * float(marg.mean())))

    lo, hi = float(field.min()), float(field.max())
    field = (field - lo) / (hi - lo or 1.0)

    # Per-qubit grain adds fine texture with no randomness.
    grain = np.zeros((size, size))
    for q, m in enumerate(marg):
        freq = 24.0 + 70.0 * float(m)
        angle = np.pi * q / max(len(marg), 1)
        phase = 2 * np.pi * freq * (xx * np.cos(angle) + yy * np.sin(angle))
        grain += (float(m) - 0.5) * np.sin(phase)
    grain /= max(len(marg), 1)
    span = float(np.ptp(grain)) or 1.0
    combined = 0.82 * field + 0.18 * (grain - grain.min()) / span
    return np.clip(combined, 0.0, 1.0)


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def quantum_field(probabilities, size: int = 512, blur: float = 0.0) -> np.ndarray:
    """Turn a probability distribution into a grayscale interference image.

    The distribution is reshaped onto a square grid and scaled up — this is the
    visual analogue of the amplitude encoding the blur engines perform, and it
    means the image literally is the measurement statistics of a circuit.
    """
    probs = np.asarray(list(probabilities), dtype=np.float64)
    if probs.size == 0:
        raise ValueError("probabilities must be non-empty")
    side = int(round(math_sqrt(probs.size)))
    if side * side != probs.size:
        # Pad up to the next perfect square so the grid is well defined.
        side = int(math_sqrt(probs.size)) + 1
        padded = np.zeros(side * side)
        padded[: probs.size] = probs
        probs = padded
    grid = probs.reshape(side, side)
    peak = float(grid.max())
    if peak > 0:
        grid = grid / peak

    img = Image.fromarray((grid * 255.0).astype(np.uint8), mode="L")
    img = img.resize((size, size), Image.BICUBIC)
    if blur > 0:
        img = img.filter(ImageFilter.GaussianBlur(blur))
    return np.asarray(img, dtype=np.float64) / 255.0


def math_sqrt(n: int) -> float:
    return float(np.sqrt(n))


def readout_texture(qubit_marginals, size: int = 512) -> np.ndarray:
    """A striped texture from per-qubit marginals — a direct circuit readout.

    Each marginal stretches a band of the image, so a change in the circuit
    produces a visible change in the frame rather than an opaque one.
    """
    m = np.asarray(list(qubit_marginals), dtype=np.float64)
    if m.size == 0:
        raise ValueError("qubit_marginals must be non-empty")
    bands = np.repeat(m, max(1, size // m.size))
    if bands.size < size:
        bands = np.concatenate([bands, np.full(size - bands.size, bands[-1])])
    bands = bands[:size]
    # Modulate along the other axis by a slow wave so bands read as volume.
    wave = 0.5 + 0.5 * np.sin(np.linspace(0, np.pi * 2 * max(m.size, 2), size))
    return np.outer(bands, wave)


def palette_from_angles(angles, size: int | None = None) -> np.ndarray:
    """Map three rotation angles onto an RGB palette and a gradient image.

    Angles are in radians. Returns a (size, size, 3) float array in [0, 1].
    """
    arr = np.asarray(list(angles), dtype=np.float64).ravel()
    if arr.size < 3:
        arr = np.concatenate([arr, np.zeros(3 - arr.size)])
    rgb = np.clip((np.sin(arr[:3]) + 1.0) / 2.0, 0.0, 1.0)
    if size is None:
        return rgb
    # Interpolate the three anchors across the image beside their complement.
    anchors = np.stack([rgb, 1.0 - rgb, rgb * 0.5 + 0.25])
    ramp = np.linspace(0.0, 1.0, size)
    blend = np.zeros((size, size, 3))
    for ch in range(3):
        blend[:, :, ch] = np.outer(
            np.interp(ramp, [0.0, 0.5, 1.0], anchors[:, ch]),
            np.interp(ramp, [0.0, 0.5, 1.0], anchors[::-1, ch]),
        )
    return np.clip(blend, 0.0, 1.0)


def tint(gray: np.ndarray, palette_rgb) -> np.ndarray:
    """Colourise a grayscale field with an RGB palette."""
    g = np.asarray(gray, dtype=np.float64)
    rgb = np.asarray(list(palette_rgb), dtype=np.float64).ravel()[:3]
    return np.clip(g[..., None] * rgb[None, None, :], 0.0, 1.0)


def entangle_frames(a: np.ndarray, b: np.ndarray, strength: float) -> np.ndarray:
    """Blend two frames — the local stand-in for the Entanglement Shader.

    A unitary-style mix: `strength` in [0, 1] moves from pure a to pure b, and a
    quarter-turn cross-term keeps the two interacting rather than merely fading,
    so the blend carries interference rather than a plain opacity ramp.
    """
    s = float(np.clip(strength, 0.0, 1.0))
    theta = s * np.pi / 2.0
    return np.clip(a * np.cos(theta) ** 2 + b * np.sin(theta) ** 2
                   + (a * b) ** 0.5 * np.sin(2 * theta) * 0.5, 0.0, 1.0)


def write_png(path: str, frame: np.ndarray) -> str:
    """Write an RGB float frame in [0, 1] to a PNG."""
    data = (np.clip(frame, 0.0, 1.0) * 255.0).astype(np.uint8)
    Image.fromarray(data, mode="RGB").save(path)
    return path


def write_mp4(path: str, frames, fps: int = 12, crf: int = 20,
              size: int | None = None, pix_fmt: str = "yuv420p") -> str:
    """Encode an iterable of RGB float frames to H.264 via ffmpeg.

    Frames are streamed to ffmpeg over a pipe, so a long film does not have to
    be held in memory. `pix_fmt=yuv420p` keeps the output playable in browsers.
    """
    if not ffmpeg_available():
        raise RuntimeError("ffmpeg is not on PATH; cannot encode video")
    first = None
    for first in frames:
        break
    if first is None:
        raise ValueError("no frames supplied")
    h, w = first.shape[:2]
    if size:
        h = w = size

    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{w}x{h}", "-r", str(fps), "-i", "pipe:0",
        "-an", "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
        "-pix_fmt", pix_fmt, path,
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    count = 0
    try:
        for frame in _chain_first(first, frames):
            if frame.shape[0] != h or frame.shape[1] != w:
                img = Image.fromarray((np.clip(frame, 0, 1) * 255).astype(np.uint8))
                img = img.resize((w, h), Image.BICUBIC)
                frame = np.asarray(img, dtype=np.float64) / 255.0
            proc.stdin.write((np.clip(frame, 0, 1) * 255).astype(np.uint8).tobytes())
            count += 1
        proc.stdin.close()
    except BrokenPipeError:
        pass
    stderr = proc.stderr.read().decode("utf-8", "replace")
    code = proc.wait()
    if code != 0:
        raise RuntimeError(f"ffmpeg failed ({code}): {stderr[:500]}")
    if count == 0:
        raise ValueError("no frames were written")
    return path


def _chain_first(first, rest):
    yield first
    for item in rest:
        yield item
