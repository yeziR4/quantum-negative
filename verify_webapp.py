"""Verify the web app end to end.

Starts the real server (offline backend, so no credentials are needed), then
exercises every endpoint over HTTP the way a browser would: health, index, a
real generation job, polling to completion, artifact download, and path-traversal
rejection.

    python -B verify_webapp.py
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

PASS, FAIL = 0, 0
BASE = ""


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  PASS  {name}" + (f"  ({detail})" if detail else ""))
    else:
        FAIL += 1
        print(f"  FAIL  {name}" + (f"  ({detail})" if detail else ""))


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def get(path: str, timeout: float = 30.0):
    """GET returning (status, body, headers). A non-2xx status is returned
    rather than raised, so the tests can assert on error responses."""
    req = urllib.request.Request(BASE + path, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers or {})


def post(path: str, payload: dict, timeout: float = 30.0):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(BASE + path, data=data, method="POST",
                                headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def wait_ready(port: int, timeout: float = 40.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz",
                                        timeout=2) as r:
                if r.status == 200:
                    return True
        except OSError:
            time.sleep(0.3)
    return False


def main() -> int:
    global BASE
    port = free_port()
    BASE = f"http://127.0.0.1:{port}"

    print("=" * 68)
    print("web app verification")
    print("=" * 68)

    shutil.rmtree("web_output", ignore_errors=True)
    log = open("webapp-test.log", "w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-B", "webapp.py", "--offline", "--port", str(port)],
        stdout=log, stderr=subprocess.STDOUT, cwd=os.getcwd())

    try:
        print("\n[1] server startup")
        ready = wait_ready(port)
        check("server becomes ready", ready, f"port {port}")
        if not ready:
            log.close()
            print(open("webapp-test.log", encoding="utf-8").read()[-800:])
            return 1

        print("\n[2] static and health endpoints")
        status, body, headers = get("/")
        check("GET / serves HTML", status == 200 and b"<html" in body.lower(),
              f"{len(body)} bytes")
        check("index declares the app title", b"QUANTUM NEGATIVE" in body)
        check("index has a generate control", b"id=\"go\"" in body)
        check("index is properly typed",
              "text/html" in headers.get("Content-Type", ""))

        status, body, _ = get("/api/health")
        health = json.loads(body)
        check("GET /api/health reports a backend", status == 200 and "backend" in health,
              health.get("backend", ""))
        check("offline mode is reported honestly",
              health.get("atlas_available") is False,
              health.get("reason", ""))
        status, _, _ = get("/healthz")
        check("GET /healthz is 200", status == 200)

        print("\n[3] input validation")
        status, payload = post("/api/generate", {})
        check("empty prompt is rejected", status == 400, payload.get("error", ""))
        status, payload = post("/api/generate", {"prompt": "x" * 500})
        check("over-long prompt is rejected", status == 400, payload.get("error", ""))
        status, _, _ = get("/api/job/00000000-0000-0000-0000-000000000000")
        check("unknown job is 404", status == 404)
        # The request is issued raw so the client cannot normalise the path away.
        status, _, _ = get("/files/../webapp.py")
        check("path traversal is refused", status in (400, 404), f"status {status}")

        print("\n[4] a real generation job")
        status, payload = post("/api/generate",
                               {"prompt": "a lighthouse counting its own rotations",
                                "size": 192, "fps": 8})
        check("POST /api/generate accepted", status == 202 and "job_id" in payload,
              payload.get("job_id", "")[:8])
        job_id = payload["job_id"]

        deadline = time.time() + 300
        job = {}
        seen_stages = set()
        while time.time() < deadline:
            _, body, _ = get(f"/api/job/{job_id}")
            job = json.loads(body)
            seen_stages.add(job.get("stage"))
            if job.get("state") in ("done", "failed"):
                break
            time.sleep(0.5)

        check("job reached a terminal state", job.get("state") in ("done", "failed"),
              job.get("state"))
        check("job succeeded", job.get("state") == "done", job.get("error") or "ok")
        check("progress reflects the pipeline stages", len(seen_stages) >= 2,
              ", ".join(sorted(s for s in seen_stages if s)))

        if job.get("state") != "done":
            log.close()
            print(open("webapp-test.log", encoding="utf-8").read()[-1500:])
            return 1

        print("\n[5] artifacts are served and playable")
        arts = job.get("artifacts") or {}
        check("film, score, poster and receipt are exposed",
              {"video", "audio", "poster", "receipt"} <= set(arts),
              ", ".join(sorted(arts)))

        for key, ctype in (("video", "video/mp4"), ("audio", "audio/"),
                           ("poster", "image/png")):
            status, blob, headers = get(arts[key])
            check(f"{key} downloads", status == 200 and len(blob) > 1000,
                  f"{len(blob)/1024:.1f} KiB, {headers.get('Content-Type')}")
            check(f"{key} content-type is {ctype}",
                  ctype in headers.get("Content-Type", ""),
                  headers.get("Content-Type", ""))

        status, blob, headers = get(arts["receipt"])
        check("receipt is served as a download",
              "attachment" in headers.get("Content-Disposition", ""))
        served_receipt = json.loads(blob)

        # The MP4 must actually be a valid MP4 container.
        status, head, _ = get(arts["video"])
        check("film has an MP4/ISO-BMFF header",
              head[4:8] == b"ftyp", head[4:12].decode("ascii", "replace"))

        print("\n[6] the page's receipt matches the pipeline's own gates")
        cp = served_receipt["creative_primitives"]
        check("receipt reports the circuit", cp["gates"] > 0,
              f"{cp['n_qubits']}q, {cp['gates']} gates")
        check("entropy is unsaturated (quantum work is observable)",
              cp["entropy_bits"] < cp["n_qubits"], 
              f"{cp['entropy_bits']:.4f} < {cp['n_qubits']}")
        check("entanglement is present", cp["mutual_information_bits"] > 0.01,
              f"{cp['mutual_information_bits']:.4f} bits")
        check("every decision names its engine",
              all(p.get("engine") for p in served_receipt["provenance"]),
              f"{len(served_receipt['provenance'])} entries")
        check("backend used is recorded",
              bool(served_receipt.get("backend")), served_receipt.get("backend"))

        print("\n[7] gallery and reproducibility")
        _, body, _ = get("/api/gallery")
        gallery = json.loads(body).get("items") or []
        check("gallery lists the finished piece", len(gallery) >= 1,
              f"{len(gallery)} item(s)")
        check("gallery item points at real artifacts",
              bool(gallery[0].get("poster")) and bool(gallery[0].get("video")))
        check("gallery preserves the prompt",
              "lighthouse" in gallery[0].get("prompt", ""))

        # Same prompt again must produce the same film bytes.
        _, payload2 = post("/api/generate",
                           {"prompt": "a lighthouse counting its own rotations",
                            "size": 192, "fps": 8})
        job2 = payload2["job_id"]
        deadline = time.time() + 300
        while time.time() < deadline:
            _, body, _ = get(f"/api/job/{job2}")
            state = json.loads(body).get("state")
            if state in ("done", "failed"):
                break
            time.sleep(0.5)
        _, body, _ = get(f"/api/job/{job2}")
        job2_data = json.loads(body)
        check("repeat job succeeded", job2_data.get("state") == "done",
              job2_data.get("error") or "ok")
        if job2_data.get("state") == "done":
            _, b1, _ = get(arts["video"])
            _, b2, _ = get(job2_data["artifacts"]["video"])
            check("same prompt yields byte-identical film",
                  b1 == b2, f"{len(b1)} vs {len(b2)} bytes")

        print("\n[8] the game page (challenge 05)")
        status, body, headers = get("/game")
        check("GET /game serves HTML", status == 200 and b"<html" in body.lower(),
              f"{len(body)} bytes")
        check("game page names itself", b"DEVELOP THE NEGATIVE" in body)
        check("game page exposes read controls",
              b"Read 0" in body and b"Read 1" in body)
        check("game page is properly typed",
              "text/html" in headers.get("Content-Type", ""))

        status, payload = post("/api/game/start", {})
        check("POST /api/game/start begins a session", status == 201
              and "game_id" in payload, payload.get("game_id", "")[:8])
        check("first state includes a question", "question" in payload,
              f"qubit {payload.get('question', {}).get('qubit')}")
        check("first state includes the plate as a PNG",
              str(payload.get("image", "")).startswith("data:image/png"))
        check("circuit metrics are exposed",
              payload.get("entropy_bits") is not None
              and payload.get("max_entropy_bits") == 8,
              f"entropy {payload.get('entropy_bits')}/8")

        game_id = payload["game_id"]
        status, _, _ = get(f"/api/game/{game_id}")
        check("GET /api/game/<id> returns the session", status == 200)
        status, payload = post(f"/api/game/{game_id}", {"choice": 7})
        check("an invalid read is rejected", status == 400,
              payload.get("error", ""))
        status, _, _ = get("/api/game/00000000-0000-0000-0000-000000000000")
        check("unknown game session is 404", status == 404)

        # Play a full session, always answering by the Born-rule marginal the
        # server itself reported — a perfect player.
        state = payload if "question" in payload else None
        _, body, _ = get(f"/api/game/{game_id}")
        state = json.loads(body)
        rounds = 0
        while not state.get("finished") and rounds < 20:
            q = state["question"]
            # Derive the answer from the reported marginal, not from a secret.
            choice = 1 if q["marginal"] >= 0.5 else 0
            status, state = post(f"/api/game/{game_id}", {"choice": choice})
            assert status == 200, state
            rounds += 1
        check("a full session plays to completion over HTTP",
              state.get("finished") is True, f"{rounds} rounds")
        check("every read was scored correct", state.get("correct") == rounds,
              f"{state.get('correct')}/{rounds}")
        check("the plate is revealed at the end",
              str(state.get("final_image", "")).startswith("data:image/png"))
        check("a rank is awarded", bool(state.get("rank")), state.get("rank", ""))
        check("history records each round", len(state.get("history") or []) == rounds)
        check("final score is positive", state.get("score", 0) > 0,
              f"{state.get('score')} points")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()

    print("\n" + "=" * 68)
    print(f"{PASS} passed, {FAIL} failed")
    print("=" * 68)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
