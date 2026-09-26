# Moth Hack 2026 — working notes

Context and plan for our Moth Hack submission. Source of truth for the API is
`../moth-api.json` (OpenAPI 3.1, `moth-api` v0.41.0); a human-readable dump of
every endpoint is in `api-notes.txt`.

## STATUS — verified as of round 9, **against the live API**

**The key works and the pipeline runs on real Atlas engines.** Account:
`yezirhasan@gmail.com`, role `player`. Six suites, **269 checks, all passing**.

| suite | checks | what it proves |
|---|---|---|
| `python -B test_qsim.py` | 44 | the simulator is physically correct |
| `python -B verify_pipeline.py --size 256` | 44 | the pipeline makes real, reproducible media |
| `python -B verify_notebook.py` | 24 | the notebook is valid, executed, evidence embedded |
| `python -B verify_webapp.py` | 52 | the app and the game work over real HTTP |
| `python -B verify_game.py` | 24 | the game is quantum and skill-based, not a coin flip |
| `python -B verify_mock_atlas.py` | 81 | the Atlas client and media engines drive real files |

### Live account facts (verified, not assumed)

- **`features: []`** — the account carries **no `run_quantum`**, so `mode="qpu"`
  (real quantum hardware) is **not available**. `AtlasBackend` raises
  `FeatureMissing` rather than silently emulating while claiming hardware. Every
  claim in the submission therefore stays on emulated/simulated execution, which
  is what it already says.
- **31 engines visible**, including six `test-*`/`demo-*` engines at **0 credits**.
  This mattered: the smoke test auto-selected the "cheapest no-input engine" and
  would have run a *test* engine, reporting success while proving nothing. It now
  skips `test-*`/`demo-*`, and selects on whether an input slot is *required*
  rather than on `input_type`.
- **Storage quota** 1 GiB upload / 10 GiB total; a full live render uses a few MB.

### The live API differs from the spec in ways that mattered

Testing against the real service found **six bugs no mock would have caught**,
because in each case my mock encoded my own wrong assumption:

1. **`entanglement-shader-v1` does not output an image.** It returns a ZIP of
   shader source (`.osl`, `.frag`, `.glsl`, `.hlsl`, `.mtlx`) plus EXR/HDR LUTs —
   graphics-authoring material, not a rendered frame. Every call would have
   crashed in `_decode_png`. Now handled honestly: the client reports the bundle
   it received and falls back to the local texture, and the mock was corrected to
   serve a real ZIP so the path is actually exercised.
2. **`retrocausal-echo-v1` returns THREE outputs** — `ir` (JSON), `result`
   (audio/wav) and `taps` (JSON). Taking `outputs[0]` yields a JSON impulse
   response where audio was expected. Selection is now by slot/content type.
3. **Its `ir` input requires `application/json`**, not a WAV. Uploading a WAV was
   rejected; the engine measures its own IR when none is supplied.
4. **The declared MIME type on the asset decides acceptance.** `blur-v1` requires
   `image/png`; uploading a PNG as `application/octet-stream` gives
   `422 input files do not match the engine's requirements`. Content type is now
   inferred from the filename.
5. **Engine schemas differ and unknown params are rejected.** `tamagotchi-v1`
   has no `mode`, so sending one gave `422 params do not match the engine
   schema`. Parameters are filtered against each engine's own `params_schema`.
6. **JSON engines nest their payload at `result.result.output`**, with
   `outputs: null`. Handling only `counts` silently discarded successful runs.

### Live results

Three Atlas engines genuinely produce layers of the delivered film:

| layer | engine | status |
|---|---|---|
| image interference | `blur-v1` | **live** — used as a 25% haze layer |
| image morph | `telablur-v1` | **live** |
| space and decay | `retrocausal-echo-v1` | **live** — audio |
| generative texture | `entanglement-shader-v1` | unavailable by design (bug 1) |

The image engines are mixed in at **low weight, deliberately**. Measured: their
output carries a mean horizontal gradient of ~6e-4, i.e. it is essentially
defocussed, with far less detail than the field it was given. Using it as the
primary structure flattened the frame to mud; using it as a texture layer over
the correlation field keeps the picture readable while still materially changing
the rendered pixels. Both facts are recorded in the code and in the receipt
(`applied_as`).

