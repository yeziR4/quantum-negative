# Airtable submission — written against the ACTUAL form

Replaces the earlier version of this file, which was written from the hack
website's challenge list rather than the form itself and therefore used **wrong
challenge numbers**. The form is the authority. Corrected below.

**Deadline: 11:59 PM Pacific Time, Monday 5 October 2026.** (Pacific, not AoE.)
The form also warns: "If we cannot watch the video, we cannot mark your work."

---

## The actual challenge list (from the form)

| Form label | Our relevance |
|---|---|
| Beginner 1: One image, one engine | possible bonus — we have blur-v1 output + params |
| Beginner 2: Make it audible | possible bonus — we have retrocausal-echo-v1 output |
| Beginner 3: Three dimensions | no |
| Intermediate 1: Moving image | **strong fit — we produce a film** |
| Intermediate 2: Quantum game | strong fit — DEVELOP THE NEGATIVE |
| Intermediate 3: Daisy chain | strong fit — we use many engines |
| Intermediate 4: VST or AU | no |
| Intermediate 5: Web app | strong fit — webapp.py |
| Advanced 1: Quantum-native #1 | maybe — repo of a quantum application on media |
| Advanced 2: Quantum-native #2 | **strong fit — the notebook** |
| Guest challenge: FQxl challenge | unknown; needs checking |

**Recommendation:** submit to **Advanced 2: Quantum-native #2** first (that is
what the notebook is for), then **Intermediate 5: Web app**, then decide between
**Intermediate 2: Quantum game** and **Intermediate 1: Moving image**.

---

## "Tell us about yourself / team"

**Are you submitting as a team or as an individual?**

```
Individual
```

**Team's name (if team) or your name (if individual)**

```
Yezir
```

**Main contact email address**

```
[FILL IN — the address you registered with]
```

**Main contact Discord handle**

```
[FILL IN — REQUIRED. This is the one field I cannot supply. It must match your
Moth Discord account.]
```

**GitHub handle**

```
yeziR4
```

**Your occupation (if individual)**

```
[FILL IN — one line, whatever is true. See the checklist at the end.]
```

**Other URLs / vital context**

```
Repo: https://github.com/yeziR4/quantum-negative
Simulator-vs-hardware comparison:
https://github.com/yeziR4/quantum-negative/tree/master/comparison
```

---

## "Tell us about your project"

### Project title

```
QUANTUM NEGATIVE
```

### Elevator pitch — describe your project in one sentence

```
A prompt becomes a short film whose every creative decision is a measurement on a
quantum circuit, rendered on real IBM quantum hardware and shipped with a receipt
proving which engine produced each choice.
```

### Select your challenge

**Advanced 2: Quantum-native #2**

### Project description — required, 100–200 words

Word count: **178** (form allows 100–200)

```
QUANTUM NEGATIVE turns a text prompt into a short audiovisual piece in which
every creative decision is a measurement outcome of a quantum circuit. The
classical code renders; it never chooses.

The motivation is that a physical quantum computer is a genuinely
non-deterministic device whose error is a property of the hardware rather than of
the algorithm. The piece is built to make that visible rather than to hide it.

A prompt is hashed to a seed. A 256-value array derived from that seed is encoded
into a quantum circuit by qpixl-v1, measured on ibm_fez, and returned. The
deviation between what was sent and what came back drives the melody, colour and
structure. blur-v1 and telablur-v1 filter the image layer; retrocausal-echo-v1
produces the reverb.

The artifacts are a short film, a stereo score, a poster and a machine-readable
provenance receipt. A companion comparison renders the same prompt on the Aer
simulator and on real hardware: the simulator converges toward the exact circuit
answer as shots rise, while the device settles at an error floor that sampling
cannot remove.
```

### Technical description — required, 50–100 words

Word count: **77** (form allows 50–100)

```
Built on the Moth Atlas REST API from a stdlib-only Python client. A nine-qubit
statevector simulator was written from scratch for local work; Atlas supplies
real execution. Engines used: qpixl-v1 (encode/measure/decode, on ibm_fez and
Aer), blur-v1, telablur-v1 and retrocausal-echo-v1. QPU runs submit mode='qpu'
with an explicit backend_name; emulation uses mode='emu' on the platform's Aer
machine. Media is assembled with numpy and ffmpeg, and provenance is recorded per
decision. 269 automated checks verify the physics and the output.
```

### Which Moth Atlas engines did you use? (multi-select)

Tick only these five — we actually drove each one:

- [x] **qpixl-v1** — the creative budget: encodes our array into a circuit, measures it
- [x] **blur-v1** — image interference
- [x] **telablur-v1** — two-image morph
- [x] **retrocausal-echo-v1** — reverb and space on the score
- [x] **tomography-api-v2** — probed while evaluating engines

