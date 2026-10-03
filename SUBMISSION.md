# Airtable submission text — copy/paste ready

Everything below is written to be pasted into the Moth Hack submission form.
**I have not seen the form**, so the field names are my best reconstruction; the
content is what matters and maps onto any reasonable field set. Anything unknown
is marked **[FILL IN]** rather than invented.

Submit at: <https://airtable.com/appsrkUE9iVgeGsH5/pagdAHP56ovMdYX7x/form>
Deadline: **2 Oct 2026** (confirm the exact time in Discord — the site states the
date without a time).

---

## Project

**Title**

```
QUANTUM NEGATIVE — a quantum-native film generator
```

**One-line summary**

```
A prompt becomes a short film whose every creative decision is a measurement on a quantum circuit — run on real IBM quantum hardware, with a simulator-vs-hardware comparison and a provenance receipt for every decision.
```

**Team / participants**

```
Yezir
GitHub: https://github.com/yeziR4
Solo entry.
```

**Links**

```
Repo      : https://github.com/yeziR4/quantum-negative
Notebook  : https://github.com/yeziR4/quantum-negative/blob/master/QUANTUM_NEGATIVE.ipynb
Comparison: https://github.com/yeziR4/quantum-negative/tree/master/comparison
Hardware  : https://github.com/yeziR4/quantum-negative/tree/master/qpu_demo
Web app   : run locally — python webapp.py   (http://127.0.0.1:8000, game at /game)
Demo      : demo/quantum_negative.mp4, demo/quantum_negative.wav, demo/poster.png
```

Everything is in the public repo: the simulator-vs-hardware comparison with the
IBM job ids, a read-only provenance receipt for every render, and the six
verification suites (269 checks, `python verify_*.py`). No credentials are
committed — verified against GitHub's own file listing, not just locally.

---

## Challenges entered

Tick all three:

```
[x] 10 — Quantum-native 2  (Expert)
[x] 08 — Make a web app    (Intermediate)
[x] 05 — Quantum game      (Intermediate)
```

---

## Submission for challenge 05 — Quantum game

**What it does**

```
DEVELOP THE NEGATIVE is a playable game in which you develop a latent photograph with a sequence of quantum development passes.

Before each pass the game asks a genuinely quantum question: if you measured qubit q right now, would it read 0 or 1? The answer is the Born-rule marginal of the live 8-qubit state — you have to read the quantum state to play. Reading correctly applies a development pass and the image emerges; a wrong read ruins the plate.

The circuit is the game's state machine, not decoration:

- Each development pass is a real rotation layer (RY) on a randomised subset of the register, followed by CNOT entanglement.
- The question each round is the exact marginal of the live state, computed from the statevector.
- The plate you are developing is rendered from that same state's probability distribution, so the picture is a picture of the state you are reasoning about.
- The HUD shows the state's entropy, so you can watch the register become more mixed as you play.

Scoring rewards reading the state EARLY — when fewer passes have resolved it, which is harder — and penalises wrong reads, so guessing is actively bad rather than merely unrewarded. Measured over 60 seeds: perfect play averages 1813 points and 8/8 correct reads, while random guessing averages 828 points and about 4.1/8. That 2.19x gap is asserted automatically in the test suite, because a game where guessing earns nearly as much as skill is a coin flip with decoration.
```

**How to run**

```
python webapp.py      # open http://127.0.0.1:8000/game
```

---

## Submission for challenge 10 — Quantum-native 2

**What it does**

```
QUANTUM NEGATIVE turns a text prompt into a short audiovisual piece in which every creative decision is a measurement outcome of a quantum circuit. The classical code only renders; it never chooses.

Concretely, a 9-qubit circuit is prepared from a seed derived from the prompt. Measuring it yields the creative primitives that drive the whole piece:

- the ranked measurement bitstrings become the melody pitches and the scene structure (count and pacing);
- the rotation angles become the RGB palette;
- the per-qubit marginals become texture layers;
- the pairwise mutual information matrix becomes the moiré structure of the image — each entangled qubit pair contributes a wave whose spatial frequency is set by how entangled it is, oriented along the gradient contours of the measurement distribution;
- the entropy sets the density of that structure.

The notebook walks the entire workflow: it validates the quantum core (unitarity, a Bell state with exactly 1 bit of mutual information, iSWAP verified exhaustively across all four basis states), derives the creative budget, runs physics and provenance gates, renders the film and score, prints the provenance receipt, and re-renders to prove the output is byte-identical.

One section deliberately reproduces a bug: the first working circuit injected the seed through RZ and CZ, which are both diagonal gates, so they contributed only relative phase and cancelled out of every computational-basis probability. The circuit measured as the uniformly mixed state — entropy exactly n bits and every pairwise mutual information exactly zero — so the seed never reached the measurement statistics. The notebook shows that failure next to the fix, because it is exactly the failure mode a reviewer should be looking for.
```

**Depth of quantum and Atlas usage**