**One honesty bug found while wiring this:** media stages were labelled with the
quantum backend's name, so an Atlas-quantum/local-media run reported
`source: atlas`. Backend and renderer are now labelled separately
(`atlas-media` vs `local-renderers`), and a layer claims `atlas-media` only when
an engine actually ran.

| suite | checks | what it proves |
|---|---|---|
| `python -B test_qsim.py` | 44 | the simulator is physically correct |
| `python -B verify_pipeline.py --size 256` | 44 | the pipeline makes real, reproducible media |
| `python -B verify_notebook.py` | 24 | the notebook is valid, executed, evidence embedded |
| `python -B verify_webapp.py` | 52 | the app and the game work over real HTTP |
| `python -B verify_game.py` | 24 | the game is quantum and skill-based, not a coin flip |
| `python -B verify_mock_atlas.py` | 78 | the Atlas client *and media engines* drive real files |

### The live API is reachable, and the client is proven against it

Connectivity was re-checked this round: Python reaches `yukon.org`,
`hack.mothquantum.com`, `github.com` and the API. `GET /api/v1/me` on
`api.mothquantum.com` returns a proper RFC-9457 error body:

```json
{"$schema": "https://api.mothquantum.com/schemas/ErrorModel.json",
 "title": "Unauthorized", "status": 401, "detail": "authentication required"}
```

`MothClient` parses that exactly right — `status=401`,
`detail='authentication required'`, and no false gated-feature. **The whole
request path is therefore proven against the live service**; only a valid key is
missing.

Note for anyone else building here: PowerShell's `Invoke-WebRequest` fails against
every one of these hosts with a TLS error ("the underlying connection was closed")
because of a schannel credential problem on this machine, while Python and
`web_fetch` work fine. That is a local shell issue, not a network outage, and it
is easy to misdiagnose as "no internet".

### Round 8 — the Atlas MEDIA engines are now wired in

Previously Atlas supplied only the creative *decisions* while every media stage
ran on the bundled renderers. Since the judging criterion is "depth of quantum and
**Atlas** usage", `engines.py` now routes four real engines:

| stage | engine | inputs | what the tests assert |
|---|---|---|---|
| image interference | `blur-v1` | `image` | PNG in, PNG out, output differs from input |
| two-image blend | `telablur-v1` | `image1`, `image2` | both slots sent |
| space / decay | `retrocausal-echo-v1` | `audio`, `ir` | WAV in, non-silent stereo WAV out |
| generative texture | `entanglement-shader-v1` | none | correct size, no input_files |

The tests are not "did a job complete" — they assert that **real bytes
round-trip**: the blob the engine read is byte-identical to the PNG sent, the
returned image decodes and differs from its input (mean abs diff 0.0151), and the
returned audio is non-silent stereo at the reported sample rate. Capability is
probed from `GET /engines` rather than assumed; a fallback is always visible
(`used_atlas: false` plus a `fallback_reason`), and `strict=True` raises instead
of silently substituting local output.

**One honesty bug found while wiring it:** media stages were labelled with the
*quantum backend's* name, so an Atlas-quantum / local-media run reported
`source: atlas` — which reads as "Atlas rendered this". The quantum backend and
the media renderer are separate things and are now labelled separately
(`atlas-media` vs `local-renderers`).

### Round 7 — packaged, and three packaging bugs found

The project is now a git repo (3 commits, no secrets, `.gitattributes` pinning
line endings) plus a self-describing bundle from `make_bundle.py`. Packaging
turned out to be its own source of silent failures:

1. **`.gitignore` excluded the deliverables.** Broad `*.png`/`*.mp4`/`*.wav`
   globs dropped the demo film, score and poster — the actual submission
   artifacts. Attempting to recover them with `!demo/*.png` negation rules does
   not work: git will not re-include a file once a broader pattern excludes it,
   and `git check-ignore -v` misleadingly reports the *negation itself* as the
   matching rule, which looks like success. Scratch is now ignored by directory.
2. **The bundle shipped scratch output.** `notebook_output_repeat/` — written by
   the notebook's reproducibility comparison — was committed and included,
   inflating the archive from ~2.1 MB to ~3.6 MB. Removed, and `make_bundle.py`
   now defaults to **deny**: only directories explicitly listed in `SHIP_DIRS`
   are walked, so scratch written by a future script cannot leak in merely
   because nobody remembered to ignore it. A size budget fails the build as a
   second guard.
