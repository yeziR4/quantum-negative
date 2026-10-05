# Brief for Claude: produce the Moth Hack demo video

Everything needed is here. This is a handoff document — you should not need to ask
follow-up questions to produce the deliverable.

---

## 1. The task

Produce a **final demo video** for a hackathon submission, using:

- **an existing 90.8-second cut** (already built, on disk) as the visual base, or
  fresh screen recording of the artifacts,
- **a voiceover in the user's cloned voice**, reading the script in §4,
- optionally, clean screen recordings of the running project (§6).

**Hard requirements from the submission form:**

- Public link (YouTube or Vimeo), **set to public, not unlisted** — the form warns
  explicitly: *"If we cannot watch the video, we cannot mark your work."*
- **Maximum 3 minutes.** Do not exceed.
- Must contain: the idea pitch, the techniques used, and the results.

The existing cut is 90.8s. With a voiceover it will stay near 2 minutes, which
leaves comfortable headroom. **Do not pad it to 3 minutes.**

---

## 2. The project, briefly

**QUANTUM NEGATIVE** — a text prompt becomes a short film in which every creative
decision (melody, instrumentation, colour, scene structure, image operators) is a
**measurement outcome of a quantum circuit**. Classical code renders the piece; it
never chooses.

Pipeline: prompt → SHA-256 → seed → a 256-value array derived from that seed →
sent to the Moth Atlas engine **`qpixl-v1`**, which encodes it into a quantum
circuit, measures it on **`ibm_fez` (real IBM quantum hardware)**, and returns the
decoded values → the deviation between sent and returned drives the artwork.

Other Atlas engines used: **`blur-v1`** and **`telablur-v1`** (image layer),
**`retrocausal-echo-v1`** (reverb on the score).

**The centrepiece result** — the same prompt rendered twice, once on the Aer
simulator and once on real hardware:

| shots | simulator mean change | hardware mean change | ratio |
|---|---|---|---|
| 256 | 0.0643 | 0.0954 | 1.5× |
| 8192 | **0.0101** | **0.0859** | **8.6×** |

Hardware run: IBM job `db0ap9s92g1c739a6cq0`, 4 QPU-seconds.

**Why this matters, and the line to land:** raise the shot count and the simulator
*converges toward the exact circuit answer* (0.064 → 0.010), while the real device
settles at an *error floor that more sampling cannot remove* (≈0.086) — because
that floor is decoherence, gate error and readout error. **That is the difference
between simulating a quantum computer and using one.**

Also true and worth saying: every decision carries a machine-readable provenance
receipt naming the engine that produced it, and **269 automated checks** across six
suites all pass.

---

## 3. The visual base — already built

