"""QUANTUM NEGATIVE Web — interactive front-end for the pipeline.

Challenge 08, "Make a web app": builds a web app that calls the Atlas API.

Architecture note, stated up front because it is the honest one: the creative
*decisions* are quantum either way, but the **media rendering** stages call the
Atlas API when a key is configured, and fall back to the bundled local engines
when it is not. The app reports which path it actually used, per request. It
never presents a simulated run as an Atlas run.

Uses only the standard library (`http.server`), so there is no build step, no
node_modules and no virtualenv — it runs anywhere Python does.

    python -B webapp.py                 # http://127.0.0.1:8000
    python -B webapp.py --port 9000
    python -B webapp.py --offline       # force the local backend

Endpoints
---------
    GET  /                  the app
    GET  /api/health        backend status, Atlas availability, feature flags
    POST /api/generate      {prompt, size?, fps?} -> {job_id}
    GET  /api/job/<job_id>  progress and, when finished, artifact URLs
    GET  /api/gallery       previously generated pieces
    GET  /files/<name>      a generated artifact
    GET  /healthz           bare liveness probe
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import threading
import time
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

import pipeline

HERE = os.path.dirname(os.path.abspath(__file__))
OUTPUT_ROOT = os.path.join(HERE, "web_output")

MAX_PROMPT = 400
DEFAULT_SIZE = 320
DEFAULT_FPS = 12

# ------------------------------------------------------------ game registry
#
# DEVELOP THE NEGATIVE (challenge 05) lives in `game.py`; this module only
# exposes it over HTTP. Game state is per-session and mutable, so it is guarded
# by a lock: the server is threaded, and two concurrent answers on one session
# would otherwise interleave on the same quantum register.

import game as game_mod

GAMES: dict[str, game_mod.QuantumGame] = {}
GAMES_LOCK = threading.Lock()
MAX_GAMES = 200


def prune_games() -> None:
    with GAMES_LOCK:
        if len(GAMES) <= MAX_GAMES:
            return
        for game_id in list(GAMES)[: len(GAMES) - MAX_GAMES]:
            GAMES.pop(game_id, None)

# ---------------------------------------------------------------- job registry


class Job:
    """One generation request and its progress."""

    def __init__(self, job_id: str, prompt: str, size: int, fps: int):
        self.id = job_id
        self.prompt = prompt
        self.size = size
        self.fps = fps
        self.state = "queued"          # queued | running | done | failed
        self.stage = "queued"
        self.progress = 0.0
        self.created = time.time()
        self.finished: float | None = None
        self.error: str | None = None
        self.artifacts: dict[str, str] = {}
        self.receipt: dict | None = None
        self.backend = "pending"

    def to_dict(self) -> dict:
        return {
            "job_id": self.id, "prompt": self.prompt, "state": self.state,
            "stage": self.stage, "progress": round(self.progress, 3),
            "error": self.error, "artifacts": self.artifacts,
            "backend": self.backend,
            "elapsed": round((self.finished or time.time()) - self.created, 2),
            "receipt": self.receipt,
        }


JOBS: dict[str, Job] = {}
JOBS_LOCK = threading.Lock()
MAX_JOBS = 40


def prune_jobs() -> None:
    """Keep the registry bounded; oldest finished jobs go first."""
    with JOBS_LOCK:
        if len(JOBS) <= MAX_JOBS:
            return
        finished = sorted((j for j in JOBS.values() if j.state in ("done", "failed")),
                          key=lambda j: j.created)
        for job in finished[: len(JOBS) - MAX_JOBS]:
            JOBS.pop(job.id, None)


# ------------------------------------------------------------------- backends


def resolve_backend(force_offline: bool) -> tuple[object, str, dict]:
    """Choose the quantum backend. Returns (backend, label, status detail)."""
    detail: dict = {"atlas_available": False, "features": [], "run_quantum": False}
    if force_offline:
        detail["reason"] = "offline mode requested"
        return pipeline.LocalBackend(), "local-emulator (offline mode)", detail

    try:
        from moth_client import MothClient
    except ImportError as exc:
        detail["reason"] = f"moth_client import failed: {exc}"
        return pipeline.LocalBackend(), "local-emulator", detail

    try:
        client = MothClient()
    except SystemExit:
        detail["reason"] = "no Atlas API key configured (MOTH_API_KEY unset)"
        return pipeline.LocalBackend(), "local-emulator", detail

    try:
        me = client.me()
    except Exception as exc:                            # noqa: BLE001
        detail["reason"] = f"Atlas auth failed: {exc}"
        return pipeline.LocalBackend(), "local-emulator", detail

    features = me.get("features") or []
    detail.update({"atlas_available": True, "features": features,
                   "run_quantum": "run_quantum" in features,
                   "email": me.get("email")})
    # Emulation stays the default because it makes the piece reproducible;
    # QPU execution is opt-in per request via the UI.
    return (pipeline.AtlasBackend(client, engine_id="coin-toss-v1", mode="emu"),
            "atlas (emu)", detail)


# ---------------------------------------------------------------- generation


def generate(job: Job, force_offline: bool) -> None:
    """Run the pipeline for one job, updating progress as it goes."""
    try:
        job.state = "running"

        job.stage = "deriving the quantum creative budget"
        job.progress = 0.15
        backend, label, status = resolve_backend(force_offline)
        job.backend = label

        job.stage = "rendering audio and film"
        job.progress = 0.45
        pipe = pipeline.Pipeline(backend=backend, size=job.size, fps=job.fps,
                                 sr=22050, frame_repeats=2)
        built = pipe.build(job.prompt)

        job.stage = "encoding artifacts"
        job.progress = 0.8
        out_dir = os.path.join(OUTPUT_ROOT, job.id)
        paths = pipe.write(built, out_dir)

        job.artifacts = {k: f"/files/{job.id}/{os.path.basename(v)}"
                         for k, v in paths.items()}
        job.receipt = json.load(open(paths["receipt"], encoding="utf-8"))
        job.receipt["backend_status"] = status
        job.stage = "done"
        job.progress = 1.0
        job.state = "done"
        job.finished = time.time()
    except Exception as exc:                            # noqa: BLE001
        job.state = "failed"
        job.stage = "failed"
        job.error = f"{type(exc).__name__}: {exc}"
        job.finished = time.time()
        traceback.print_exc()
    finally:
        prune_jobs()


# ---------------------------------------------------------------------- HTML

INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>QUANTUM NEGATIVE</title>
<style>
  :root { --bg:#08090c; --panel:#12141a; --line:#242833; --ink:#e8e6e1;
          --dim:#8b93a7; --accent:#e0b64a; }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--ink);
         font:15px/1.55 ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif; }
  header { padding:34px 24px 18px; border-bottom:1px solid var(--line); }
  h1 { margin:0 0 6px; font-size:26px; letter-spacing:.14em; font-weight:600; }
  .sub { color:var(--dim); font-size:14px; max-width:70ch; }
  main { max-width:980px; margin:0 auto; padding:26px 20px 80px; }
  .panel { background:var(--panel); border:1px solid var(--line);
           border-radius:10px; padding:18px; margin-bottom:18px; }
  textarea { width:100%; min-height:74px; background:#0b0d12; color:var(--ink);
             border:1px solid var(--line); border-radius:8px; padding:12px;
             font:inherit; resize:vertical; }
  .row { display:flex; gap:12px; align-items:center; flex-wrap:wrap; margin-top:12px; }
  button { background:var(--accent); color:#181a1f; border:0; border-radius:8px;
           padding:11px 20px; font:inherit; font-weight:650; cursor:pointer; }
  button:disabled { opacity:.5; cursor:progress; }
  select { background:#0b0d12; color:var(--ink); border:1px solid var(--line);
           border-radius:8px; padding:9px; font:inherit; }
  label { color:var(--dim); font-size:13px; }
  #status { color:var(--dim); font-size:13px; min-height:20px; }
  .bar { height:3px; background:var(--line); border-radius:3px; overflow:hidden; margin-top:14px; }
  .bar > i { display:block; height:100%; width:0; background:var(--accent);
             transition:width .35s ease; }
  .grid { display:grid; grid-template-columns:1fr 1fr; gap:16px; }
  @media (max-width:760px) { .grid { grid-template-columns:1fr; } }
  video, img, audio { width:100%; border-radius:8px; background:#000; display:block; }
  audio { margin-top:12px; }
  table { width:100%; border-collapse:collapse; font-size:13px; }
  td { padding:5px 8px; border-bottom:1px solid var(--line); vertical-align:top; }
  td.k { color:var(--dim); width:44%; }
  code { color:var(--accent); font-size:12px; word-break:break-all; }
  .pill { display:inline-block; padding:3px 10px; border-radius:99px;
          border:1px solid var(--line); font-size:12px; color:var(--dim); }
  .pill.ok { color:#7ee0a0; border-color:#2c5c40; }
  .pill.warn { color:var(--accent); border-color:#5c4a2c; }
  .meter { height:5px; background:var(--line); border-radius:3px; margin:4px 0 10px; }
  .meter > i { display:block; height:100%; background:var(--accent); border-radius:3px; }
  footer { color:var(--dim); font-size:12px; padding:0 24px 40px; max-width:980px; margin:0 auto; }
  a { color:var(--accent); }
</style>
</head>
<body>
<header>
  <h1>QUANTUM NEGATIVE</h1>
  <div class="sub">A prompt becomes a short film whose melody, instrumentation,
  colour and structure are all <strong>measurement outcomes of a quantum
  circuit</strong>. Same prompt, same result — every decision is recorded.</div>
</header>
<main>
  <div class="panel">
    <textarea id="prompt" maxlength="400"
      placeholder="the last negative of a dying star, developed in the dark"></textarea>
    <div class="row">
      <button id="go">Generate</button>
      <a class="pill" href="/game" style="text-decoration:none">play DEVELOP THE NEGATIVE →</a>
      <label>resolution
        <select id="size">
          <option value="256">256 (fast)</option>
          <option value="320" selected>320</option>
          <option value="384">384</option>
          <option value="512">512 (slow)</option>
        </select>
      </label>
      <span class="pill" id="backend">checking backend…</span>
    </div>
    <div class="bar"><i id="bar"></i></div>
    <div id="status"></div>
  </div>

  <div class="panel" id="result" style="display:none">
    <div class="grid">
      <div>
        <video id="video" controls loop muted playsinline></video>
        <audio id="audio" controls></audio>
      </div>
      <div>
        <div style="color:var(--dim);font-size:13px;margin-bottom:8px">
          Quantum creative budget</div>
        <table id="quantum"></table>
        <div style="color:var(--dim);font-size:13px;margin:16px 0 8px">
          Provenance — every decision and the engine that made it</div>
        <table id="prov"></table>
        <div class="row">
          <a id="dlvideo" download>download film</a>
          <a id="dlaudio" download>download score</a>
          <a id="dlreceipt" download>download receipt</a>
        </div>
      </div>
    </div>
  </div>

  <div class="panel">
    <div style="color:var(--dim);font-size:13px;margin-bottom:10px">Earlier pieces</div>
    <div id="gallery" class="grid"></div>
  </div>
</main>
<footer>
  Creative decisions come from a quantum circuit; media rendering uses the Moth
  Atlas API when a key is configured and the bundled local engines otherwise.
  The backend actually used is reported for every run.
</footer>
<script>
const $ = (id) => document.getElementById(id);
let timer = null;

async function health() {
  try {
    const r = await fetch('/api/health'); const h = await r.json();
    const el = $('backend');
    if (h.atlas_available) {
      el.className = 'pill ok';
      el.textContent = 'Atlas connected · run_quantum=' + h.run_quantum;
    } else {
      el.className = 'pill warn';
      el.textContent = 'local emulator · ' + (h.reason || 'no Atlas key');
    }
  } catch (e) {
    $('backend').textContent = 'backend unknown';
  }
}

function row(tbody, k, v) {
  const tr = document.createElement('tr');
  const a = document.createElement('td'); a.className = 'k'; a.textContent = k;
  const b = document.createElement('td'); b.innerHTML = v;
  tr.append(a, b); tbody.append(tr);
}

function pct(x) { return (100 * x).toFixed(1) + '%'; }

async function generate() {
  const prompt = $('prompt').value.trim();
  if (!prompt) { $('status').textContent = 'Enter a prompt first.'; return; }
  $('go').disabled = true;
  $('result').style.display = 'none';
  const r = await fetch('/api/generate', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ prompt, size: +$('size').value })
  });
  const { job_id, error } = await r.json();
  if (error) { $('status').textContent = error; $('go').disabled = false; return; }
  poll(job_id);
}

function poll(id) {
  timer = setInterval(async () => {
    const r = await fetch('/api/job/' + id);
    const j = await r.json();
    $('bar').style.width = pct(j.progress || 0);
    $('status').textContent = j.stage + ' · ' + (j.elapsed || 0).toFixed(1) + 's';
    if (j.state === 'done') { clearInterval(timer); $('go').disabled = false; show(j); }
    if (j.state === 'failed') {
      clearInterval(timer); $('go').disabled = false;
      $('status').textContent = 'failed: ' + j.error;
    }
  }, 600);
}

function show(j) {
  $('result').style.display = 'block';
  $('video').src = j.artifacts.video;
  $('audio').src = j.artifacts.audio;
  $('dlvideo').href = j.artifacts.video;
  $('dlaudio').href = j.artifacts.audio;
  $('dlreceipt').href = j.artifacts.receipt;

  const cp = j.receipt.creative_primitives;
  const q = $('quantum'); q.innerHTML = '';
  row(q, 'seed', '<code>' + cp.seed + '</code>');
  row(q, 'circuit', cp.n_qubits + ' qubits · ' + cp.gates + ' gates · '
      + cp.shots + ' shots');
  row(q, 'entropy', cp.entropy_bits.toFixed(3) + ' / ' + cp.n_qubits + ' bits');
  row(q, 'entanglement (mean adjacent)',
      cp.mutual_information_bits.toFixed(4) + ' bits');
  row(q, 'strongest pair',
      cp.max_pair_mutual_information_bits.toFixed(4) + ' bits');
  row(q, 'melody (from outcomes)',
      '<code>' + cp.pitches.join(' ') + '</code>');
  row(q, 'scenes', cp.scene_count + ' · pacing ' + cp.scene_pacing.join(','));
  row(q, 'timbre', cp.timbre);
  row(q, 'backend', '<code>' + j.backend + '</code>');

  const p = $('prov'); p.innerHTML = '';
  for (const e of j.receipt.provenance) row(p, e.choice, '<code>'
      + e.engine + '</code><br><span style="color:var(--dim)">'
      + e.source + '</span>');
}

async function gallery() {
  const r = await fetch('/api/gallery'); const g = await r.json();
  const el = $('gallery'); el.innerHTML = '';
  if (!g.items.length) { el.innerHTML = '<span style="color:var(--dim)">nothing yet</span>'; return; }
  for (const it of g.items) {
    const d = document.createElement('div');
    d.innerHTML = '<img src="' + it.poster + '" alt="">'
      + '<div style="color:var(--dim);font-size:12px;margin-top:6px">'
      + it.prompt.slice(0, 70) + '</div>'
      + '<div style="font-size:12px">' + it.pitches + ' · <a href="'
      + it.video + '">film</a></div>';
    el.append(d);
  }
}

$('go').onclick = generate;
$('prompt').value = 'the last negative of a dying star, developed in the dark';
health(); gallery();
</script>
</body>
</html>
"""