3. **A reviewer could not verify the notebook from a fresh copy.**
   `verify_notebook.py` failed on a clean extraction because `notebook_output/`
   is generated, not shipped. It now regenerates it automatically when absent,
   so verification works from a cold checkout with no undocumented prerequisite.

The bundle was then verified properly — not by trusting the build, but by
extracting it elsewhere and running all six suites there: **231/231 pass**.

### Round 6 — two bugs found by testing the Atlas path against a mock API

`moth_client.py` and `AtlasBackend` had never executed a single HTTP round trip,
because no API key ever arrived. That was the largest unverified surface in the
project, so `verify_mock_atlas.py` stands up a local server implementing the
documented endpoints and response shapes and drives the real client through
them. It immediately found two bugs that would have surfaced on first live
contact — one of which would have broken the Atlas path completely:

**1. The client leaked its API key to the storage host (security).** `_request`
unconditionally attached `Authorization: Bearer moth_...`, including on
**presigned** upload URLs. Those point at storage, not the API, and are
authorised by their own signature — so the key was being handed to a third-party
host for no benefit. Fixed with an `auth=False` path for presigned calls, and the
suite now asserts the header is *absent* on the presigned PUT. Worth noting the
mock had to be corrected first: my original mock demanded the bearer token on
presigned URLs, which would have hidden exactly this bug.

**2. `AtlasBackend` never populated `probabilities` or `qubit_marginals`
(fatal).** It decoded the measured bitstrings and stopped there, so
`_compose_film` raised `"probabilities must be non-empty"`. **The pipeline had
never actually run on the Atlas backend** — every previous run used
`LocalBackend`. Fixed by reconstructing the distribution from the sampled counts
(observed outcomes take their measured frequency; residual mass spreads evenly
over unobserved outcomes so the vector sums to 1 deterministically), then
deriving marginals, entropy and pair mutual information from it. Because sampled
counts carry shot noise this is an *estimate*, not an exact statevector readout —
which is why the receipt records the shot count.

Both bugs were invisible to every existing suite, because every existing suite
used `LocalBackend`. That is the general lesson: a second implementation of an
interface is only trustworthy once it has been executed.

### Deliverable 3 — `game.py`, "DEVELOP THE NEGATIVE" (challenge 05)

Added as a **game mode inside the existing web app**, not a third separate
project, so the game entry costs a fraction of a standalone build. Playable at
`/game`, driven by `/api/game/start` and `/api/game/<id>`.

The design intent was to make the game **mechanically** quantum rather than
thematically quantum — a quiz with quantum clip-art would satisfy the brief and
prove nothing. So the circuit *is* the game's state machine:

- Each round asks: if qubit *q* were measured now, would it read 0 or 1? The
  answer is the **Born-rule marginal** of the live state.
- Scoring rewards **earliness** (reading a less-developed state correctly) and
  penalises a wrong read, so guessing is actively bad rather than merely
  unrewarded. Measured over 60 seeds: perfect 1813 vs random 828 (**2.19x**),
  and a perfect player answers 8/8 while guessing manages ~4.1/8.
- The plate is rendered from the circuit's own probability distribution, so the
  picture the player develops *is* a picture of the state they are reasoning
  about.

Four bugs found while building it, all recorded in the code:

1. `apply_dip` could pick the same qubit as CNOT control and target.
2. A question could be asked about a qubit at **exactly 0.5 marginal**, where
   "the more likely outcome" is an arbitrary tie-break rather than a Born-rule
   answer — i.e. a genuinely unanswerable question.
3. The rewrite's `for ... else` fallback was **dead code**: the loop body always
   `break`s on success and has no break-free path, so the `else` never ran and
   the state could reach a point where no question was constructible.
4. The root cause of (2) and (3): building the dip from **Hadamard layers**
   drives every marginal toward exactly 0.5 (entropy still well below n bits, so
   the state was structured but no individual qubit was readable). The same
   H-vs-rotation trap the pipeline hit. Fixed by evolving with **RY rotations**
   and entangling with CNOTs — CNOT preserves the control's marginal, so bias
   and entanglement coexist.

### Deliverable 1 — `QUANTUM_NEGATIVE.ipynb` (challenge 10, Expert)

29 cells (13 code, 16 markdown), **executed with 0 errors**, outputs saved in the
file. Covers: the quantum core and its correctness checks; deriving the creative
budget; the physics gates; the seed-dependence demonstration; a deliberate
reproduction of the broken diagonal-gate circuit next to the fix; rendering with
the poster/score/film displayed inline; the provenance receipt; a byte-level
reproducibility check; and the Atlas API section.

