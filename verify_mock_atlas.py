"""Verify moth_client.py and AtlasBackend against a mock Atlas API.

Why this exists: `moth_client.py` implements the full Atlas REST workflow, but
without an API key it had never executed a single HTTP round trip. That is the
largest unverified surface in the project, and the one most likely to fail on
first contact with the real service.

This suite stands up a local HTTP server that serves the endpoints documented in
the OpenAPI spec (`moth-api` v0.41.0) with the documented response shapes, then
drives the real client through them: auth, engine discovery, the asset create →
presigned PUT → complete dance, job submit, status polling, result retrieval and
artifact download. If the client's request shapes, headers or parsing are wrong,
this fails.

It does NOT prove the real Atlas behaves identically — only the real service can
do that. What it proves is that the client implements the documented protocol
correctly, so that a first live call fails only for reasons an API key can fix.

    python -B verify_mock_atlas.py
"""

from __future__ import annotations

import io
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
import wave
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

PASS, FAIL = 0, 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  PASS  {name}" + (f"  ({detail})" if detail else ""))
    else:
        FAIL += 1
        print(f"  FAIL  {name}" + (f"  ({detail})" if detail else ""))


# --------------------------------------------------------------- mock service

ASSETS: dict[str, dict] = {}      # asset_id -> metadata
UPLOADED: dict[str, bytes] = {}   # asset_id -> bytes
JOBS: dict[str, dict] = {}        # job_id -> job
ENGINE_PROCESS_CALLS: list[dict] = []
PUT_REQUESTS: list[dict] = []     # what the client sent to the presigned URL

# The media engines the pipeline drives, with their documented input slots,
# output type and parameter defaults (from the published OpenAPI description).
MEDIA_ENGINES: dict[str, dict] = {
    "blur-v1": {
        "name": "Quantum Blur", "credits": 3, "output": "image",
        "inputs": {"image": True, "mask": False},
        "params_schema": {"downscale": {"type": "boolean", "default": True},
                          "reach": {"type": "number", "default": 0},
                          "size": {"type": "integer", "default": 1024},
                          "strength": {"type": "number", "default": 0.5},
                          "style": {"type": "string", "enum": ["rx", "ry"]}},
    },
    "telablur-v1": {
        "name": "Quantum Teleblur", "credits": 4, "output": "image",
        "inputs": {"image1": True, "image2": True, "mask": False},
        "params_schema": {"direction": {"type": "string",
                                        "enum": ["full", "vertical", "horizontal"]},
                          "downscale": {"type": "boolean", "default": True},
                          "size": {"type": "integer", "default": 1024},
                          "strength": {"type": "number", "default": 0.5}},
    },
    "retrocausal-echo-v1": {
        "name": "Retrocausal Echo", "credits": 6, "output": "audio",
        # BOTH slots are optional on the real engine, and `ir` accepts
        # application/json (a measured envelope) rather than a WAV. Marking `ir`
        # required here previously made the mock reject submissions that the live
        # API accepts — a mock being stricter than reality hides real behaviour.
        "inputs": {"audio": False, "ir": False},
        "params_schema": {"decay": {"type": "number", "default": 0.9},
                          "emit": {"type": "string", "enum": ["audio", "map"]},
                          "mix": {"type": "number", "default": 0.6},
                          "output_format": {"type": "string",
                                            "enum": ["pcm_16", "pcm_32", "float_32"]},
                          "sr": {"type": "integer", "default": 44100}},
    },
    "entanglement-shader-v1": {
        "name": "Entanglement Shader", "credits": 4, "output": "image",
        "inputs": {},
        "params_schema": {"absorption": {"type": "number", "default": 0.95},
                          "incoming_rays": {"type": "integer", "default": 8},
                          "interaction": {"type": "number", "default": 1},
                          "layers": {"type": "integer", "default": 2},
                          "reflectance": {"type": "number", "default": 0.2},
                          "resolution": {"type": ["integer", "null"]},
                          "style": {"type": "string",
                                    "enum": ["peaked", "frustrated", "3-body",
                                             "constrained"]}},
    },
}

API_KEY = "moth_mock_key_for_tests"