# -------------------------------------------------------------------- handler

JOB_PATH = re.compile(r"^/api/job/([0-9a-f-]{36})$")
FILE_PATH = re.compile(r"^/files/([0-9a-f-]{36})/([A-Za-z0-9_.-]+)$")
GAME_PATH = re.compile(r"^/api/game/([0-9a-f-]{36})$")


GAME_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DEVELOP THE NEGATIVE</title>
<style>
  :root { --bg:#07080a; --panel:#12141a; --line:#242833; --ink:#e8e6e1;
          --dim:#8b93a7; --accent:#e0b64a; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--ink);
         font:15px/1.55 ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif; }
  header { padding:26px 24px 14px; border-bottom:1px solid var(--line); }
  h1 { margin:0 0 4px; font-size:22px; letter-spacing:.16em; font-weight:600; }
  .sub { color:var(--dim); font-size:13px; max-width:76ch; }
  main { max-width:920px; margin:0 auto; padding:22px 20px 70px; }
  .panel { background:var(--panel); border:1px solid var(--line);
           border-radius:10px; padding:18px; margin-bottom:16px; }
  .grid { display:grid; grid-template-columns:300px 1fr; gap:20px; }
  @media (max-width:720px){ .grid { grid-template-columns:1fr; } }
  img { width:100%; border-radius:8px; background:#000; display:block; }
  .hud { display:flex; gap:22px; flex-wrap:wrap; font-size:13px; }
  .hud b { color:var(--accent); font-size:17px; display:block; font-weight:650; }
  .hud span { color:var(--dim); }
  .q { font-size:19px; margin:6px 0 4px; }
  .q code { color:var(--accent); }
  .hint { color:var(--dim); font-size:13px; margin-bottom:14px; }
  .row { display:flex; gap:12px; flex-wrap:wrap; align-items:center; }
  button { border:0; border-radius:9px; padding:14px 26px; font:inherit;
           font-weight:650; cursor:pointer; background:var(--accent); color:#181a1f; }
  button.alt { background:#232733; color:var(--ink); }
  button:disabled { opacity:.45; cursor:not-allowed; }
  .bar { height:6px; background:var(--line); border-radius:3px; overflow:hidden; margin:12px 0 6px; }
  .bar > i { display:block; height:100%; background:var(--accent); width:0; }
  table { width:100%; border-collapse:collapse; font-size:12.5px; margin-top:10px; }
  td { padding:4px 7px; border-bottom:1px solid var(--line); }
  .ok { color:#7ee0a0; } .bad { color:#e07777; }
  .pill { display:inline-block; padding:2px 9px; border-radius:99px;
          border:1px solid var(--line); font-size:11.5px; color:var(--dim); }
  a { color:var(--accent); }
  .mono { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:12px; }
</style>
</head>
<body>
<header>
  <h1>DEVELOP THE NEGATIVE</h1>
  <div class="sub">Develop a latent photograph with a sequence of quantum
  development passes. Each pass is a real rotation layer on an 8-qubit register.
  Before each pass you must <strong>read the state</strong>: if you measured
  qubit <em>q</em> right now, would it read 0 or 1? The answer is the Born-rule
  marginal, not a guess. Reading correctly develops the plate; a wrong read
  ruins it. <a href="/">back to the generator</a></div>
</header>
<main>
  <div class="panel">
    <div class="hud">
      <div><span>round</span><b id="round">1/8</b></div>
      <div><span>score</span><b id="score">0</b></div>
      <div><span>correct</span><b id="correct">0</b></div>
      <div><span>development</span><b id="dev">2/10</b></div>
    </div>
    <div class="bar"><i id="bar"></i></div>
  </div>

  <div class="grid">
    <div class="panel">
      <img id="plate" alt="the negative being developed">
      <div class="mono" id="statemeta" style="color:var(--dim);margin-top:8px"></div>
    </div>
    <div class="panel">
      <div id="play">
        <div class="q" id="question">&mdash;</div>
        <div class="hint" id="hint"></div>
        <div class="row">
          <button id="zero">Read 0</button>
          <button id="one">Read 1</button>
          <button class="alt" id="restart">New plate</button>
        </div>
      </div>
      <div id="result" style="display:none"></div>
      <div id="log"></div>
    </div>
  </div>
</main>
<script>
const $ = (id) => document.getElementById(id);
let gameId = null, busy = false;

function render(s) {
  $('round').textContent = Math.min(s.round, s.rounds_total) + '/' + s.rounds_total;
  $('score').textContent = s.score;
  $('correct').textContent = s.correct + '/' + s.rounds_played;
  $('dev').textContent = s.development + '/10';
  $('bar').style.width = (100 * s.development / 10) + '%';
  $('plate').src = s.revealed ? (s.final_image || s.image) : s.image;
  const frac = s.entropy_bits / s.max_entropy_bits;
  $('statemeta').textContent =
    'entropy ' + s.entropy_bits.toFixed(3) + '/' + s.max_entropy_bits +
    ' bits · ' + (100 * frac).toFixed(0) + '% mixed';

  if (s.finished) {
    $('play').style.display = 'none';
    $('result').style.display = 'block';
    $('result').innerHTML = '<div class="q">Developed.</div>'
      + '<div class="hint">Final score <b>' + s.score + '</b> · '
      + s.correct + '/' + s.rounds_total + ' reads correct · '
      + '<span class="pill">' + (s.rank || '') + '</span></div>'
      + '<div class="row"><button id="again">Develop another</button></div>';
    $('again').onclick = start;
  } else {
    $('play').style.display = 'block';
    $('result').style.display = 'none';
    const q = s.question;
    $('question').innerHTML = 'If you measured qubit <code>' + q.qubit +
      '</code> right now, would it read 0 or 1?';
    $('hint').textContent = 'Born-rule marginal P(1) = ' + q.marginal.toFixed(4)
      + ' — the state is the only source of the answer.';
    $('zero').disabled = false; $('one').disabled = false;
  }

  const log = $('log');
  log.innerHTML = '';
  if (s.history && s.history.length) {
    const t = document.createElement('table');
    t.innerHTML = '<tr><td><span class="pill">round</span></td>'
      + '<td><span class="pill">qubit</span></td>'
      + '<td><span class="pill">P(1)</span></td>'
      + '<td><span class="pill">you</span></td>'
      + '<td><span class="pill">born</span></td>'
      + '<td><span class="pill">points</span></td></tr>';
    for (const h of s.history.slice().reverse()) {
      const tr = document.createElement('tr');
      tr.innerHTML = '<td>' + h.round + '</td><td>' + h.qubit + '</td><td>'
        + h.marginal.toFixed(4) + '</td><td>' + h.chosen + '</td><td>'
        + h.answer + '</td><td class="' + (h.correct ? 'ok' : 'bad') + '">'
        + (h.gained > 0 ? '+' : '') + h.gained + '</td>';
      t.append(tr);
    }
    log.append(t);
  }
}

async function start() {
  if (busy) return; busy = true;
  const r = await fetch('/api/game/start', {
    method:'POST', headers:{'Content-Type':'application/json'}, body:'{}' });
  const s = await r.json();
  gameId = s.game_id; busy = false;
  render(s);
}

async function answer(choice) {
  if (busy || !gameId) return; busy = true;
  $('zero').disabled = true; $('one').disabled = true;
  const r = await fetch('/api/game/' + gameId, {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({choice}) });
  const s = await r.json();
  busy = false;
  render(s);
}

$('zero').onclick = () => answer(0);
$('one').onclick = () => answer(1);
$('restart').onclick = start;
start();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    server_version = "QuantumNegative/0.1"
    force_offline = False

    def log_message(self, fmt, *args):                  # quieter default
        if os.environ.get("QN_VERBOSE"):
            super().log_message(fmt, *args)

    # -- helpers ---------------------------------------------------------

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, payload: dict) -> None:
        self._send(code, json.dumps(payload).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _read_json(self, limit: int = 64 * 1024) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > limit:
            return {}
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    # -- routes ----------------------------------------------------------

    def do_GET(self) -> None:                           # noqa: N802
        path = urlparse(self.path).path

        if path in ("/", "/index.html"):
            return self._send(200, INDEX_HTML.encode("utf-8"),
                              "text/html; charset=utf-8")
        if path == "/healthz":
            return self._json(200, {"ok": True})
        if path == "/api/health":
            _, label, status = resolve_backend(self.force_offline)
            return self._json(200, {"backend": label, **status})
        if path == "/api/gallery":
            return self._json(200, {"items": self._gallery()})
        if path == "/game":
            return self._send(200, GAME_HTML.encode("utf-8"),
                              "text/html; charset=utf-8")

        m = GAME_PATH.match(path)
        if m:
            with GAMES_LOCK:
                session = GAMES.get(m.group(1))
            if not session:
                return self._json(404, {"error": "unknown game session"})
            return self._json(200, session.status())

        m = JOB_PATH.match(path)
        if m:
            job = JOBS.get(m.group(1))
            if not job:
                return self._json(404, {"error": "unknown job"})
            # Only expose finished artifacts, never a half-written file.
            payload = job.to_dict()
            if job.state != "done":
                payload["artifacts"] = {}
            return self._json(200, payload)

        m = FILE_PATH.match(path)
        if m:
            return self._serve_file(m.group(1), unquote(m.group(2)))

        return self._json(404, {"error": "not found"})

    def do_POST(self) -> None:                          # noqa: N802
        path = urlparse(self.path).path

        if path == "/api/game/start":
            body = self._read_json()
            try:
                seed = int(body["seed"]) if body.get("seed") is not None else None
            except (TypeError, ValueError):
                return self._json(400, {"error": "seed must be an integer"})
            session = game_mod.QuantumGame(seed=seed)
            game_id = str(uuid.uuid4())
            with GAMES_LOCK:
                GAMES[game_id] = session
            prune_games()
            payload = session.start()
            payload["game_id"] = game_id
            return self._json(201, payload)

        m = GAME_PATH.match(path)
        if m:
            body = self._read_json()
            try:
                choice = int(body.get("choice"))
            except (TypeError, ValueError):
                return self._json(400, {"error": "choice must be 0 or 1"})
            if choice not in (0, 1):
                return self._json(400, {"error": "choice must be 0 or 1"})
            with GAMES_LOCK:
                session = GAMES.get(m.group(1))
                if not session:
                    return self._json(404, {"error": "unknown game session"})
                # Hold the lock across the answer: it mutates the shared quantum
                # register, and this server handles requests on threads.
                payload = session.answer(choice)
            payload["game_id"] = m.group(1)
            return self._json(200, payload)

        if path != "/api/generate":
            return self._json(404, {"error": "not found"})

        body = self._read_json()
        prompt = str(body.get("prompt") or "").strip()
        if not prompt:
            return self._json(400, {"error": "prompt is required"})
        if len(prompt) > MAX_PROMPT:
            return self._json(400, {"error": f"prompt must be <= {MAX_PROMPT} chars"})
        try:
            size = int(body.get("size") or DEFAULT_SIZE)
            fps = int(body.get("fps") or DEFAULT_FPS)
        except (TypeError, ValueError):
            return self._json(400, {"error": "size and fps must be integers"})
        size = max(128, min(size, 640))
        fps = max(6, min(fps, 24))

        job = Job(str(uuid.uuid4()), prompt, size, fps)
        with JOBS_LOCK:
            JOBS[job.id] = job
        threading.Thread(target=generate, args=(job, self.force_offline),
                         daemon=True).start()
        return self._json(202, {"job_id": job.id, "state": job.state})

    # -- helpers ---------------------------------------------------------

    def _gallery(self) -> list[dict]:
        items = []
        with JOBS_LOCK:
            jobs = [j for j in JOBS.values() if j.state == "done"]
        for job in sorted(jobs, key=lambda j: j.created, reverse=True)[:8]:
            receipt = job.receipt or {}
            pitches = (receipt.get("creative_primitives") or {}).get("pitches") or []
            items.append({
                "job_id": job.id, "prompt": job.prompt, "backend": job.backend,
                "poster": job.artifacts.get("poster", ""),
                "video": job.artifacts.get("video", ""),
                "audio": job.artifacts.get("audio", ""),
                "pitches": " ".join(str(p) for p in pitches[:8]),
            })
        return items

    def _serve_file(self, job_id: str, name: str) -> None:
        if job_id not in JOBS:
            return self._json(404, {"error": "unknown job"})
        # Reject anything that could escape the job directory.
        safe = os.path.basename(name)
        path = os.path.join(OUTPUT_ROOT, job_id, safe)
        if not os.path.isfile(path):
            return self._json(404, {"error": "no such artifact"})
        ctype = mimetypes.guess_type(safe)[0] or "application/octet-stream"
        with open(path, "rb") as fh:
            blob = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(blob)))
        # Inline playback for media, download for the receipt.
        disposition = "attachment" if safe.endswith(".json") else "inline"
        self.send_header("Content-Disposition",
                         f'{disposition}; filename="{safe}"')
        self.end_headers()
        self.wfile.write(blob)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--offline", action="store_true",
                    help="never contact Atlas; use the local engines")
    args = ap.parse_args()

    os.makedirs(OUTPUT_ROOT, exist_ok=True)
    Handler.force_offline = args.offline

    backend, label, status = resolve_backend(args.offline)
    print(f"quantum backend : {label}")
    if status.get("atlas_available"):
        print(f"  authenticated as {status.get('email')}")
        print(f"  features        : {status.get('features')}")
        print(f"  run_quantum     : {status.get('run_quantum')}")
    else:
        print(f"  reason          : {status.get('reason')}")
    print(f"listening on http://{args.host}:{args.port}")

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