Regenerate and re-execute with `python -B build_notebook.py --execute` (the
executor is self-contained — `nbclient` is not installed and pip cannot reach the
network here).

### Deliverable 2 — `webapp.py` (challenge 08, Intermediate)

Stdlib-only HTTP server (`http.server`), no build step and no dependencies. Serves
an app at `/`, a JSON API (`/api/health`, `/api/generate`, `/api/job/<id>`,
`/api/gallery`), and generated artifacts from `/files/<job>/<name>`.

    python -B webapp.py            # http://127.0.0.1:8000
    python -B webapp.py --offline  # never contact Atlas

It reports, **per run**, which backend actually produced the media
(`local-emulator` vs `atlas`), so a simulated run is never presented as an Atlas
run. Verified over real HTTP: startup, all endpoints, input validation, 404s,
**path-traversal refusal**, a full generation job with stage progress, correct
content types, a valid MP4 container header, gallery listing, and byte-identical
output for a repeated prompt.

### Still blocked, and only this

A valid `moth_` API key. Everything that can be built or proven without
credentials is done. Place it at `moth/.moth_api_key` (or export
`MOTH_API_KEY`), then run the staged smoke test:

```
python -B smoke_test.py auth       # -> features[], including run_quantum
python -B smoke_test.py engines    # -> live engine list vs the spec
python -B smoke_test.py run        # -> cheapest no-input engine, real job
```

## What the pipeline delivers on one prompt (see `demo/`)

| artifact | what it is |
|---|---|
| `quantum_negative.mp4` | 512x512 H.264, 92 frames, 7.7s, yuv420p |
| `quantum_negative.wav` | 16-bit stereo, 32 notes, ~10s |
| `poster.png` | still frame |
| `receipt.json` | every creative decision + the quantum primitive behind it + sha256 of each artifact |

**Verified properties** (`verify_pipeline.py`):

- Artifacts are well-formed: H.264 decodes via ffprobe, WAV is stereo 16-bit
  with real duration, PNG magic bytes checked, video duration matches receipt.
- **Reproducible:** same prompt → byte-identical wav, mp4 and png.
- **Distinctive:** a different prompt changes ≥3 creative parameters and the audio bytes.
- **Provenance:** every choice names its engine and source; receipt hashes match
  the files on disk.
- **The quantum choice is audible**, not decorative: the selected timbre's
  spectral centroid is measured and the candidate timbres are proven distinct
  (fm=1836Hz, odd=1145Hz, all=961Hz, oct=1013Hz at one seed).

## Two bugs found this round that would have sunk the "quantum-native" claim

**1. The circuit was a no-op on measurement statistics (critical).** The first
circuit used H, CNOT, iSWAP, then seed-derived **RZ** and **CZ**. It measured as
the *uniformly mixed* state: entropy exactly `n` bits and every pairwise mutual
information exactly 0. `RZ` and `CZ` are both **diagonal**, so they contribute
only relative phase, which cancels out of every computational-basis probability.
The outcome distribution was therefore completely independent of the seed — the
"quantum randomness" driving the film was just integer ordering. Fixed by
injecting the seed through **non-diagonal RY** rotations with entangling gates
between passes. Now: entropy 7.29/9 bits (not saturated), mean adjacent mutual
information 0.090 bits, strongest pair 0.68 bits, L1 distance between two seeds
1.57. Guards for all of this are now hard gates in `verify_pipeline.py`.

**2. The first poster was a coarse barcode.** `readout_texture` stretched 8
marginals across 512px, giving 64px bands with obvious repetition. Replaced with
`correlation_field`, which draws the O(n²) mutual-information matrix as a moire
whose wave *orientation* follows the gradient contours of the probability
field. Qubit count was then chosen by **looking at the output**: 8 qubits tiles
visibly (16x16 map), 10 is near-uniform (H=7.97/10) and tiles again, **9** is the
sweet spot.

## Round 1 findings (still current)

- `qsim.py` — statevector core, 44/44 tests: unitarity to 1.7e-15, Bell-state MI
  of exactly 1.000000000 bit, exhaustive iSWAP basis-state correctness,
  deterministic seeded sampling, reservoir + readout beating the mean baseline by
  3.4x linearly and fitting to MAE 0.005 with degree-2 features.
- `moth_client.py` — compiles; key resolution, staged errors, and the whole
  request transport verified.
