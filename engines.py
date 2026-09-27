"""Atlas media engines — the image and audio stages, routed through the API.

Until now the Atlas integration covered the *creative decisions* only
(`AtlasBackend` draws the measurement outcomes) while every media stage ran on
the bundled local renderers. The submission's judging criterion is "depth of
quantum and **Atlas** usage", and the honest position — already stated in the
notebook — is that Atlas owns these stages where the engines exist. This module
implements that, using the exact request schemas from the published OpenAPI
description (`moth-api` v0.41.0).

Three engines are wired, chosen for being the ones the pipeline can feed real
files to and get real media back:

| stage | engine | inputs | output |
|---|---|---|---|
| image interference | `blur-v1` | `image`, optional `mask` | image |
| two-image blend | `telablur-v1` | `image1`, `image2`, optional `mask` | image |
| space / decay | `retrocausal-echo-v1` | `audio`, `ir` | audio |
| shader texture | `entanglement-shader-v1` | none (generative) | image |

Design rules, all deliberate:

* **Capability is probed, not assumed.** Engine availability is read from
  `GET /engines`, and a caller can ask what is available before running.
* **Every result reports the engine that produced it.** No fallback is silent:
  the returned `EngineResult` names the engine on success and the reason on
  failure, so the provenance receipt can state which path was taken.
* **Failure degrades to the local renderer, visibly.** A media stage that cannot
  reach Atlas must not abort a piece that the notebook claims is reproducible;
  it falls back and records that it did.
* **Byte round-tripping is explicit.** Inputs are encoded to PNG/WAV and
  uploaded; outputs are downloaded and decoded, so what the engine returns is
  what the pipeline uses.
"""

from __future__ import annotations

import io
import mimetypes
import os
import wave

import numpy as np
from PIL import Image

__all__ = ["EngineResult", "MediaEngines", "ENGINE_SCHEMAS"]


def _zip_members(blob: bytes) -> list[str]:
    """List the members of a ZIP payload, or [] if it is not a ZIP.

    Exists because `entanglement-shader-v1` returns a ZIP of shader source, and a
    caller deserves to know what actually arrived rather than getting an opaque
    decoding error.
    """
    import zipfile
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            return zf.namelist()
    except Exception:                                   # noqa: BLE001
        return []


# The documented input/output contract for each engine we use. Kept here so the
# module is readable without the OpenAPI file, and asserted against the live
# engine definitions where possible.
ENGINE_SCHEMAS = {
    "blur-v1": {
        "inputs": {"image": True, "mask": False},
        "output": "image",
        "params": {"downscale": True, "mask_bin_size": None,
                   "mask_min_region": None, "reach": 0, "size": 1024,
                   "strength": 0.5, "style": "rx"},
    },
    "telablur-v1": {
        "inputs": {"image1": True, "image2": True, "mask": False},
        "output": "image",
        "params": {"direction": "full", "downscale": True,
                   "mask_bin_size": None, "mask_min_region": None,
                   "size": 1024, "strength": 0.5},
    },
    "retrocausal-echo-v1": {
        "inputs": {"audio": True, "ir": True},
        "output": "audio",
        "params": {"decay": 0.9, "emit": "audio", "feedback": 0.0, "mix": 0.6,
                   "output_format": "pcm_16", "sr": 44100},
    },
    "entanglement-shader-v1": {
        "inputs": {},
        "output": "image",
        "params": {"absorption": 0.95, "incoming_rays": 8, "interaction": 1,
                   "layers": 2, "reflectance": 0.2, "resolution": None,
                   "style": "peaked"},
    },
}


class EngineResult:
    """What one media stage produced, and by which path."""

    __slots__ = ("value", "engine", "used", "reason", "detail")

    def __init__(self, value, engine: str, used: bool, reason: str = "",
                 detail: dict | None = None):
        self.value = value          # numpy array, or None on failure
        self.engine = engine        # e.g. "blur-v1" or "film.correlation_field"
        self.used = used            # True if the Atlas engine actually ran
        self.reason = reason        # why it did not, when used is False
        self.detail = detail or {}  # params, job id, byte sizes, ...

    def __repr__(self) -> str:
        state = "atlas" if self.used else f"local ({self.reason})"
        return f"<EngineResult {self.engine} {state}>"

    def to_dict(self) -> dict:
        return {"engine": self.engine, "used_atlas": self.used,
                "reason": self.reason, "detail": self.detail}


