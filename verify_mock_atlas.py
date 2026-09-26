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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

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
                "schema": "about:blank", "count": 2, "next_cursor": None,
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
                ],
            })

        if path.startswith("/api/v1/engines/"):
            engine_id = path.split("/")[4]
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

    def do_PATCH(self) -> None:                     # noqa: N802
        if not self._guard():
            return
        return self._send(200, {})


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
        check("GET /engines returns the engine list", ids ==
              ["coin-toss-v1", "tessa-image-v1"], str(ids))
        check("pagination terminates when next_cursor is absent", len(engines) == 2)
        schema = client.params_schema("coin-toss-v1")
        check("params_schema is reachable per engine", "props" in schema,
              str(sorted(schema.keys())))
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