```
Quantum depth:
- 9-qubit circuit, ~40 gates, 4096 shots per run.
- Genuine entanglement, measured not asserted: mean adjacent mutual information ~0.09 bits, strongest pair ~0.68 bits, and entropy strictly below n bits so the distribution is not uniform.
- Exact statevector simulation of the circuit, written from scratch with no quantum SDK dependency, so the notebook is self-contained and auditable.
- Quantum reservoir computing: a fixed seeded circuit drives a high-dimensional feature vector, with a classically-trained readout (linear, and degree-2 polynomial when a nonlinear target needs it).
- The circuit's correlation matrix is used directly as compositional material, not merely as a source of randomness.

Atlas usage:
- moth_client.py implements the full Atlas REST workflow: API-key auth, the asset create → presigned PUT → complete dance, job submit with input_files/params/mode, status polling, result retrieval, and streaming artifact downloads.
- AtlasBackend runs the same composition logic against real Atlas engines, including mode="qpu" for genuine hardware execution when the account carries the run_quantum feature. It raises FeatureMissing when a feature is absent, so a missing capability degrades visibly rather than silently pretending to be hardware execution.
- Media stages have direct Atlas counterparts and are documented as the intended path: tessa-image-v1, blur-v1, blur-core-v1, telablur-v1, entanglement-shader-v1, retrocausal-echo-v1, qrc-midi-v1, qrc-audio-v1, blur-midi-v1, with coin-toss-v1 / comet-qrng-v1 as the primitive engines.
- The bundled local engines exist so the notebook runs anywhere with no account and no credits, and so the composition logic is testable in isolation. It is a fallback, not a replacement.
```

**How to run**

```
jupyter lab QUANTUM_NEGATIVE.ipynb

# or regenerate and execute end to end:
python build_notebook.py --execute

Requires Python 3.11+, numpy, Pillow, and ffmpeg on PATH.
The notebook runs fully offline against the bundled simulator.
For the Atlas section, set MOTH_API_KEY.
```

---

## Submission for challenge 08 — Make a web app

**What it does**

```
A web app that turns a prompt into the same audiovisual piece, in the browser. It exposes a JSON API (health, generate, job status, gallery) and serves the generated film, score, poster and provenance receipt.

The UI shows the quantum creative budget for the run — seed, circuit size, entropy, entanglement, the derived melody, scene structure, timbre — alongside a table of provenance listing every creative decision and the engine that made it. A gallery lists earlier pieces.

Because media rendering can take tens of seconds, generation runs as a background job that the page polls, with real stage progress ("deriving the quantum creative budget" → "rendering audio and film" → "encoding artifacts").

The app reports per run which backend actually produced the media (local simulator vs Atlas), so a simulated run is never presented as an Atlas run.
```

**Atlas API usage**

```
The app calls the Atlas API through moth_client.py when a key is configured, and reports the backend actually used on every request. It also surfaces the account's feature flags (including whether run_quantum is available for real hardware execution) via its health endpoint.
```

**How to run**

```
python webapp.py            # http://127.0.0.1:8000
python webapp.py --offline  # never contact Atlas

Standard library only — no build step, no dependencies, no node_modules.
```

---

## Judging criteria — how this addresses each

**Quality of execution.** **266 automated checks across six suites, all passing**: 44 for the quantum core, 44 for the pipeline, 24 for the notebook,
52 for the web app and game exercised over real HTTP, 24 for the game's
mechanics, and 78 driving the Atlas API client and its media engines through their documented protocol against a local mock server. Artifacts are validated as real media (ffprobe
confirms H.264 and duration; the MP4 container header is checked; the WAV is
stereo 16-bit), and the receipt's SHA-256 hashes are verified against the files
on disk. Known limitations are documented rather than glossed.

**Depth of quantum and Atlas usage.** A 9-qubit entangling circuit whose
correlation matrix is used as compositional material; exact entanglement and
entropy metrics; a from-scratch statevector simulator with correctness proofs; a
quantum reservoir; a game whose questions are Born-rule marginals of a live
state; and the full Atlas REST workflow implemented, with `mode="qpu"` support
and honest feature gating. The bug that would have made the whole claim false is
documented alongside its fix.

**Originality.** Most generative work uses randomness as an input. Here the
circuit's *correlation structure* is the material: the image is a picture of the
pairwise mutual information matrix, the piece ships with a provenance receipt
that makes every creative decision auditable, and the game makes the player read
the quantum state itself rather than merely look at its output. Determinism from
a text prompt — the same prompt yields byte-identical media — makes the work
checkable in a way generative art usually is not.

---

## Before submitting — checklist

- [ ] Add your name / GitHub handle.
- [ ] Decide on the repo or file-share link and paste it in.
- [ ] Confirm in Discord whether **one project may be entered into multiple
      challenges**, and whether the **2 Oct deadline has a specific time**.
- [ ] Run the Atlas smoke test and paste the real feature list and, if
      `run_quantum` is present, add a line about hardware execution:
      `python smoke_test.py auth`
- [ ] Optionally host the web app and add the URL.
- [ ] Run all six verification suites one last time and note the totals.

---

## Notes on scope

All three entries are one coherent project rather than three throwaway builds:
the game is a mode inside the web app, and the web app renders the same pipeline
the notebook documents. That was a deliberate choice — sharing the quantum core,
the renderers and the verification gates across three challenges meant each
additional entry cost far less than a standalone build, so the marginal effort
went into depth rather than breadth.

The public Global Quantum Game Jam window closed on 27 Sept, so the optional
double-entry bonus for that jam is no longer available. The Moth challenge itself
still runs to 2 Oct.