Location: `C:\Users\yezir\OneDrive\Documents\yukon-research\moth\`

The cut already exists:

```
video_assets\quantum-negative-demo.mp4      # 90.8s, 1920x1080, H.264, 5.1 MB
```

It contains, in order:

| time | content |
|---|---|
| 0:00–0:09 | **Title card** — "QUANTUM NEGATIVE / every creative decision is a measurement on a quantum circuit / Moth Hack 2026 · Advanced 2: Quantum-native #2" |
| 0:09–0:17 | **The film** — 7.7s, with its own score |
| 0:17–0:37 | **Pipeline card** — prompt → sha256 → 256 values → **qpixl-v1 on ibm_fez** (highlighted gold) → measurement → melody/colour/structure |
| 0:37–0:59 | **Comparison card** — simulator vs real hardware side by side, **8.6× MORE ERROR** in a gold box. The hardware image is visibly hazier, its ring structure broken up. |
| 0:59–1:17 | **Receipt card** — the real `receipt.json` rendered as a panel: each decision, its engine, the IBM job id `db0ap9s92g1c739a6cq0`, and `params_clamped: reach 2 -> 1` |
| 1:17–1:31 | **Repo card** — github.com/yeziR4/quantum-negative / 269 automated checks |

Audio bed: the project's own generated score, at 35% volume, looping.

**To rebuild any of it** (deterministic, no network needed):

```bash
cd C:\Users\yezir\OneDrive\Documents\yukon-research\moth
python -B build_video_assets.py     # writes the 5 cards + a 16:9 film
python -B assemble_video.py         # concatenates + adds the score
```

Individual cards are at `video_assets\01_title.png` … `05_repo.png` if you would
rather re-edit than voice over the finished cut.

---

## 4. The voiceover script — read this, in this order

Written to fit the existing cut. Read at a **normal, unhurried pace**. Timings are
anchors, not straitjackets — if a line lands early or late by a second or two,
that is fine. If your read runs long overall, the safe place to lose time is the
pipeline segment (0:17–0:37).

**[0:00 — title card]**

> This is Quantum Negative. A text prompt becomes a short film, and every creative
> decision in it is a measurement on a quantum circuit. The code renders. It never
> chooses.

**[0:17 — pipeline card]**

> The prompt is hashed to a seed. That seed becomes an array of two hundred and
> fifty-six values, which the qpixl engine encodes into a quantum circuit,
> measures on ibm fez — real IBM hardware — and hands back. That deviation,
> between what went in and what came back, is what drives the melody, the colour
> and the structure.

**[0:37 — comparison card]**

> We rendered the same prompt twice: once on the simulator, once on the real
> device. The simulator changes those values by about one percent. The hardware,
> by nearly nine — eight point six times more.

**[0:47 — still on comparison card]**

> And that difference is not noise we can average away. Raise the shot count and
> the simulator converges toward the exact circuit answer. The device cannot. It
> settles at an error floor, because that floor is decoherence and gate error —
> the physics of the machine.

**[0:59 — receipt card]**

> Every decision is written to a provenance receipt, with the engine that produced
> it, the IBM job id, and the QPU seconds. Two hundred and sixty-nine automated
> checks verify the physics and the output.

**[1:17 — repo card]**

> Everything is public — the pipeline, the notebook, both receipts, and the
> comparison. Quantum Negative, at github dot com slash yeziR4 slash
> quantum-negative.

**Pronunciation:** "qpixl" as *"Q-pixel"*. "ibm fez" as written (it is a real
device name). "yeziR4" as *"yezir four"*.

---

## 5. Constraints and things to get right

1. **This is an AI-built project and that is disclosed.** The submission form
   answers "yes" to LLM-generated code, naming the agent that wrote it. **So the
   video must not claim human authorship of the code.** Present tense statements
   about what the project does ("the code renders", "we rendered the same prompt
   twice") are accurate and fine — the *creative* work is genuinely not
   LLM-generated: the melody, image and audio all come from quantum measurement
   outcomes. Do not add lines like "I wrote every line" or "I built this from
   scratch".
2. **Do not overstate the quantum claims.** The account is authorised for QPU use
   and the hardware runs are real, with IBM job ids recorded in the repo. But we
   may not claim the artwork was produced on hardware for *every* stage — only the
   creative budget (`qpixl-v1`) runs on `ibm_fez`; the rest is emulation. Say
   "partly on real IBM hardware", as the script does.
3. **Keep the numbers exact.** 8.6×, 0.010 vs 0.086, 269 checks, 90.8s cut, IBM
   job `db0ap9s92g1c739a6cq0`. These are all verifiable in the repo — do not round
   or embellish them.
4. **Do not add music or sound effects.** The score in the video is generated by
   the project itself. Adding licensed or generated music would weaken the claim
   that the piece is quantum-derived, and risks a copyright mismatch.
5. **Keep it under 3 minutes.**
6. **Landscape 16:9, 1080p.** That is what the existing cut is.

---

## 6. Optional: screen recordings worth including

If you can capture clean screen footage, these would strengthen the video. Total
added time should stay under ~20 seconds, and the total must remain under 3
minutes.

1. **The web app.** Run it and show the prompt→film flow:
   ```bash
   cd C:\Users\yezir\OneDrive\Documents\yukon-research\moth
   python webapp.py     # then open http://127.0.0.1:8000  (game at /game)
   ```
   It reports, per run, which engines actually produced each layer and where any
   fell back to a local renderer — that transparency is a selling point, so let it
   be visible.

2. **The receipts, live.** Open
   `comparison\hardware\receipt.json` in an editor and scroll it. Seeing a real
   IBM job id in a real file is more persuasive than a rendered card.

3. **The comparison in the repo.** Open
   `https://github.com/yeziR4/quantum-negative/tree/master/comparison` in a
   browser and show `side_by_side.png` and `REPORT.md`.

Prefer **short, still, legible** captures. Scrolling fast or zooming around makes
a 3-minute budget disappear and reads as padding.

---

## 7. Deliverable

1. The final video file, 1080p, under 3 minutes, with the voiceover mixed over the
   existing score (score ducked to roughly 20–25% under the voice).
2. **Uploaded to YouTube, set to Public**, with the link returned.
3. Suggested title and description for the upload:

```
Title:  QUANTUM NEGATIVE — a film whose every decision is a quantum measurement
        (Moth Hack 2026)

Desc:   A text prompt becomes a short film in which the melody, colour and
        structure are all measurement outcomes of a quantum circuit, run partly
        on real IBM quantum hardware via Moth Atlas.

        Same prompt rendered on the simulator and on ibm_fez: the simulator
        converges toward the exact circuit answer as shots rise, while the device
        settles at an error floor that sampling cannot remove — 8.6x more error.

        Code, receipts and the full comparison: https://github.com/yeziR4/quantum-negative
        Built with Moth Atlas. Advanced 2: Quantum-native #2.
```

4. **Confirm the YouTube link is public** (open it in a private browser window and
   check it plays without signing in). This is the single most common way an entry
   becomes unmarkable.

---

## 8. Context files in the repo, if you need more detail

| file | what it holds |
|---|---|
| `comparison/REPORT.md` | the simulator-vs-hardware finding, written up |
| `comparison/comparison.json` | the exact figures, machine-readable |
| `NOTES.md` | development log, including the API bugs found and fixed |
| `QUANTUM_NEGATIVE.ipynb` | the expert-tier notebook |
| `video_assets/` | the five cards and the 16:9 film |
| `VIDEO_PLAN.md` | the shot plan this brief is built from |

The git history is worth keeping visible: it shows a live API breaking six
assumptions and each one being fixed with evidence. That reads as competence.
