# QUANTUM NEGATIVE

**Moth Hack 2026 submission** — a prompt becomes a short film whose melody, instrumentation, colour and structure are all **measurement outcomes of a quantum circuit**.

Submitted to:

- **Challenge 10 — Quantum-native 2** (Expert): the Python notebook.
- **Challenge 08 — Make a web app** (Intermediate): the interactive app.
- **Challenge 05 — Quantum game** (Intermediate): *DEVELOP THE NEGATIVE*, a game mode inside the web app.

---

## The idea

Every creative decision in the piece is a measurement on a quantum state. The classical code only *renders*; it never chooses. Melody pitches, scene count and pacing, the instrument, the image operators and the colour palette all trace back to outcomes recorded in a provenance receipt.

"Quantum-native" is easy to claim and hard to check, so this project is built to be checkable. The circuit is verified to actually be doing quantum work, the output is byte-reproducible from the prompt, and the app reports which backend produced each run.

### Why a circuit, rather than a random number generator

Because the *structure* of the state is used as compositional material, not just its unpredictability:

| Circuit property | What it drives |
|---|---|
| Measured bitstrings, ranked by probability | melody pitches; scene count and pacing |
| Rotation angles | the RGB palette |
| Per-qubit marginals | texture layers |
| **Pairwise mutual information** | the moiré structure of the image |
| Entropy | the density of that structure |

The image is literally a picture of the circuit's correlation matrix: each entangled qubit pair contributes a wave whose spatial frequency is set by how entangled it is, oriented along the gradient contours of the measurement distribution.

---

## Contents

| file | what it is |
|---|---|
| `QUANTUM_NEGATIVE.ipynb` | the notebook submission (executed, outputs included) |
| `webapp.py` | the web app |
| `pipeline.py` | prompt → film, with per-decision quantum provenance |
| `qsim.py` | exact statevector simulator, written from scratch |
| `synth.py` | deterministic audio synthesis |
| `film.py` | deterministic image/film synthesis |
| `game.py` | *DEVELOP THE NEGATIVE* — the playable quantum game |
| `checks.py` | physics and provenance gates |
| `moth_client.py` | Atlas API client (auth, assets, jobs, engines) |
| `build_notebook.py` | regenerates and re-executes the notebook |
| `verify_*.py`, `test_qsim.py` | the verification suites |
| `demo/` | a finished piece: film, score, poster, receipt |
| `api-notes.txt` | the full Atlas API reference, extracted from the OpenAPI spec |

---

## Quick start

```bash
# 1. the notebook (self-contained; no account or credits needed)
jupyter lab QUANTUM_NEGATIVE.ipynb
#    ...or regenerate and execute it end to end:
python build_notebook.py --execute

# 2. the web app, including the game
python webapp.py            # http://127.0.0.1:8000   (game at /game)
python webapp.py --offline  # never contact Atlas

# 3. verify everything
python test_qsim.py             # 44 checks — the simulator is physically correct
python verify_pipeline.py       # 44 checks — real, reproducible media
python verify_notebook.py       # 24 checks — the notebook is valid and executed
python verify_webapp.py         # 52 checks — the app and game over real HTTP
python verify_game.py           # 24 checks — the game is quantum and skill-based
python verify_mock_atlas.py     # 78 checks — Atlas client + media engines
```

**266 checks, all passing.** Requirements: Python 3.11+, `numpy`, `Pillow`, and `ffmpeg` on `PATH`. The web app itself needs only the standard library. There is no build step.

`verify_mock_atlas.py` needs no API key: it stands up a local server implementing
the documented Atlas endpoints and drives the real client through the full
workflow, so the REST layer is verified even before a key exists.

To run the Atlas API sections against the real service, provide a key (see below).

---

## Packaging a submission bundle

```bash
python make_bundle.py                 # dist/quantum-negative-<date>.zip + manifest
python make_bundle.py --verify-only   # re-check an existing bundle
```

The bundle is self-describing: it carries a `MANIFEST.json` listing every file
with its SHA-256 and size, so a recipient can confirm the archive survived
transfer. It **refuses to build** if a file matching a secret name would be
included, and it fails if the archive exceeds a size budget.

Those two guards exist because packaging bugs here are silent, and both kinds
already happened: `.gitignore` first excluded the demo media — the actual
deliverables — via broad `*.png`/`*.mp4`/`*.wav` globs, and then the notebook's
scratch `notebook_output_repeat/` directory doubled the archive size. The bundler
now defaults to **deny** at the top level, walking only explicitly listed
directories.

Verify a bundle from a clean extraction rather than trusting the build step:

```bash
unzip -q dist/quantum-negative-<date>.zip -d /tmp/check
cd /tmp/check/quantum-negative
python verify_pipeline.py && python verify_notebook.py && python verify_mock_atlas.py
```