- **Base URL is CONFIRMED: `https://api.mothquantum.com`.** Unauthenticated
  and dummy-key calls to `/api/v1/me` and `/api/v1/engines` return
  `401 {"detail": "authentication required"}` — a real API answer. Nothing in
  the spec needed to change; `servers: null` in the spec was the only gap.
- **Cloudflare gotcha, solved:** the API rejects the default Python urllib
  signature with `403 "The site owner has blocked access based on your
  browser's signature"`. Sending an honest identifying `User-Agent` (now the
  client default) turns that into a clean `401`. Any agent using plain
  `urllib`/`requests` defaults against this API will hit the same wall.

**Blocked on one input:** a valid `moth_` API key. Place it at
`moth/.moth_api_key` (first line) or export `MOTH_API_KEY`, then run:

```
python -B smoke_test.py auth       # -> features[], including run_quantum
python -B smoke_test.py engines    # -> live engine list vs the spec
python -B smoke_test.py run        # -> cheapest no-input engine, real job
```

## The API in one page

- **Spec:** OpenAPI 3.1, title `moth-api`, version `v0.41.0`, 62 paths.
  **25 engines** have an enumerated `/process` path, and there is also a generic
  `POST /api/v1/engines/{engineID}/process` — so `GET /api/v1/engines` is
  authoritative for the live list; trust it over this count.
- **Auth:** `Authorization: Bearer <key>`. Two schemes:
  - `bearerAuth` — accepts **either** a Supabase JWT **or a `moth_` API key**.
    Everything we need (assets, engines, jobs) works with the API key.
  - `bearerJWTAuth` — JWT only; needed for *grants, transfers, invitations*.
    We do not need these.
- **API key:** created from the dashboard, or via `POST /api/v1/keys`
  (`{"name": "..."}`) which returns `CreateKeyOutputBody {key, key_id, name}`.
  The `key` field is the secret — store it, never commit it.
- **Base URL:** `https://api.mothquantum.com` (confirmed by live 401, see above).
- **Account gate:** every request checks for a *current active account*, so the
  key only works once the platform account is active.
- **Credits:** engines declare `credits_per_run`, and `/me/storage` exposes
  `quota`/`usage`. Watch this — we have a limited budget.

## The core job flow

```
POST /api/v1/assets                     -> {asset_id, upload:{url, headers}}
PUT  <upload.url>  (exact headers)      -> bytes go straight to storage
POST /api/v1/assets/{asset_id}/complete -> status: uploaded
POST /api/v1/engines/{engine_id}/process {input_files:{slot:asset_id}, params:{...}, mode}
                                        -> 202 {job_id, status, submitted_at}
GET  /api/v1/jobs/{job_id}/status       -> poll until completed|failed
GET  /api/v1/jobs/{job_id}/result       -> outputs[]: {slot, url, filename, ...}
GET  <output.url>                       -> download the artifact
```

Notes that matter:

- `input_files` maps a **slot name to a caller-owned, uploaded asset UUID**.
  Shared assets *cannot* be used as inputs. Slot names are declared per engine
  (e.g. `image`, `mask`, `audio`, `midi`, `model`, `state`).
- The file bytes never pass through the API — presigned URLs only.
- **Async by default.** Always poll; do not assume a result.
- `steps` / `start_from` / `stop_after` let us run or resume an engine's
  workflow partially — useful for cheap iteration on expensive engines.

## Full engine inventory (27)

Derived from both `/api/v1/engines` and the enumerated `/process` paths.

**Image / 2D**
| engine | what it does |
|---|---|
| `tessa-image-v1` | Tessa Image. Real-QPU image generation; `machine` enum includes `aer`, `least_busy`, `ibm_fez`, `ibm_marrakesh`, … |
| `blur-v0`, `blur-v1` | Quantum Blur on images (input `image` + optional `mask`) |
| `blur-core-v1` | "Quantum Blur Core" — unitary, information-preserving blur on an **arbitrary N-dim grid of numbers**, amplitude-encoded onto a Gray-coded qubit grid |
| `telablur-v1` | Quantum Teleblur — blurs **two** images together (+ mask), `direction: full/vertical/horizontal` |
| `deep-fryer-v1` | Deep Fryer, tile/gate based |
| `qpixl-v1` | QPixl image encoding; `machine` enum with many `fake_*` backends and `mode: emu/qpu` |
| `qrc-image-v1` | QRC Image — reservoir computing to generate image sequences (`fps`, `length`) |
| `entanglement-shader-v0/v1` | Entanglement Shader — **3D/rendering**; styles `peaked`, `frustrated`, `3-body`, `constrained` |
| `tomography-api-v2` | Tomography on a **user-supplied circuit** (`circuit_qasm` required) |