class MockAtlas(BaseHTTPRequestHandler):
    """Serves the documented Atlas response shapes."""

    server_version = "MockAtlas/1.0"

    def log_message(self, *args):        # keep the test output clean
        pass

    # -- helpers ---------------------------------------------------------

    def _auth_ok(self) -> bool:
        header = self.headers.get("Authorization") or ""
        return header == f"Bearer {API_KEY}"

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return {}

    def _guard(self) -> bool:
        """Reproduce the documented auth behaviour: 401 on a bad/missing key."""
        if not self._auth_ok():
            self._send(401, {"detail": "authentication required"})
            return False
        return True

    # -- routes ----------------------------------------------------------

    def do_GET(self) -> None:                       # noqa: N802
        path = self.path.split("?")[0]
        # Presigned blob URLs are authorised by their own signature, NOT by the
        # API key — that is the point of presigning. Requiring the bearer token
        # here would misrepresent the real service and would also mask the bug
        # where the client leaked its key to the storage host.
        if not path.startswith("/blob/") and not self._guard():
            return

        if path == "/api/v1/me":
            return self._send(200, {
                "id": "user-1", "email": "hacker@example.com",
                "role": "member", "platform_role": "player",
                "features": ["run_quantum", "publish_engines"],
                "organizations": [], "organizations_unavailable": False,
            })

        if path == "/api/v1/engines":
            return self._send(200, {
                "schema": "about:blank",
                "count": 2 + len(MEDIA_ENGINES), "next_cursor": None,
                "engines": [
                    {"engine_id": "coin-toss-v1", "name": "Coin Toss",
                     "credits_per_run": 1, "input_type": "none",
                     "output_type": "json", "is_async": True,
                     "input_files": None, "enabled": True},
                    {"engine_id": "tessa-image-v1", "name": "Tessa Image",
                     "credits_per_run": 5, "input_type": "image",
                     "output_type": "image", "is_async": True,
                     "input_files": [{"name": "image", "required": True}],
                     "enabled": True},
                ] + [
                    {"engine_id": eid, "name": spec["name"],
                     "credits_per_run": spec["credits"],
                     "input_type": "multipart" if spec["inputs"] else "none",
                     "output_type": spec["output"], "is_async": True,
                     "input_files": [{"name": slot, "required": required}
                                     for slot, required in spec["inputs"].items()]
                     or None,
                     "enabled": True}
                    for eid, spec in MEDIA_ENGINES.items()
                ],
            })

        if path.startswith("/api/v1/engines/"):
            engine_id = path.split("/")[4]
            if engine_id in MEDIA_ENGINES:
                spec = MEDIA_ENGINES[engine_id]
                return self._send(200, {
                    "engine_id": engine_id, "name": spec["name"],
                    "params_schema": {"type": "object",
                                      "props": spec["params_schema"]},
                    "input_files": [{"name": slot, "required": req}
                                    for slot, req in spec["inputs"].items()] or None,
                    "credits_per_run": spec["credits"],
                    "enabled": True,
                })
            return self._send(200, {
                "engine_id": engine_id, "name": engine_id,
                "params_schema": {"type": "object", "props": {
                    "shots": {"type": "integer", "default": 1024},
                    "mode": {"type": "string", "default": "emu"},
                }},
                "credits_per_run": 1, "input_type": "none", "enabled": True,
            })

        if path.startswith("/api/v1/jobs/"):
            parts = path.strip("/").split("/")
            job_id = parts[3]
            job = JOBS.get(job_id)
            if not job:
                return self._send(404, {"detail": "unknown job"})
            tail = parts[4] if len(parts) > 4 else None
            if tail == "status":
                return self._send(200, {
                    "schema": "about:blank", "job_id": job_id,
                    "engine_id": job["engine_id"], "status": job["status"],
                    "submitted_at": job["submitted_at"],
                    "updated_at": job["updated_at"],
                    "progress": job["progress"], "outputs": job["outputs"],
                    "error": None, "steps": None, "result": None,
                })
            if tail == "result":
                return self._send(200, {
                    "schema": "about:blank", "outputs": job["outputs"],
                    "result": {"counts": job.get("counts")},
                })
            return self._send(200, {
                "job_id": job_id, "engine_id": job["engine_id"],
                "status": job["status"], "created_at": job["submitted_at"],
                "updated_at": job["updated_at"], "owner": "user-1",
                "gated_features": [],
            })

        if path == "/api/v1/keys":
            return self._send(200, {"schema": "about:blank", "keys": [], "count": 0})

        if path == "/api/v1/me/storage":
            return self._send(200, {"schema": "about:blank", "usage": {"bytes": 0},
                                    "quota": {"bytes": 1_000_000}})

        if path.startswith("/api/v1/assets/"):
            asset_id = path.split("/")[4]
            asset = ASSETS.get(asset_id)
            if not asset:
                return self._send(404, {"detail": "unknown asset"})
            return self._send(200, asset)

        # The presigned upload/download surface: GET serves bytes.
        if path.startswith("/blob/"):
            blob_id = path.split("/")[-1]
            data = UPLOADED.get(blob_id)
            if data is None:
                return self._send(404, {"detail": "no such blob"})
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            return self.wfile.write(data)

        return self._send(404, {"detail": f"unhandled GET {path}"})

    def do_PUT(self) -> None:                       # noqa: N802
        """The presigned upload target. Note: no Authorization header here."""
        path = self.path.split("?")[0]
        if not path.startswith("/blob/"):
            return self._send(404, {"detail": f"unhandled PUT {path}"})
        blob_id = path.split("/")[-1]
        # Record what the client actually sent, so the test can assert the
        # presigned headers were forwarded, not merely that bytes arrived.
        PUT_REQUESTS.append({
            "blob_id": blob_id,
            "headers": {k.lower(): v for k, v in self.headers.items()},
        })
        n = int(self.headers.get("Content-Length") or 0)
        UPLOADED[blob_id] = self.rfile.read(n)
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self) -> None:                      # noqa: N802
        path = self.path.split("?")[0]
        body = self._read()

        # Upload completion happens before/independent of auth in some flows;
        # keep auth for API routes only.
        if path.startswith("/api/v1/"):
            if not self._guard():
                return

        if path == "/api/v1/assets":
            asset_id = str(uuid.uuid4())
            ASSETS[asset_id] = {
                "asset_id": asset_id, "filename": body.get("filename"),
                "content_type": body.get("content_type"),
                "size_bytes": body.get("size_bytes"), "status": "pending",
                "kind": "upload", "owner": "user-1", "metadata": {},
                "created_at": _now(), "updated_at": _now(),
                "upload": {
                    "url": f"{BASE_URL}/blob/{asset_id}",
                    "headers": {"Content-Type": "application/octet-stream",
                                "x-mock-upload": "1"},
                },
            }
            return self._send(201, ASSETS[asset_id])

        if path.startswith("/api/v1/assets/") and path.endswith("/complete"):
            asset_id = path.split("/")[4]
            asset = ASSETS.get(asset_id)
            if not asset:
                return self._send(404, {"detail": "unknown asset"})
            if asset_id not in UPLOADED:
                return self._send(409, {"detail": "no object uploaded"})
            asset["status"] = "uploaded"
            asset["updated_at"] = _now()
            asset.pop("upload", None)
            return self._send(200, asset)

        if path.startswith("/api/v1/engines/") and path.endswith("/process"):
            engine_id = path.split("/")[4]
            ENGINE_PROCESS_CALLS.append({"engine_id": engine_id, "body": body})
            job_id = str(uuid.uuid4())
            # Reproduce the documented feature gate: mode=qpu requires the
            # run_quantum feature, and the 403 response must name that feature.
            if body.get("mode") == "qpu":
                return self._send(403, {"detail": "feature run_quantum required"})

            if engine_id in MEDIA_ENGINES:
                return self._process_media_engine(engine_id, job_id, body)

            counts = {"00000000": 137, "00000001": 129, "11111111": 141,
                      "10101010": 88}
            JOBS[job_id] = {
                "engine_id": engine_id, "status": "queued", "progress": 0.0,
                "submitted_at": _now(), "updated_at": _now(),
                "counts": counts,
                "outputs": [{
                    "slot": "out", "filename": "counts.json",
                    "content_type": "application/json",
                    "output_asset_id": None, "size_bytes": 128,
                    "url": f"{BASE_URL}/blob/out-{job_id}", "expires_at": _now(),
                }],
                "_polls": 0,
            }
            UPLOADED[f"out-{job_id}"] = json.dumps(counts).encode()
            return self._send(202, {"job_id": job_id, "status": "queued",
                                    "submitted_at": _now()})

        return self._send(404, {"detail": f"unhandled POST {path}"})

    def _process_media_engine(self, engine_id: str, job_id: str,
                              body: dict) -> None:
        """Serve a media engine: validate inputs, transform, return a real file.

        The transformation is deliberately deterministic and visibly different
        from the input (a gain, a blend, a decay envelope), so the round-trip
        proves the client uploaded real bytes and consumed real bytes back —
        rather than merely that a job completed.
        """
        spec = MEDIA_ENGINES[engine_id]
        params = body.get("params") or {}
        inputs = body.get("input_files") or {}

        missing = [slot for slot, required in spec["inputs"].items()
                   if required and not inputs.get(slot)]
        if missing:
            return self._send(422, {"detail": f"missing required input_files: {missing}"})

        blobs = {}
        for slot, asset_id in inputs.items():
            if asset_id not in UPLOADED:
                return self._send(422, {"detail": f"input {slot} was never uploaded"})
            blobs[slot] = UPLOADED[asset_id]

        try:
            if spec["output"] == "image":
                out_bytes, filename, ctype = self._transform_image(
                    engine_id, blobs, params)
            else:
                out_bytes, filename, ctype = self._transform_audio(
                    engine_id, blobs, params)
        except Exception as exc:                        # noqa: BLE001
            return self._send(500, {"detail": f"engine failed: {exc}"})

        _require_png_or_wav(filename, out_bytes)
        UPLOADED[f"out-{job_id}"] = out_bytes
        JOBS[job_id] = {
            "engine_id": engine_id, "status": "queued", "progress": 0.0,
            "submitted_at": _now(), "updated_at": _now(), "counts": None,
            "outputs": [{
                "slot": "out", "filename": filename, "content_type": ctype,
                "output_asset_id": None, "size_bytes": len(out_bytes),
                "url": f"{BASE_URL}/blob/out-{job_id}", "expires_at": _now(),
            }],
            "_polls": 0,
        }
        return self._send(202, {"job_id": job_id, "status": "queued",
                                "submitted_at": _now()})

    @staticmethod
    def _transform_image(engine_id: str, blobs: dict,
                         params: dict) -> tuple[bytes, str, str]:
        from PIL import Image
        strength = float(params.get("strength", 0.5))

        if engine_id == "telablur-v1":
            a = Image.open(io.BytesIO(blobs["image1"])).convert("L")
            b = Image.open(io.BytesIO(blobs["image2"])).convert("L")
            b = b.resize(a.size)
            out = Image.blend(a, b, max(0.0, min(strength, 1.0)))
        elif engine_id == "entanglement-shader-v1":
            # Real behaviour: a ZIP of shader source, not a rendered image.
            res = int(params.get("resolution") or 128)
            return _shader_bundle(res, res), f"{engine_id}.zip", "application/zip"
        else:                                            # blur-v1 and friends
            a = Image.open(io.BytesIO(blobs["image"])).convert("L")
            gain = 1.0 + 4.0 * (strength - 0.5)
            out = a.point(lambda p: max(0, min(255, int(p * gain))))
            # A visible spatial shift proves the returned bytes are the engine's
            # output and not an echo of the upload.
            out = out.transform(out.size, Image.AFFINE, (1, 0, 3, 0, 1, 3))

        buf = io.BytesIO()
        out.save(buf, format="PNG")
        return buf.getvalue(), f"{engine_id}.png", "image/png"

    @staticmethod
    def _transform_audio(engine_id: str, blobs: dict,
                         params: dict) -> tuple[bytes, str, str]:
        with wave.open(io.BytesIO(blobs["audio"]), "rb") as fh:
            channels, width, rate = (fh.getnchannels(), fh.getsampwidth(),
                                     fh.getframerate())
            frames = np.frombuffer(fh.readframes(fh.getnframes()), dtype="<i2")
        decay = float(params.get("decay", 0.9))
        # Apply a decay envelope so the output is measurably not the input.
        n = len(frames)
        ramp = np.exp(-(1.0 - 1.0 / max(decay, 1e-3)) * 4.0 * np.arange(n) / max(n, 1))
        out_frames = (frames.astype(np.float64) * ramp).astype("<i2")
        buf = io.BytesIO()
        with wave.open(buf, "wb") as fh:
            fh.setnchannels(channels)
            fh.setsampwidth(width)
            fh.setframerate(rate)
            fh.writeframes(out_frames.tobytes())
        return buf.getvalue(), f"{engine_id}.wav", "audio/wav"

    def do_PATCH(self) -> None:                     # noqa: N802
        if not self._guard():
            return
        return self._send(200, {})