Other engines visible to the account, which we did **not** run: blur-core-v1,
blur-v0, blur-midi-v1, coin-toss-v1, comet-qrng-v1, deep-fryer-v1,
entanglement-shader-v1, graph-v1, labyrinth-v1, otoc-echo-v1, qdrive-api-v1,
qrc-*, tamagotchi-*, tessa-image-v1. **Do not tick them.** `entanglement-shader-v1`
in particular was called, but it returns shader source rather than an image, so
we did not use its output.

### QPU or emulation?

```
Both. The creative budget runs on real hardware — qpixl-v1 on ibm_fez, with the
IBM job ids recorded in the repository (for example db0ap9s92g1c739a6cq0, 4
QPU-seconds) — and the same engine also runs in emulation for the side-by-side
comparison. The remaining stages use the platform's emulation.
```

### Code repository

```
https://github.com/yeziR4/quantum-negative
```

### Demo URL

```
[Leave blank — the web app runs locally via `python webapp.py`. The video and the
repo cover everything a judge needs.]
```

---

## Media — all supplied

| Field | Value |
|---|---|
| **Demo video** | **https://youtu.be/4eeO1za0FQg** — verified public, 112s (under the 3-min cap) |
| **Poster art** | `demo/poster.png` — 512×512, 1:1 (form accepts 1:1 to 4:3) |
| Additional images (up to 5) | `comparison/side_by_side.png`, `qpu_demo/poster.png`, `demo/poster.png` |
| Presentation slides | not supplied (optional) |

The video was verified with YouTube's own oEmbed endpoint (`HTTP 200` with title
and author) and by reading the watch page, which reports `"isUnlisted": false`.
So it is **genuinely public**, not unlisted — which is the failure the form warns
about, and the most common way an otherwise good entry becomes unmarkable.


## Honest answers to the disclosure questions

These are asked plainly, so answer them plainly. Being caught hedging would cost
more than the disclosure does.

### Generative AI usage

```
Yes. The engineering was built collaboratively with an AI coding agent (DeepSeek
Harness), which wrote the pipeline, the simulator, the Atlas client and the test
suites, and ran the API jobs. All creative decisions in the artwork come from the
quantum circuit's measurement outcomes, not from a language model: no generative
model touches the melody, the image or the audio.
```

### What generative AI tools did you use?

```
DeepSeek Harness (agentic coding). No image-, audio- or video-generation models
were used to create the artwork.
```

### Non-Moth APIs

```
No.
```

### Non-Moth API details

```
Not applicable — no non-Moth APIs were used.
```

---

## Media you must supply — the real gaps

| Field | Status |
|---|---|
| Poster art (required, 1:1 to 4:3) | **ready** — `demo/poster.png` (512×512, 1:1) |
| Demo video (required, public link, ≤3 min) | **NOT MADE — the biggest gap** |
| Additional images (up to 5) | **ready** — `comparison/side_by_side.png`, `qpu_demo/poster.png`, `demo/poster.png` |
| Presentation slides (PDF) | optional — not made |

**The video is required, and the form says work cannot be marked without it.** It
must contain the pitch, the technique and the results. Our existing film is under
10 seconds and does not explain itself, so **it does not satisfy this.**

### Planned video (≈2 minutes, no editing skill needed)

1. **0:00–0:20** — the film playing, no narration.
2. **0:20–0:45** — the pitch over the poster: *every decision is a measurement on
   a quantum circuit, and this one ran on real IBM hardware.*
3. **0:45–1:20** — the comparison: simulator left, hardware right, the numbers
   (0.010 vs 0.086, 8.6×). Say the point aloud: *the simulator approaches the
   exact answer as you sample more; the device cannot, because its error is
   physical.*
4. **1:20–1:45** — the provenance receipt scrolling: every decision, the engine
   behind it, the IBM job ID.
5. **1:45–2:00** — the repo, and the 269 checks.

I can assemble all the visuals for this. What I cannot do is record your voice.

---

## Checklist before submitting

- [x] **Demo video** — done: https://youtu.be/4eeO1za0FQg — verified public
      (`isUnlisted: false`), 112s, under the 3-minute cap.
- [x] **Repo link** — done: https://github.com/yeziR4/quantum-negative
- [ ] **Discord handle** — required, must match your Moth Discord account.
- [ ] **Occupation** — one true line. e.g. *Software engineer*, *Student*,
      *Independent developer*.
- [ ] **Consider tidying the YouTube title.** It currently reads
      `Quantum Negative  Prompt as Quantum Measurement` — missing a colon, with a
      double space. Suggested: `QUANTUM NEGATIVE — a film whose every decision is
      a quantum measurement (Moth Hack 2026)`. Judges scanning many entries
      benefit from seeing the event name.
- [ ] **Choose categories.** Recommended order: **Advanced 2 (Quantum-native #2)**
      first, then Intermediate 5 (Web app), then Intermediate 2 (Quantum game) or
      Intermediate 1 (Moving image).
- [ ] **Find out what the FQxl guest challenge is** — not on the hack website.
- [ ] Tick both permission boxes and the eligibility confirmation.
