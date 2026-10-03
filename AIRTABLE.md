# Airtable copy-paste blocks

Sized for a form that may still have a short character limit. The mods reported
a 100-character cap that was then "fixed", so each block below is written to be
**usable at ~100 characters** and **better if you have more room**. Start with
the short block; if the field accepts more, paste the longer one instead.

Repo: **https://github.com/yeziR4/quantum-negative** — put this in every form.

---

## Every form, regardless of challenge

**Name / GitHub handle**

```
Yezir (@yeziR4)
```

**Project title**

```
QUANTUM NEGATIVE
```

**Repo link**

```
https://github.com/yeziR4/quantum-negative
```

---

## Challenge 10 — Quantum-native 2  (Expert)  ← put your weight here

**Short description (fits ~100 chars)**

```
A quantum circuit decides every creative choice in a film; proof and receipts in the repo.
```

**Longer description (use if the field allows)**

```
A prompt becomes a short film in which every creative decision is a measurement outcome of a quantum circuit — melody, instrumentation, colour, scene structure and image operators all trace back to measurements. The notebook runs the full workflow end to end through the Moth Atlas API, and includes a simulator-versus-hardware comparison: the same prompt rendered on Aer and on ibm_fez, with the measured deviation from the input recorded for each (mean 0.010 vs 0.086, an 8.6x difference), plus the IBM job id and QPU seconds. Every render writes a provenance receipt naming the engine behind each decision, and 269 automated checks verify the physics and the output.
```

**Workflow summary (likely a separate field)**

```
Prompt -> SHA-256 -> seed. qpixl-v1 encodes a 256-value array into a quantum circuit on ibm_fez, measures it and returns the values; the deviation from the input drives the piece. blur-v1 and telablur-v1 process the image layer, retrocausal-echo-v1 the audio. Notebook shows the pipeline, the physics gates, the provenance receipt and the hardware comparison.
```

**Why it is quantum-native rather than quantum-decorated**

```
The circuit's pairwise mutual information matrix is the image's structure, and its measurement outcomes set the melody and pacing. The notebook also documents a bug where diagonal-only gates made the circuit a no-op on measurement statistics, and shows the fix.
```

---

## Challenge 08 — Make a web app  (Intermediate)

**Short description (fits ~100 chars)**

```
Prompt to quantum-generated film in the browser, via several Atlas engines. Repo linked.
```

**Longer description (use if the field allows)**

```
A web app that turns a prompt into a short film, score and poster, driving the Moth Atlas API from the browser. It reports per run which backend actually produced the media and whether an Atlas engine or the local fallback was used, so nothing is misattributed. Generation runs as a background job with real stage progress, and the page displays the quantum creative budget alongside a provenance table naming the engine behind every decision. Standard library only, no build step, runs with `python webapp.py`.
```

**Includes the game (challenge 05) as a mode at `/game`.**

---

## Challenge 05 — Quantum game  (Intermediate)

**Short description (fits ~100 chars)**

```
Develop a latent photograph by reading qubit marginals. Playable mode in the web app.
```

**Longer description (use if the field allows)**

```
DEVELOP THE NEGATIVE is a playable game in which you develop a latent photograph with quantum development passes. Each round asks a genuinely quantum question: if you measured qubit q right now, would it read 0 or 1? The answer is the Born-rule marginal of the live 8-qubit state, so you must read the quantum state to play. Correct reads apply a development pass and the image emerges; wrong reads ruin the plate. Scoring rewards reading early and penalises wrong answers, so guessing is actively bad: measured over 60 seeds, perfect play averages 1813 points and 8/8 correct reads, random guessing 828 and about 4/8. Playable at /game in the web app.
```

---

## Challenge 01 — One image, one engine  (Beginner, £100)

Only if the form allows extra entries — this is a bonus, not the main submission.

**Short description**

```
Image passed through Atlas blur-v1 with the parameters used recorded in the repo.
```

**Workflow + parameters**

```
film.quantum_field produces a 320x320 grey field from the circuit's probability distribution, then Atlas blur-v1 processes it: strength 0.15, reach 1 (the engine caps reach at 1), style rx, downscale false, size 320. Output is tinted with a palette derived from the circuit's rotation angles. Parameters and the clamped values are recorded in comparison/simulator/receipt.json.
```

---

## Challenge 02 — Make it audible  (Beginner, £100)

Bonus, only if there is room.

**Short description**

```
Score generated from quantum measurement outcomes, with Atlas retrocausal-echo-v1 reverb.
```

**Workflow**

```
Measurement outcomes set the melody pitches and the instrument (additive or FM). The mix is sent to Atlas retrocausal-echo-v1 with decay 0.9, mix 0.32, emit audio, pcm_16. The engine returns three outputs — ir (JSON), result (WAV) and taps (JSON) — and the audio is selected by slot. Non-silent stereo at the reported sample rate; the receipt is in demo/receipt.json.
```

---

## If a form asks you to attach a file

Use the bundle: `dist/quantum-negative-2026-09-26.zip` — self-describing, with a
SHA-256 manifest, no credentials. Everything is also in the public repo, so a
link is usually enough.

## If a form asks about the judging criteria

```
Quality of execution: 269 automated checks across six suites, all passing. Artifacts validated as real media (ffprobe confirms H.264; WAV is stereo 16-bit); receipt hashes verified against the files.

Depth of quantum and Atlas usage: a 9-qubit entangling circuit whose correlation matrix is the image structure. Real hardware: qpixl-v1 on ibm_fez, job db0ap9s92g1c739a6cq0, with a simulator-vs-hardware comparison showing an 8.6x larger deviation on silicon. Four Atlas engines driven by real files; feature gating and fallbacks reported honestly rather than hidden.

Originality: the circuit's correlation structure is the material, not just a randomness source. The game makes the player read the live quantum state. Every decision carries a provenance receipt, and the same prompt reproduces the same bytes.
```