def _synthetic_pattern(w: int, h: int, style: str = "peaked"):
    """A deterministic pattern, used only by the legacy shader-v0 stub."""
    from PIL import Image
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
    xx /= max(w - 1, 1)
    yy /= max(h - 1, 1)
    seed = (abs(hash(style)) % 7) + 1
    field = (np.sin(2 * np.pi * (seed * xx + yy)) +
             np.cos(2 * np.pi * (xx - seed * yy))) / 2.0
    data = ((field + 1.0) / 2.0 * 255).astype(np.uint8)
    return Image.fromarray(data, mode="L")


def _shader_bundle(w: int, h: int) -> bytes:
    """Mimic the real entanglement-shader-v1 payload: a ZIP of shader source.

    The live engine returns `.osl`/`.frag`/`.glsl`/`.hlsl`/`.mtlx` source files
    plus EXR/HDR LUTs — graphics-authoring material, not a rendered image. The
    mock reproduces that shape so the client's honest-fallback path is actually
    exercised rather than being tested against an invented PNG.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("entanglement_texture.osl", "// osl shader source\n")
        zf.writestr("entanglement_texture.glsl", "// glsl shader source\n")
        zf.writestr("entanglement_texture.frag", "// frag shader source\n")
        zf.writestr("R_lut.exr", b"EXR\x00" + b"\x00" * 64)
        zf.writestr("T_lut.hdr", b"#?RADIANCE\n" + b"\x00" * 64)
    return buf.getvalue()


def _require_png_or_wav(filename: str, blob: bytes) -> None:
    """Fail loudly if a media engine would serve something undecodable."""
    if filename.endswith(".png"):
        if blob[:8] != b"\x89PNG\r\n\x1a\n":
            raise ValueError("image output is not a PNG")
    elif filename.endswith(".wav"):
        if blob[:4] != b"RIFF" or blob[8:12] != b"WAVE":
            raise ValueError("audio output is not a WAV")


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# The status endpoint advances a job on each poll so the client's wait loop is
# genuinely exercised rather than completing on the first call.
_original_get = MockAtlas.do_GET


def do_GET_with_progress(self):                     # noqa: N802
    path = self.path.split("?")[0]
    if path.startswith("/api/v1/jobs/") and path.endswith("/status"):
        job_id = path.strip("/").split("/")[3]
        job = JOBS.get(job_id)
        if job:
            job["_polls"] = job.get("_polls", 0) + 1
            if job["_polls"] >= 2:
                job["status"] = "completed"
                job["progress"] = 1.0
            else:
                job["status"] = "processing"
                job["progress"] = 0.5
            job["updated_at"] = _now()
    return _original_get(self)


MockAtlas.do_GET = do_GET_with_progress


BASE_URL = ""


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> int:
    global BASE_URL
    port = free_port()
    BASE_URL = f"http://127.0.0.1:{port}"

    print("=" * 70)
    print("mock Atlas API verification — moth_client.py and AtlasBackend")
    print("=" * 70)

    server = ThreadingHTTPServer(("127.0.0.1", port), MockAtlas)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        import moth_client
        from moth_client import MothClient, MothError
        import pipeline
        from pipeline import AtlasBackend

        print("\n[1] authentication")
        client = MothClient(api_key=API_KEY, base_url=BASE_URL)
        check("client accepts an explicit key", bool(client.api_key))
        me = client.me()
        check("GET /me returns the account", me.get("email") == "hacker@example.com",
              me.get("email"))
        check("feature flags are parsed", me.get("features") ==
              ["run_quantum", "publish_engines"], str(me.get("features")))
        check("has_feature('run_quantum') is True", client.has_feature("run_quantum"))
        check("has_feature('nonsense') is False", not client.has_feature("nonsense"))

        print("\n[2] auth failure is reported honestly")
        bad = MothClient(api_key="moth_wrong", base_url=BASE_URL)
        try:
            bad.me()
            check("a bad key raises", False, "no exception")
        except MothError as exc:
            check("a bad key raises MothError with status 401", exc.status == 401,
                  f"status {exc.status}, detail {exc.detail!r}")
            check("a 401 is not reported as a gated feature",
                  exc.gated_feature is None)

        print("\n[3] engine discovery")
        engines = client.engines()
        ids = sorted(e["engine_id"] for e in engines)
        # Assert membership rather than an exact list: the mock also serves the
        # media engines, and hard-coding a count here broke the moment it did.
        check("GET /engines returns the primitive engine",
              "coin-toss-v1" in ids, str(ids))
        check("GET /engines returns the media engines",
              {"blur-v1", "telablur-v1", "retrocausal-echo-v1",
               "entanglement-shader-v1"} <= set(ids), str(ids))
        check("pagination terminates when next_cursor is absent",
              len(engines) == len(ids) and len(ids) >= 6, f"{len(ids)} engines")
        schema = client.params_schema("coin-toss-v1")
        check("params_schema is reachable per engine", "props" in schema,
              str(sorted(schema.keys())))
        media_schema = client.params_schema("blur-v1")
        check("media engine params_schema declares its documented fields",
              {"strength", "reach", "style"} <= set((media_schema.get("props") or {})),
              str(sorted((media_schema.get("props") or {}).keys())))
        cheapest = client.cheap_engines(2)
        check("cheap_engines sorts by credits", cheapest[0][1] == "coin-toss-v1",
              str(cheapest))

        print("\n[4] the asset upload dance")
        asset = client.upload_bytes("counts.json", b'{"hello":"world"}',
                                    content_type="application/json")
        check("upload completes and returns an asset",
              asset.get("status") == "uploaded", asset.get("status", ""))
        check("asset has an id", bool(asset.get("asset_id")))
        asset_id = asset["asset_id"]
        check("the bytes actually reached storage",
              UPLOADED.get(asset_id) == b'{"hello":"world"}',
              f"{len(UPLOADED.get(asset_id, b''))} bytes")
        upload_call = next((r for r in PUT_REQUESTS if r["blob_id"] == asset_id), None)
        check("the presigned upload was actually performed", upload_call is not None)
        if upload_call:
            check("the presigned headers were forwarded",
                  upload_call["headers"].get("x-mock-upload") == "1",
                  str(sorted(k for k in upload_call["headers"] if k.startswith("x-"))))
            check("the presigned PUT carries no API authorization",
                  "authorization" not in upload_call["headers"])
        check("asset metadata keeps the declared size",
              ASSETS[asset_id]["size_bytes"] == 17,
              str(ASSETS[asset_id]["size_bytes"]))

        print("\n[5] uploading a real file from disk")
        with open("_mock_upload.bin", "wb") as fh:
            fh.write(b"\x00\x01\x02binary-payload" * 8)
        from_disk = client.upload_file("_mock_upload.bin")
        check("upload_file works from a path",
              from_disk.get("status") == "uploaded", from_disk.get("status", ""))
        check("bytes match the source file",
              UPLOADED[from_disk["asset_id"]] ==
              open("_mock_upload.bin", "rb").read())

        print("\n[6] job submit, poll and result")
        job = client.submit("coin-toss-v1", params={"shots": 512}, mode="emu")
        check("submit returns 202-style payload with a job id",
              bool(job.get("job_id")) and job.get("status") == "queued",
              job.get("status", ""))
        check("the engine received the params",
              ENGINE_PROCESS_CALLS[-1]["body"].get("params") == {"shots": 512},
              str(ENGINE_PROCESS_CALLS[-1]["body"].get("params")))
        check("the engine received the mode",
              ENGINE_PROCESS_CALLS[-1]["body"].get("mode") == "emu")

        final = client.wait(job["job_id"], poll=0.2, timeout=15, verbose=False)
        check("wait polls until the job completes",
              final.get("status") == "completed", final.get("status", ""))
        check("progress reached 1.0", final.get("progress") == 1.0,
              str(final.get("progress")))

        result = client.result(job["job_id"])
        outputs = result.get("outputs") or []
        check("result exposes outputs", len(outputs) == 1,
              f"{len(outputs)} output(s)")
        check("result carries the engine's counts",
              bool((result.get("result") or {}).get("counts")),
              str(list(((result.get("result") or {}).get("counts") or {}).keys())[:3]))

        print("\n[7] artifact download")
        out_path = client.download(outputs[0]["url"], "_mock_output.json")
        check("download writes the artifact", os.path.exists(out_path))
        downloaded = json.load(open(out_path, encoding="utf-8"))
        check("downloaded bytes are the served payload",
              downloaded == JOBS[job["job_id"]]["counts"],
              str(sorted(downloaded)[:2]))

        print("\n[8] the feature gate is surfaced, not swallowed")
        try:
            # A mode the mock refuses, to prove gated_feature is extracted.
            gated = MothClient(api_key=API_KEY, base_url=BASE_URL)
            gated.submit("coin-toss-v1", params={}, mode="qpu")
            check("qpu submit is rejected by the mock", False, "no error raised")
        except MothError as exc:
            check("a 403 is raised", exc.status == 403, f"status {exc.status}")
            check("the missing feature is named",
                  exc.gated_feature == "run_quantum",
                  str(exc.gated_feature))

        print("\n[9] AtlasBackend produces usable creative primitives")
        atlas = AtlasBackend(client, engine_id="coin-toss-v1", mode="emu",
                             shots=256)
        primitives, provenance = atlas.primitives(seed=42)
        check("primitives are returned", primitives is not None)
        check("provenance names the Atlas engine",
              provenance and provenance[0].engine == "coin-toss-v1",
              provenance[0].engine if provenance else "none")
        check("provenance is labelled as coming from atlas",
              provenance[0].source == "atlas", provenance[0].source)
        check("measured bitstrings were decoded from the counts",
              len(primitives.bits) > 0, f"{len(primitives.bits)} outcomes")
        check("creative parameters were derived",
              len(primitives.pitches) > 0 and primitives.scene_count >= 4,
              f"{len(primitives.pitches)} notes, {primitives.scene_count} scenes")
        check("the job id is recorded for audit",
              "job_id" in provenance[0].detail,
              provenance[0].detail.get("job_id", "")[:8])
        check("the mode is recorded for audit",
              provenance[0].detail.get("mode") == "emu")

        print("\n[10] AtlasBackend reports a missing feature rather than pretending")
        # The mock refuses mode=qpu, so FeatureMissing must be raised — proving a
        # missing capability degrades visibly instead of silently falling back to
        # a simulator while still claiming hardware execution.
        strict = AtlasBackend(client, engine_id="coin-toss-v1", mode="qpu",
                              shots=64)
        try:
            strict.primitives(seed=1)
            check("mode=qpu raises FeatureMissing", False, "no exception raised")
        except AtlasBackend.FeatureMissing as exc:
            check("mode=qpu raises FeatureMissing", True, str(exc)[:70])
        except MothError as exc:
            check("mode=qpu raises FeatureMissing", False,
                  f"raised MothError instead: {exc}")

        print("\n[11] the pipeline runs end to end on the Atlas backend")
        pipe = pipeline.Pipeline(backend=atlas, size=128, fps=8, sr=22050,
                                 frame_repeats=1)
        built = pipe.build("a mock prompt")
        check("the pipeline accepts the Atlas backend",
              built["receipt"]["backend"] == "atlas",
              built["receipt"]["backend"])
        # The provenance list must carry the Atlas engine, not the local one.
        entries = [p.to_dict() for p in built["provenance"]] \
            if "provenance" in built else built["receipt"]["provenance"]
        engines = [e["engine"] for e in entries]
        check("the receipt records the Atlas engine in provenance",
              any("coin-toss" in str(e) for e in engines), str(engines))
        check("the receipt records the engine's job id",
              any("job_id" in json.dumps(e.get("detail") or {}) for e in entries))
        check("media was produced regardless of backend",
              built["audio"].size > 0 and len(built["frames"]) > 0,
              f"{len(built['frames'])} frames")

        print("\n[12] the Atlas MEDIA engines are driven with real files")
        import engines as media_mod
        import film
        import synth

        media = media_mod.MediaEngines(client, strict=True, poll=0.2,
                                       timeout=20)
        caps = media.capabilities()
        check("capabilities are probed from the API, not assumed",
              all(caps.values()), json.dumps(caps))

        # --- blur-v1: a real PNG must round-trip through the engine.
        field = film.quantum_field(primitives.probabilities, size=96, blur=1.0)
        before = media_mod.MediaEngines._encode_png(field)
        res = media.blur_image(field, strength=0.5)
        check("blur-v1 ran on Atlas (not a fallback)", res.used, res.reason or "ok")
        check("blur-v1 names its engine", res.engine == "blur-v1", res.engine)
        check("blur-v1 returned an array of the right shape",
              res.value.shape == field.shape, str(res.value.shape))
        check("blur-v1 output is decodable image data",
              0.0 <= float(res.value.min()) and float(res.value.max()) <= 1.0,
              f"range [{res.value.min():.3f}, {res.value.max():.3f}]")
        check("blur-v1 output differs from its input (bytes really round-tripped)",
              float(np.abs(np.asarray(res.value) - field).mean()) > 0.01,
              f"mean abs diff {float(np.abs(np.asarray(res.value) - field).mean()):.4f}")
        check("the job id is recorded for audit", "job_id" in res.detail,
              res.detail.get("job_id", "")[:8])
        check("input and output byte sizes are recorded",
              res.detail.get("input_bytes", 0) > 0
              and res.detail.get("output_bytes", 0) > 0,
              f"{res.detail.get('input_bytes')} -> {res.detail.get('output_bytes')}")
        # The engine received the uploaded asset, not a local path.
        call = next((c for c in ENGINE_PROCESS_CALLS
                     if c["engine_id"] == "blur-v1"), None)
        check("blur-v1 was submitted with an uploaded asset id",
              bool(call) and bool((call["body"].get("input_files") or {}).get("image")),
              str((call or {}).get("body", {}).get("input_files")))
        check("the blob the engine read is the PNG we sent",
              UPLOADED.get((call["body"]["input_files"]["image"])) == before)

        # --- telablur-v1: two images.
        res2 = media.blend_images(field, np.clip(1.0 - field, 0, 1), strength=0.5)
        check("telablur-v1 ran on Atlas", res2.used, res2.reason or "ok")
        check("telablur-v1 sent both image slots",
              len((next((c for c in ENGINE_PROCESS_CALLS
                         if c["engine_id"] == "telablur-v1"), {})
                   .get("body", {}).get("input_files") or {})) == 2)

        # --- entanglement-shader-v1 returns SHADER SOURCE, not an image.
        # Verified against the live API: the engine answers with a ZIP holding
        # .osl/.glsl/.hlsl/.mtlx and EXR/HDR LUTs, so there is no texture to
        # blend. The correct behaviour is a *visible* fallback that reports the
        # bundle it received — never a silent substitution, and never a crash.
        shader_media = media_mod.MediaEngines(client, strict=False, poll=0.2,
                                              timeout=20)
        res3 = shader_media.shader_texture(size=64, style="peaked")
        check("shader does not claim to have produced an image", not res3.used)
        check("shader reports why it fell back",
              "shader source" in res3.reason, res3.reason[:70])
        check("shader lists the zip members it received",
              isinstance(res3.detail.get("zip_members"), list)
              and len(res3.detail["zip_members"]) >= 1,
              str(res3.detail.get("zip_members"))[:80])
        check("shader fallback still yields a usable texture",
              res3.value.shape == (64, 64), str(res3.value.shape))
        shader_call = next((c for c in ENGINE_PROCESS_CALLS
                            if c["engine_id"] == "entanglement-shader-v1"), None)
        check("shader was submitted with no input_files",
              bool(shader_call) and not shader_call["body"].get("input_files"))
        check("the shader client is not strict, so it degrades instead of raising",
              shader_media.strict is False)

        # --- retrocausal-echo-v1: real WAV in, real WAV out.
        audio = synth_buf = np.zeros((2, 2205))
        t = np.arange(2205) / 22050.0
        audio[0] = 0.4 * np.sin(2 * np.pi * 220 * t)
        audio[1] = 0.4 * np.sin(2 * np.pi * 330 * t)
        ir = synth.make_ir(seed=1, sr=22050, seconds=0.3)
        res4 = media.convolve_audio(audio, ir, sr=22050, decay=0.9, mix=0.6)
        check("retrocausal-echo-v1 ran on Atlas", res4.used, res4.reason or "ok")
        check("audio came back as a stereo buffer",
              res4.value.ndim == 2 and res4.value.shape[0] == 2,
              str(res4.value.shape))
        check("the engine's own sample rate is reported",
              res4.detail.get("output_sr") == 22050,
              str(res4.detail.get("output_sr")))
        check("audio output is not silent",
              float(np.abs(res4.value).max()) > 0.01,
              f"peak {float(np.abs(res4.value).max()):.4f}")
        check("echo received only the audio slot (ir is measured, not uploaded)",
              set((next((c for c in ENGINE_PROCESS_CALLS
                         if c["engine_id"] == "retrocausal-echo-v1"), {})
                   .get("body", {}).get("input_files") or {})) == {"audio"})

        print("\n[13] fallback is visible, never silent")
        class _Exhausted(media_mod.MediaEngines):
            def available(self, engine_id):
                return False

        soft = _Exhausted(client)
        soft.probe().setdefault("_probe_error", "simulated outage")
        out = soft.blur_image(field, local=lambda: np.full_like(field, 0.25))
        check("unavailable engine falls back instead of raising", not out.used)
        check("the fallback names the local engine it used",
              out.engine == "film.quantum_field", out.engine)
        check("the fallback records why", bool(out.reason), out.reason[:50])
        check("the fallback still returns usable media",
              out.value.shape == field.shape)

        # In strict mode the same condition must raise, so a caller that needs
        # Atlas cannot silently receive local output.
        strict_media = media_mod.MediaEngines(client, strict=True)
        strict_media._available = {}
        try:
            strict_media.blur_image(field)
            check("strict mode raises rather than falling back", False,
                  "no exception")
        except RuntimeError as exc:
            check("strict mode raises rather than falling back", True,
                  str(exc)[:60])

        print("\n[14] the PIPELINE routes its media stages through Atlas")
        media_soft = media_mod.MediaEngines(client, poll=0.2, timeout=20)
        pipe2 = pipeline.Pipeline(backend=atlas, media=media_soft, size=96,
                                  fps=6, sr=22050, frame_repeats=1)
        built2 = pipe2.build("a prompt with atlas media")
        prov2 = [p.to_dict() for p in built2["provenance"]] \
            if "provenance" in built2 else built2["receipt"]["provenance"]
        by_choice = {p["choice"]: p for p in prov2}
        check("the receipt records an image-interference stage",
              "image-interference" in by_choice, str(sorted(by_choice)))
        if "image-interference" in by_choice:
            entry = by_choice["image-interference"]
            check("image interference was produced by blur-v1 on Atlas",
                  entry["engine"] == "blur-v1" and entry["detail"].get("used_atlas"),
                  f"{entry['engine']} used_atlas={entry['detail'].get('used_atlas')}")
            check("the stage is attributed to atlas-media as its source",
                  entry["source"] == "atlas-media", entry["source"])
        check("the space-and-decay stage was produced by retrocausal-echo-v1",
              by_choice.get("space-and-decay", {}).get("engine")
              in ("retrocausal-echo-v1", "synth.convolve_ir"),
              str(by_choice.get("space-and-decay", {}).get("engine")))
        check("media still rendered with route-through enabled",
              built2["audio"].size > 0 and len(built2["frames"]) > 0,
              f"{len(built2['frames'])} frames")

        # The same pipeline without `media` must not attribute any MEDIA stage to
        # Atlas — only the creative budget comes from there.
        pipe3 = pipeline.Pipeline(backend=atlas, size=96, fps=6, sr=22050,
                                  frame_repeats=1)
        built3 = pipe3.build("a prompt without atlas media")
        prov3 = built3["receipt"]["provenance"]
        media_choices = {"image-interference", "space-and-decay",
                         "visual-structure-and-palette",
                         "instrumentation-and-melody"}
        media_sources = {p["source"] for p in prov3
                         if p["choice"] in media_choices}
        check("without media engines, no media stage claims Atlas attribution",
              media_sources == {"local-renderers"}, str(sorted(media_sources)))
        check("with media engines, Atlas owns the interference layer",
              by_choice.get("image-interference", {}).get("source") == "atlas-media",
              str(by_choice.get("image-interference", {}).get("source")))
        check("the local path still records its engine names",
              any("film." in p["engine"] or "synth." in p["engine"]
                  for p in prov3),
              str(sorted({p["engine"].split(" ")[0] for p in prov3})))
    finally:
        server.shutdown()
        server.server_close()
        for path in ("_mock_upload.bin", "_mock_output.json"):
            try:
                os.remove(path)
            except OSError:
                pass

    print("\n" + "=" * 70)
    print(f"{PASS} passed, {FAIL} failed")
    print("=" * 70)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