**Audio / music**
| engine | what it does |
|---|---|
| `blur-midi-v1` | Blur Jazz — quantum blur across MIDI piano rolls |
| `qrc-audio-v1` | QRC Audio — reservoir computing audio generation |
| `qrc-midi-v1` | QRC MIDI generation |
| `qrc-train-v2` | QRC Train — trains the reservoir on a token sequence |
| `qrc-gen-v2` | QRC Generate — generates from a trained state |
| `otoc-echo-v1` | Quantum Echo — out-of-time-order correlator, audio rendering |
| `retrocausal-echo-v1` | Retrocausal Echo — convolution/reverb with an IR, `negative_mode: invert/reverse/phase` |

**Games / interactive / structured**
| engine | what it does |
|---|---|
| `labyrinth-v1` | Quantum Labyrinth — level generation from a coupling map; takes `level_data` with `grid_size`, `num_qubits`, `initial_states` |
| `graph-v1` | Quantum Graph — **arbitrary user-defined operations** (`BlochOperation`, `RelationshipOperation`) on a coupling map |
| `tamagotchi-v0`, `tamagotchi-v1` | Tamagotchi — QEC/stabilizer toy with noise params (`p_1q`, `p_gate`, `p_idle`, `p_meas`) |

**Raw quantum / primitives**
| engine | what it does |
|---|---|
| `coin-toss-v1` | Quantum coin toss, `mode: emu/qpu`, `shots` |
| `comet-qrng-v1` | Comet QRNG — certified randomness; `bell_witness`, `epsilon_log2`, Toeplitz derivation, pulse chaining |
| `qdrive-api-v1` | QDrive — takes an **initial circuit** asset, ansatz/coupling map/targets, `update_method: spectral`, tomography options |

## Critical capability finding

Many engines accept **`mode: "qpu"`**, and the spec says plainly:

> *Some param values are reserved for accounts holding a platform feature
> (for example `mode=qpu` requires `run_quantum`) and answer 403 naming the
> feature.*

So real-QPU execution is a **feature flag on the account** (`run_quantum`).
`GET /api/v1/me` returns `features: [...]`. The judging criterion is literally
**"depth of quantum and Atlas usage"** — therefore:

1. First thing to check after auth: does the account have `run_quantum`?
2. If yes, include at least one genuine `mode: qpu` run and document the
   backend, shots, and any noise/error data. That is the strongest possible
   evidence of depth.
3. If no, fall back to `emu` plus the `fake_*` device backends (which model real
   hardware noise) — and say so honestly.

## Submission plan

One coherent project, aimed at three challenges:

| # | Challenge | Tier | Prize | Artifact |
|---|---|---|---|---|
| 2 | Quantum-native 2 | Expert | £200 | Python notebook: full API workflow generating media |
| 8 | Make a web app | Intermediate | £150 | Deployed web app calling the Atlas API |
| 5 | Quantum game | Intermediate | £150 | Only if the pipeline fits a game loop |

Judging: **quality of execution · depth of quantum and Atlas usage ·
originality**, relative to tier. The expert tier is the least crowded, so the
notebook is the priority.

## Open questions for the Discord / docs

1. API **base URL** (spec has no `servers`).
2. Does our account carry **`run_quantum`**? (Check `/api/v1/me`.)
3. Deadline: is **2 Oct** 23:59 London?
4. Can **one** project be entered into multiple challenges?
5. Airtable form fields — what exactly must be submitted per challenge?
6. Semantics of `assets ... kind=notebook` / `notebook_id`: is the platform
   notebook the expected deliverable for Quantum-native 2, or is a standalone
   `.ipynb` fine?
7. Credit budget: how many runs do we get? (`credits_per_run`, `/me/storage`)

## Repo layout

```
moth/
  dump_spec.py     # regenerate api-notes.txt from the OpenAPI JSON
  api-notes.txt    # every endpoint + field, human-readable
  NOTES.md         # this file
  moth_client.py   # stdlib-only client (auth, assets, jobs, engines)
  smoke_test.py    # auth -> engines -> one cheap job -> download
```