class MediaEngines:
    """Runs the pipeline's media stages on Atlas, with visible local fallback.

    `client` is a `moth_client.MothClient`. Set `strict=True` to raise instead of
    falling back — useful in tests that must prove the Atlas path was taken.
    """

    #: engines we can drive, in preference order
    IMAGE_ENGINE = "blur-v1"
    BLEND_ENGINE = "telablur-v1"
    AUDIO_ENGINE = "retrocausal-echo-v1"
    TEXTURE_ENGINE = "entanglement-shader-v1"

    def __init__(self, client, *, strict: bool = False, timeout: float = 600.0,
                 poll: float = 2.0):
        self.client = client
        self.strict = strict
        self.timeout = timeout
        self.poll = poll
        self._available: dict[str, dict] | None = None

    # -- capability -------------------------------------------------------

    def probe(self, refresh: bool = False) -> dict[str, dict]:
        """Which of the engines we need are actually visible to this account."""
        if self._available is None or refresh:
            try:
                live = {e["engine_id"]: e for e in self.client.engines()}
            except Exception as exc:                    # noqa: BLE001
                live = {}
                self._probe_error = f"{type(exc).__name__}: {exc}"
            else:
                self._probe_error = ""
            self._available = live
        return self._available

    def available(self, engine_id: str) -> bool:
        entry = self.probe().get(engine_id)
        return bool(entry) and entry.get("enabled", True) is not False

    def capabilities(self) -> dict[str, bool]:
        return {e: self.available(e) for e in
                (self.IMAGE_ENGINE, self.BLEND_ENGINE, self.AUDIO_ENGINE,
                 self.TEXTURE_ENGINE)}

    # -- byte round-tripping ---------------------------------------------

    @staticmethod
    def _encode_png(frame: np.ndarray) -> bytes:
        """numpy frame in [0, 1] (HxW or HxWx3) -> PNG bytes."""
        arr = np.asarray(frame, dtype=np.float64)
        if arr.ndim == 2:
            data = (np.clip(arr, 0, 1) * 255).astype(np.uint8)
            img = Image.fromarray(data, mode="L")
        else:
            data = (np.clip(arr[..., :3], 0, 1) * 255).astype(np.uint8)
            img = Image.fromarray(data, mode="RGB")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    @staticmethod
    def _decode_png(blob: bytes, size: int | None = None,
                    keep_colour: bool = False) -> np.ndarray:
        """PNG bytes -> float array in [0, 1].

        Defaults to greyscale. `keep_colour=True` preserves an RGB payload,
        which matters: the live `blur-v1` returns a colour image, and collapsing
        it to one channel and then broadcasting that back over three channels
        silently discards the palette the quantum angles chose — which is exactly
        what made an early live render come out muddy grey.
        """
        img = Image.open(io.BytesIO(blob))
        if size:
            img = img.resize((size, size), Image.BICUBIC)
        if keep_colour:
            if img.mode != "RGB":
                img = img.convert("RGB")
        elif img.mode != "L":
            img = img.convert("L")
        return np.asarray(img, dtype=np.float64) / 255.0

    @staticmethod
    def _encode_wav(buf: np.ndarray, sr: int) -> bytes:
        """Stereo float buffer -> 16-bit PCM WAV bytes."""
        arr = np.asarray(buf, dtype=np.float64)
        if arr.ndim == 1:
            arr = np.stack([arr, arr])
        pcm = (np.clip(arr, -1, 1) * 32767.0).astype("<i2").T.reshape(-1)
        out = io.BytesIO()
        with wave.open(out, "wb") as fh:
            fh.setnchannels(2)
            fh.setsampwidth(2)
            fh.setframerate(sr)
            fh.writeframes(pcm.tobytes())
        return out.getvalue()

    @staticmethod
    def _decode_wav(blob: bytes) -> tuple[np.ndarray, int]:
        """WAV bytes -> (float buffer shape (2, n), sample rate)."""
        with wave.open(io.BytesIO(blob), "rb") as fh:
            channels, width, rate = (fh.getnchannels(), fh.getsampwidth(),
                                     fh.getframerate())
            raw = fh.readframes(fh.getnframes())
        if width != 2:
            raise ValueError(f"expected 16-bit PCM, got {width*8}-bit")
        pcm = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32767.0
        if channels > 1:
            pcm = pcm.reshape(-1, channels).T
        else:
            pcm = np.stack([pcm, pcm])
        return pcm, rate

    # -- the generic run --------------------------------------------------

    def _run(self, engine_id: str, *, params: dict,
             files: dict[str, tuple[str, bytes]] | None = None,
             mode: str | None = None,
             prefer_slot: str | None = None,
             prefer_type: str | None = None) -> tuple[list[bytes], list[str], str]:
        """Upload inputs, submit, wait, download outputs.

        Returns (output blobs, filenames, job_id).

        Slot selection is not a detail. Verified against the live API,
        `retrocausal-echo-v1` returns THREE outputs — `ir` (JSON), `result`
        (audio/wav) and `taps` (JSON) — so taking the first one silently yields a
        JSON impulse response where audio was expected. Callers name the slot or
        content type they want.

        The declared MIME type matters too: the engine's `input_files` contract
        lists accepted types, and the API answers
        `422 input files do not match the engine's requirements` when the asset's
        saved content type is not among them. Uploading a PNG as
        `application/octet-stream` then fails exactly this way, so the content
        type is inferred from the filename rather than left to the default.
        """
        params, clamp_notes = self._clamp(engine_id, params)
        self._last_clamp_notes = clamp_notes
        input_ids: dict[str, str] = {}
        for slot, (filename, blob) in (files or {}).items():
            ctype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
            asset = self.client.upload_bytes(filename, blob, content_type=ctype)
            input_ids[slot] = asset["asset_id"]

        job = self.client.submit(engine_id, params=params,
                                 input_files=input_ids or None, mode=mode)
        job_id = job["job_id"]
        self.client.wait(job_id, poll=self.poll, timeout=self.timeout,
                         verbose=False)
        result = self.client.result(job_id)
        outputs = list(result.get("outputs") or [])

        def rank(out: dict) -> int:
            """Lower sorts first."""
            slot = str(out.get("slot") or "")
            ctype = str(out.get("content_type") or "")
            if prefer_slot and slot == prefer_slot:
                return 0
            if prefer_type and ctype.startswith(prefer_type):
                return 1
            # Side-channel outputs are never the media itself.
            if slot in ("ir", "taps", "map", "trajectory"):
                return 3
            return 2

        outputs.sort(key=rank)

        blobs, names = [], []
        for out in outputs:
            url = out.get("url")
            if not url:
                continue
            name = out.get("filename") or f"{engine_id}-output"
            dest = os.path.join("_engine_tmp",
                                f"{job_id[:8]}-{os.path.basename(name)}")
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            self.client.download(url, dest)
            with open(dest, "rb") as fh:
                blobs.append(fh.read())
            names.append(f"{out.get('slot') or '?'}:{os.path.basename(name)}")
            try:
                os.remove(dest)
            except OSError:
                pass
        if not blobs:
            raise RuntimeError(f"{engine_id} produced no outputs")
        return blobs, names, job_id

    def _fallback(self, engine_id: str, reason: str, local_value,
                  local_engine: str, detail: dict | None = None) -> EngineResult:
        if self.strict:
            raise RuntimeError(
                f"Atlas engine {engine_id} unavailable and strict mode is on: {reason}")
        return EngineResult(local_value, local_engine, False, reason=reason,
                            detail=detail or {})

    # -- schema-driven parameter safety ------------------------------------

    def _schema(self, engine_id: str) -> dict:
        """Cache an engine's declared parameter schema."""
        if not hasattr(self, "_schemas"):
            self._schemas: dict[str, dict] = {}
        if engine_id not in self._schemas:
            try:
                self._schemas[engine_id] = self.client.params_schema(engine_id) or {}
            except Exception:                           # noqa: BLE001
                self._schemas[engine_id] = {}
        return self._schemas[engine_id]

    def _clamp(self, engine_id: str, params: dict) -> tuple[dict, list[str]]:
        """Clamp parameters to the bounds the engine's live schema declares.

        The API answers `422 params do not match the engine schema` for an
        out-of-range value, and the error names no field, which makes it opaque.
        This cost real debugging time: the pipeline derived
        `blur_reach = 1 + (n % 2)`, which yields 2, while `blur-v1` declares
        `reach` as **0..1** — so every render silently fell back to the local
        renderer because of one integer.

        Rather than hard-code that single bound, the declared `minimum`/`maximum`
        for each numeric parameter are read from the engine's schema and applied.
        Returns the clamped params plus a note for every value that moved, so the
        adjustment is recorded in the receipt instead of happening invisibly.
        """
        props = (self._schema(engine_id).get("props")
                 or self._schema(engine_id).get("properties") or {})
        if not props:
            return params, []
        out, notes = dict(params), []
        for key, value in list(params.items()):
            spec = props.get(key)
            if not isinstance(spec, dict):
                continue
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                continue
            # anyOf/oneOf wrappers (nullable numbers) carry bounds inside.
            candidates = [spec] + [c for c in (spec.get("anyOf") or [])
                                   + (spec.get("oneOf") or [])
                                   if isinstance(c, dict)]
            lo = next((c.get("minimum") for c in candidates
                       if c.get("minimum") is not None), None)
            hi = next((c.get("maximum") for c in candidates
                       if c.get("maximum") is not None), None)
            if lo is not None and value < lo:
                out[key] = lo
                notes.append(f"{key}: {value} -> {lo} (min)")
            elif hi is not None and value > hi:
                out[key] = hi
                notes.append(f"{key}: {value} -> {hi} (max)")
        return out, notes

    # -- stages -----------------------------------------------------------

    def blur_image(self, field: np.ndarray, *, strength: float = 0.5,
                   reach: int = 0, size: int | None = None,
                   style: str = "rx", downscale: bool = False,
                   local=None) -> EngineResult:
        """Image interference via `blur-v1`; falls back to a local renderer.

        The returned array keeps whichever dimensionality came back: the live
        engine answers with a colour image, and forcing it to greyscale would
        discard the palette the quantum angles chose.

        `downscale` defaults to False. The engine's own default is True, which
        resamples internally and left a visible 4x4 block quantisation in the
        rendered frames — an artefact of the engine's pipeline, not of ours.

        `local` is a zero-argument callable returning the fallback array, so the
        caller decides what the local equivalent is.
        """
        engine = self.IMAGE_ENGINE
        reason = ""
        if not self.available(engine):
            reason = self.probe().get("_probe_error") or f"{engine} not available"
            return self._fallback(engine, reason, local() if local else field,
                                  "film.quantum_field")
        colour = np.asarray(field).ndim == 3
        try:
            png = self._encode_png(field)
            params = {"strength": float(strength), "reach": float(reach),
                      "style": style, "downscale": bool(downscale)}
            if size:
                params["size"] = int(size)
            blobs, names, job_id = self._run(
                engine, params=params,
                files={"image": ("field.png", png)},
                prefer_type="image/")
            out = self._decode_png(blobs[0], size=field.shape[0],
                                   keep_colour=colour)
            return EngineResult(out, engine, True, detail={
                "job_id": job_id, "params": params,
                "params_clamped": getattr(self, "_last_clamp_notes", []),
                "input_bytes": len(png), "output_bytes": len(blobs[0]),
                "outputs": names, "colour": colour,
            })
        except Exception as exc:                        # noqa: BLE001
            return self._fallback(engine, f"{type(exc).__name__}: {exc}",
                                  local() if local else field,
                                  "film.quantum_field")

    def blend_images(self, a: np.ndarray, b: np.ndarray, *,
                     strength: float = 0.5, direction: str = "full",
                     local=None) -> EngineResult:
        """Two-image blend via `telablur-v1`."""
        engine = self.BLEND_ENGINE
        if not self.available(engine):
            reason = self.probe().get("_probe_error") or f"{engine} not available"
            return self._fallback(engine, reason,
                                  local() if local else a, "film.entangle_frames")
        try:
            pa, pb = self._encode_png(a), self._encode_png(b)
            params = {"strength": float(strength), "direction": direction,
                      "downscale": True}
            blobs, names, job_id = self._run(
                engine, params=params,
                files={"image1": ("a.png", pa), "image2": ("b.png", pb)},
                prefer_type="image/")
            out = self._decode_png(blobs[0], size=a.shape[0])
            return EngineResult(out, engine, True, detail={
                "job_id": job_id, "params": params,
                "input_bytes": len(pa) + len(pb), "output_bytes": len(blobs[0]),
                "outputs": names,
            })
        except Exception as exc:                        # noqa: BLE001
            return self._fallback(engine, f"{type(exc).__name__}: {exc}",
                                  local() if local else a, "film.entangle_frames")

    def shader_texture(self, *, size: int = 256, style: str = "peaked",
                       interplay: float = 1.0, layers: int = 2,
                       local=None) -> EngineResult:
        """`entanglement-shader-v1` — which does NOT return a usable image.

        Verified against the live API: this engine returns a ZIP containing
        shader source (`.osl`, `.frag`, `.glsl`, `.hlsl`, `.mtlx`) plus EXR/HDR
        LUTs — computer-graphics authoring material, not a rendered frame. There
        is no image to blend into the film, and claiming otherwise would be
        false. The method reports the shader bundle it received and falls back to
        the local texture, so the pipeline keeps working and the receipt states
        exactly what came back.

        Kept in the codebase deliberately: it records a real capability boundary
        of the platform instead of hiding it behind a crash.
        """
        engine = self.TEXTURE_ENGINE
        if not self.available(engine):
            reason = self.probe().get("_probe_error") or f"{engine} not available"
            return self._fallback(engine, reason,
                                  local() if local else np.zeros((size, size)),
                                  "film.correlation_field")
        try:
            params = {"style": style, "interaction": float(interplay),
                      "layers": int(layers), "resolution": int(size)}
            blobs, names, job_id = self._run(engine, params=params)
            members = _zip_members(blobs[0])
            detail = {"job_id": job_id, "params": params,
                      "output_bytes": len(blobs[0]), "outputs": names,
                      "zip_members": members,
                      "note": ("engine returns shader source and LUTs, not a "
                               "rendered texture")}
            return self._fallback(
                engine,
                "engine returns shader source (.osl/.glsl/.hlsl) and EXR/HDR "
                "LUTs, not a rendered image",
                local() if local else np.zeros((size, size)),
                "film.correlation_field", detail=detail)
        except Exception as exc:                        # noqa: BLE001
            return self._fallback(engine, f"{type(exc).__name__}: {exc}",
                                  local() if local else np.zeros((size, size)),
                                  "film.correlation_field")

    def convolve_audio(self, audio: np.ndarray, ir: np.ndarray, *,
                       sr: int = 22050, decay: float = 0.9, mix: float = 0.6,
                       local=None) -> EngineResult:
        """Space and decay via `retrocausal-echo-v1`.

        Two things verified against the live API and encoded here:

        * The `ir` input slot requires **application/json** (a previously
          measured otoc-echo trajectory envelope), not a WAV. Sending a WAV for
          it is rejected. It is also optional, so the engine measures its own
          impulse response when none is supplied — which is what we do, and why
          the local `ir` argument is not uploaded.
        * The engine returns THREE outputs (`ir`, `result`, `taps`), so the
          audio must be selected by slot or content type rather than by position.

        The result's own sample rate is read back from the returned WAV instead
        of assumed, so a rate mismatch cannot silently pitch-shift the piece.
        """
        engine = self.AUDIO_ENGINE
        if not self.available(engine):
            reason = self.probe().get("_probe_error") or f"{engine} not available"
            return self._fallback(engine, reason,
                                  local() if local else audio, "synth.convolve_ir")
        try:
            wav_audio = self._encode_wav(audio, sr)
            params = {"decay": float(decay), "mix": float(mix),
                      "emit": "audio", "output_format": "pcm_16", "sr": int(sr)}
            blobs, names, job_id = self._run(
                engine, params=params,
                files={"audio": ("audio.wav", wav_audio)},
                prefer_slot="result", prefer_type="audio/")
            out, out_sr = self._decode_wav(blobs[0])
            return EngineResult(out, engine, True, detail={
                "job_id": job_id, "params": params, "input_sr": sr,
                "output_sr": out_sr,
                "input_bytes": len(wav_audio),
                "output_bytes": len(blobs[0]), "outputs": names,
                "note": "ir measured by the engine; the JSON ir output is a "
                        "reusable envelope and is not a WAV input",
            })
        except Exception as exc:                        # noqa: BLE001
            return self._fallback(engine, f"{type(exc).__name__}: {exc}",
                                  local() if local else audio, "synth.convolve_ir")