---

## Quantum backend

Two backends implement the same interface, so the composition logic is written once:

- **`LocalBackend`** — the bundled exact statevector simulator. No credentials, fully deterministic. This is the default so the notebook and app run anywhere.
- **`AtlasBackend`** — the real Moth Atlas engines over the REST API, including `mode="qpu"` for genuine hardware execution when the account carries the `run_quantum` feature.

`AtlasBackend` raises `FeatureMissing` when a required platform feature is absent, so a missing capability **degrades visibly rather than silently falling back to a simulator while still claiming hardware execution**. Both the notebook and the web app report the backend actually used, per run.

### Where Atlas engines replace the local ones

| stage | local implementation | Atlas engine |
|---|---|---|
| image blur / interference | `film.quantum_field` | `blur-v1`, `blur-core-v1` |
| image generation | `film.correlation_field` | `tessa-image-v1` |
| two-image blend | `film.entangle_frames` | `telablur-v1` |
| 3D / shader pass | — | `entanglement-shader-v1` |
| reverb / space | `synth.convolve_ir` | `retrocausal-echo-v1` |
| melody generation | `qsim.Reservoir` + readout | `qrc-midi-v1`, `qrc-audio-v1` |
| MIDI transform | — | `blur-midi-v1` |
| creative primitive / randomness | `LocalBackend` circuit | `coin-toss-v1`, `comet-qrng-v1` |

The local path exists so the work runs with no account and no credits, and so the composition logic is testable in isolation. It is a fallback, not a replacement.

### API setup

```bash
export MOTH_API_KEY=moth_...          # or write it to moth/.moth_api_key
python smoke_test.py auth             # account + feature flags, incl. run_quantum
python smoke_test.py engines          # live engine list vs the spec
python smoke_test.py run              # one cheap real job, then download outputs
```

**Note for other participants:** the API sits behind Cloudflare, which rejects Python's default `urllib` user-agent with a **403** ("blocked based on your browser's signature"). That is not an auth failure and is easy to misread as a bad key. `moth_client.py` sends an honest identifying user-agent, which turns it into a clean `401` when unauthenticated and a normal response once a key is present.

---

## Verification

The claim "a quantum process drove these choices" is falsifiable, so the checks are the point.

**Circuit correctness** (`test_qsim.py`): unitarity preserved to 1.7e-15 across random circuits; Bell state gives mutual information of exactly 1.000000000 bit; iSWAP verified exhaustively across all four basis states; deterministic seeded sampling.

**Physics gates** (`checks.py`, used by every suite): entropy is *not* saturated, the state is not uniform, entanglement is present, and measurement outcomes are selection-based rather than index ordering. These exist because of a real bug — the first circuit used `RZ` and `CZ` to inject the seed. Both are **diagonal** gates, so they contribute only relative phase, which cancels out of every computational-basis probability. The circuit measured as the uniformly mixed state: entropy exactly `n` bits and *every* pairwise mutual information exactly zero. The seed never reached the measurement statistics, so the film would have been driven by integer ordering while claiming to be quantum. The notebook reproduces that failure on purpose in §5 and shows the fix.

**Output validation** (`verify_pipeline.py`): artifacts are well-formed (ffprobe confirms H.264 and duration; WAV is stereo 16-bit); the same prompt reproduces **byte-identical** wav, mp4 and png; a different prompt changes several creative parameters; receipt hashes match the files on disk; and the chosen timbre is measurably audible (candidate timbres are spectrally distinct — fm 1836 Hz vs oct 1013 Hz), so the quantum selection demonstrably reaches the delivered audio.

**Deliverable validation** (`verify_notebook.py`, `verify_webapp.py`): the notebook is valid nbformat with every cell executed and no errors, and its embedded outputs contain each claim it makes; the app is exercised over real HTTP including input validation, 404s, path-traversal refusal, correct content types and a valid MP4 container header.

---

## Limitations, stated plainly

- The default path is an **exact classical simulation** of the circuit, not hardware execution. It is a faithful simulation, and the Atlas path is where hardware enters — but the numbers in the notebook were not produced by a QPU, and nothing here implies they were.
- A circuit is not *needed* to make these choices. The argument for using one is that its correlation structure is used as compositional material rather than as a source of randomness alone.
- Entropy and mutual information are computed exactly from the statevector; sampled shot counts are used only for ranking outcomes, never for the metrics.

---

## Credits

Built for [Moth Hack 2026](https://hack.mothquantum.com/) using the [Moth Atlas](https://platform.mothquantum.com) platform. The API surface was taken from the platform's published OpenAPI description (`moth-api` v0.41.0).
