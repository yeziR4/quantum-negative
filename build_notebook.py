"""Build the Moth Hack submission notebook (challenge 10, "Quantum-native 2").

The notebook is generated from this script rather than hand-edited so that the
deliverable is reproducible and reviewable: edit here, re-run, re-verify.

    python -B build_notebook.py            # write the .ipynb
    python -B build_notebook.py --execute   # write and execute it end to end

Executing requires nbformat + nbclient (both are already installed here).
"""

from __future__ import annotations

import argparse
import os
import sys

NB_PATH = "QUANTUM_NEGATIVE.ipynb"


_COUNTER = {"n": 0}


def _next_id() -> str:
    """Deterministic, stable cell id (nbformat 5 requires one per cell)."""
    _COUNTER["n"] += 1
    return f"qn-{_COUNTER['n']:02d}"


def md(*lines: str) -> dict:
    return {"cell_type": "markdown", "id": _next_id(), "metadata": {},
            "source": list(lines)}


def code(*lines: str) -> dict:
    return {"cell_type": "code", "id": _next_id(), "execution_count": None,
            "metadata": {}, "outputs": [], "source": list(lines)}


def build() -> dict:
    cells: list[dict] = []

    # ---------------------------------------------------------------- title
    cells.append(md(
        "# QUANTUM NEGATIVE\n",
        "### A quantum-native film generator, built on the Moth Atlas API\n",
        "\n",
        "**Moth Hack 2026 — challenge 10, *Quantum-native 2***\n",
        "\n",
        "---\n",
        "\n",
        "## What this is\n",
        "\n",
        "A prompt becomes a short audiovisual piece in which **every creative decision is the\n",
        "measurement outcome of a quantum circuit**. The classical code here only *renders*;\n",
        "it never chooses. Melody, instrumentation, scene structure, colour and image\n",
        "operators all come from measuring a quantum state.\n",
        "\n",
        "That separation is the whole point. \"Quantum-native\" is easy to claim and hard to\n",
        "check, so this notebook is built to be checkable:\n",
        "\n",
        "1. **Every decision is recorded** in a provenance receipt naming the engine that\n",
        "   produced it.\n",
        "2. **The circuit is verified** to actually be doing quantum work — the gates below\n",
        "   assert that the state is entangled, that entropy is not saturated, and that the\n",
        "   seed *reaches the measurement statistics*. (During development it did not; see\n",
        "   §5 for the bug and the fix.)\n",
        "3. **The output is reproducible.** Same prompt, same bytes.\n",
        "\n",
        "---\n",
        "\n",
        "## Why this is *quantum*-native rather than quantum-decorated\n",
        "\n",
        "A random number generator would be cheaper. The justification for using a circuit is\n",
        "that its **structure** is used, not just its unpredictability:\n",
        "\n",
        "| Circuit property | What it drives in the piece |\n",
        "|---|---|\n",
        "| Measured bitstrings (ranked by probability) | melody pitches; scene count and pacing |\n",
        "| Rotation angles | the RGB palette |\n",
        "| Per-qubit marginals | the vertical/horizontal texture layers |\n",
        "| **Pairwise mutual information** | the moiré structure of the image |\n",
        "| Entropy | the density of that structure |\n",
        "\n",
        "The image is literally a picture of the circuit's correlation matrix: each entangled\n",
        "qubit pair contributes a wave whose spatial frequency is set by how entangled it is,\n",
        "oriented along the gradient contours of the measurement distribution.\n",
    ))

    # ---------------------------------------------------------------- setup
    cells.append(md(
        "---\n",
        "## 1 · Setup\n",
        "\n",
        "The whole pipeline is dependency-light. Everything below runs offline against the\n",
        "bundled statevector simulator; §8 shows the same interface running on the real Atlas\n",
        "API, including genuine QPU execution when the account provides it.\n",
    ))
    cells.append(code(
        "import json, os, sys, time\n",
        "import numpy as np\n",
        "\n",
        "# The pipeline modules live alongside this notebook.\n",
        "sys.path.insert(0, os.getcwd())\n",
        "\n",
        "import checks, film, pipeline, qsim, synth\n",
        "from pipeline import LocalBackend, AtlasBackend, Pipeline\n",
        "\n",
        "print('numpy', np.__version__)\n",
        "print('ffmpeg available:', film.ffmpeg_available())\n",
        "print('pipeline version:', pipeline.VERSION)\n",
    ))

    # ---------------------------------------------------------------- circuit
    cells.append(md(
        "---\n",
        "## 2 · The quantum core\n",
        "\n",
        "`qsim.py` is an exact statevector simulator, written from scratch with no quantum SDK\n",
        "dependency, so the notebook is self-contained and auditable.\n",
        "\n",
        "Before trusting it to make creative decisions, it has to be demonstrably correct.\n",
        "The checks below are the load-bearing ones: **unitarity** (norm preserved through\n",
        "random circuits), the **Bell state** (maximal entanglement, exactly 1 bit of mutual\n",
        "information), and **iSWAP** verified exhaustively across all four basis states.\n",
    ))
    cells.append(code(
        "# Unitarity: a quantum circuit must preserve total probability.\n",
        "reg = qsim.QuantumRegister(6, seed=1)\n",
        "reg.hadamard(0); reg.cnot(0, 1); reg.ry(2, 1.1); reg.iswap(2, 5)\n",
        "print('norm error after gates:', reg.verify_normalised())\n",
        "\n",
        "# Bell state: maximal entanglement should give exactly 1 bit of mutual information.\n",
        "bell = qsim.QuantumRegister(2, seed=0)\n",
        "bell.hadamard(0); bell.cnot(0, 1)\n",
        "mi = qsim.mutual_information(bell.pair_joint(0, 1))\n",
        "print('Bell state probabilities:', [round(p, 6) for p in bell.probabilities()])\n",
        "print(f'Bell state mutual information: {mi:.9f} bits')\n",
        "assert abs(mi - 1.0) < 1e-9, 'Bell state must be maximally entangled'\n",
        "\n",
        "# iSWAP, exhaustively. This caught a real bug: a version that mapped\n",
        "# |01>->|01> and |11>->i|10> looked plausible but was wrong for two of the\n",
        "# four basis states. Only checking all four exposed it.\n",
        "expected = {0b00: (0b00, 1+0j), 0b01: (0b10, 1j), 0b10: (0b01, 1j), 0b11: (0b11, 1+0j)}\n",
        "for basis, (want_i, want_a) in expected.items():\n",
        "    r = qsim.QuantumRegister(2, seed=0)\n",
        "    r.state = [0j] * 4; r.state[basis] = 1 + 0j\n",
        "    r.iswap(0, 1)\n",
        "    got_i = max(range(4), key=lambda i: abs(r.state[i]))\n",
        "    assert got_i == want_i and abs(r.state[got_i] - want_a) < 1e-12\n",
        "print('iSWAP verified on all four basis states')\n",
    ))

    # ---------------------------------------------------------------- primitives
    cells.append(md(
        "---\n",
        "## 3 · Deriving the creative budget\n",
        "\n",
        "The prompt is hashed to a seed (so the piece is reproducible), and the seed sets the\n",
        "circuit's rotation angles. Measuring the circuit yields the **creative primitives**\n",
        "that drive everything downstream.\n",
        "\n",
        "Note the design constraint this imposes: the seed must enter through **non-diagonal**\n",
        "gates. `RZ` and `CZ` are diagonal, so they add only relative phase, which cancels out\n",
        "of every computational-basis probability — a circuit built that way produces a\n",
        "distribution completely independent of the seed. §5 demonstrates this concretely.\n",
    ))
    cells.append(code(
        "PROMPT = 'the last negative of a dying star, developed in the dark'\n",
        "\n",
        "backend = LocalBackend(num_qubits=9, shots=4096)\n",
        "primitives, provenance = backend.primitives(Pipeline.seed_from_prompt(PROMPT))\n",
        "\n",
        "cp = primitives.to_dict()\n",
        "print('seed          :', cp['seed'])\n",
        "print('circuit       : %d qubits, %d gates, %d shots' % (cp['n_qubits'], cp['gates'], cp['shots']))\n",
        "print('entropy       : %.4f / %d bits' % (cp['entropy_bits'], cp['n_qubits']))\n",
        "print('mean adj. MI  : %.4f bits' % cp['mutual_information_bits'])\n",
        "print('strongest pair: %.4f bits' % cp['max_pair_mutual_information_bits'])\n",
        "print()\n",
        "print('creative choices derived from the measurement:')\n",
        "print('  melody      :', cp['pitches'])\n",
        "print('  scenes      : %d, pacing %s' % (cp['scene_count'], cp['scene_pacing']))\n",
        "print('  timbre      :', cp['timbre'])\n",
        "print('  palette     :', [round(v, 3) for v in film.palette_from_angles(cp['angles'])])\n",
    ))

    # ---------------------------------------------------------------- gates
    cells.append(md(
        "---\n",
        "## 4 · Verifying that the circuit is really doing the work\n",
        "\n",
        "These gates are the ones that matter. If the circuit were a no-op, or if the seed\n",
        "did not reach the measurement statistics, everything downstream would still *look*\n",
        "like a generative artwork while being driven by nothing quantum at all.\n",
        "\n",
        "*(Provenance is checked separately in §7, after the render stages have added their\n",
        "own entries — at this point only the circuit's entry exists.)*\n",
    ))
    cells.append(code(
        "# Physics gates: is the circuit actually doing observable quantum work?\n",
        "gates = checks.check_primitives(cp)\n",
        "print(checks.format_gates(gates))\n",
        "summary = checks.summarise(gates)\n",
        "print()\n",
        "print('%d/%d physics gates passed' % (summary['passed'], summary['total']))\n",
        "assert summary['ok'], 'a physics gate failed'\n",
        "\n",
        "print()\n",
        "print('circuit provenance so far (render stages append in sections 6-7):')\n",
        "for entry in provenance:\n",
        "    print('  %-34s <- %s' % (entry.choice, entry.engine))\n",
    ))

    cells.append(md(
        "### 4b · The seed genuinely reaches the measurement statistics\n",
        "\n",
        "Two runs with different seeds must produce **measurably different** outcome\n",
        "distributions. If they did not, the \"quantum randomness\" would be cosmetic.\n",
    ))
    cells.append(code(
        "dist_a = backend.primitives(cp['seed'])[0]\n",
        "dist_b = backend.primitives(0xDEADBEEF)[0]\n",
        "\n",
        "same = dist_a.probabilities == primitives.probabilities\n",
        "l1 = sum(abs(x - y) for x, y in zip(primitives.probabilities, dist_b.probabilities))\n",
        "print('same seed reproduces the distribution exactly:', same)\n",
        "print('L1 distance between two seeds: %.4f' % l1)\n",
        "assert same and l1 > 0.5\n",
    ))

    # ---------------------------------------------------------------- bug demo
    cells.append(md(
        "---\n",
        "## 5 · The bug that nearly faked this whole project\n",
        "\n",
        "Worth showing explicitly, because it is exactly the failure mode a reviewer should\n",
        "be suspicious of.\n",
        "\n",
        "The first working circuit used `H`, `CNOT`, `iSWAP`, then seed-derived **`RZ`** and\n",
        "**`CZ`**. It looked entangled. It measured as the *uniformly mixed* state: entropy\n",
        "exactly `n` bits, and **every** pairwise mutual information exactly zero.\n",
        "\n",
        "The reason is that `RZ` and `CZ` are both **diagonal** matrices. They add relative\n",
        "phase, which cancels out of `|amplitude|²`. So the outcome distribution was\n",
        "completely independent of the seed — the film would have been driven by integer\n",
        "ordering while *claiming* to be quantum.\n",
        "\n",
        "The cell below reproduces that failure on purpose, then shows the fix.\n",
    ))
    cells.append(code(
        "def broken_circuit(seed, n=6):\n",
        "    \"\"\"The original design: seed enters only through diagonal gates.\"\"\"\n",
        "    reg = qsim.QuantumRegister(n, seed=seed)\n",
        "    rng = np.random.default_rng(seed)\n",
        "    angles = rng.uniform(-np.pi, np.pi, n)\n",
        "    for q in range(n):\n",
        "        reg.hadamard(q)\n",
        "    for q in range(n - 1):\n",
        "        reg.cnot(q, q + 1)\n",
        "    for q, a in enumerate(angles):\n",
        "        reg.rz(q, float(a))      # diagonal: adds phase only\n",
        "    for q in range(0, n - 1, 2):\n",
        "        reg.cz(q, q + 1)         # diagonal: adds phase only\n",
        "    return reg\n",
        "\n",
        "bad_a, bad_b = broken_circuit(1), broken_circuit(2)\n",
        "same_probs = bad_a.probabilities() == bad_b.probabilities()\n",
        "print('broken circuit, two different seeds -> identical distribution:', same_probs)\n",
        "print('  entropy: %.4f / 6 bits  (saturated -> uniform state)'\n",
        "      % qsim.entropy_bits(bad_a.probabilities()))\n",
        "print('  mutual information: %.6f bits  (no entanglement)'\n",
        "      % qsim.mutual_information(bad_a.pair_joint(0, 1)))\n",
        "\n",
        "# The fix: non-diagonal RY rotations, with entangling gates between passes so the\n",
        "# angles propagate into the measurement statistics.\n",
        "good_a = backend.primitives(1)[0]\n",
        "good_b = backend.primitives(2)[0]\n",
        "print()\n",
        "print('fixed circuit, two different seeds -> identical distribution:',\n",
        "      good_a.probabilities == good_b.probabilities)\n",
        "print('  entropy: %.4f / %d bits (not saturated)'\n",
        "      % (good_a.entropy_bits, good_a.n_qubits))\n",
        "print('  mean adjacent mutual information: %.4f bits' % good_a.mutual_information_bits)\n",
    ))

    # ---------------------------------------------------------------- render
    cells.append(md(
        "---\n",
        "## 6 · Rendering the piece\n",
        "\n",
        "The primitives are handed to the renderers. Nothing downstream makes a choice —\n",
        "`synth.py` and `film.py` are pure functions of their inputs, which is what makes the\n",
        "same prompt reproduce the same bytes.\n",
    ))
    cells.append(code(
        "t0 = time.time()\n",
        "pipe = Pipeline(backend=backend, size=384, fps=12, sr=22050, frame_repeats=2)\n",
        "built = pipe.build(PROMPT)\n",
        "paths = pipe.write(built, 'notebook_output')\n",
        "elapsed = time.time() - t0\n",
        "\n",
        "receipt = json.load(open(paths['receipt'], encoding='utf-8'))\n",
        "print('rendered in %.1fs' % elapsed)\n",
        "for key, path in sorted(paths.items()):\n",
        "    print('  %-8s %-28s %8.1f KiB' % (key, os.path.basename(path),\n",
        "                                        os.path.getsize(path) / 1024))\n",
        "print()\n",
        "print('video:', receipt['video'])\n",
        "print('audio: rms=%.4f  spectral centroid=%.0f Hz  notes=%d'\n",
        "      % (receipt['audio']['rms'], receipt['audio']['spectral_centroid_hz'],\n",
        "         len(receipt['audio']['notes'])))\n",
    ))

    cells.append(md("### 6b · The poster frame\n"))
    cells.append(code(
        "if get_ipython() is not None:\n",
        "    from IPython.display import Image, display\n",
        "    display(Image(filename=paths['poster']))\n",
        "else:\n",
        "    print('(not running in a kernel) poster written to', paths['poster'])\n",
    ))

    cells.append(md("### 6c · The score\n"))
    cells.append(code(
        "if get_ipython() is not None:\n",
        "    from IPython.display import Audio, display as display_audio\n",
        "    display_audio(paths['audio'])\n",
        "else:\n",
        "    print('(not running in a kernel) score written to', paths['audio'])\n",
    ))

    cells.append(md(
        "### 6d · The film\n",
        "\n",
        "Encoded as H.264/yuv420p, so it plays inline and in any browser.\n",
    ))
    cells.append(code(
        "# Renders inline in Jupyter. Outside a notebook kernel there is nothing to\n",
        "# display into, so report the artifact rather than failing.\n",
        "if get_ipython() is not None:\n",
        "    from IPython.display import HTML, display as display_html\n",
        "    import base64\n",
        "    data = base64.b64encode(open(paths['video'], 'rb').read()).decode('ascii')\n",
        "    display_html(HTML(\n",
        "        f'<video width=\"480\" controls loop muted playsinline '\n",
        "        f'src=\"data:video/mp4;base64,{data}\"></video>'))\n",
        "else:\n",
        "    print('(not running in a kernel) film written to', paths['video'])\n",
    ))

    # ---------------------------------------------------------------- receipt
    cells.append(md(
        "---\n",
        "## 7 · The provenance receipt\n",
        "\n",
        "Every creative decision, the engine that produced it, and the metrics behind it.\n",
        "This is the artifact that makes the workflow auditable rather than merely asserted.\n",
    ))
    cells.append(code(
        "for entry in receipt['provenance']:\n",
        "    print('%-38s <- %s' % (entry['choice'], entry['engine']))\n",
        "    print('    source: %s' % entry['source'])\n",
        "    for key, value in entry['detail'].items():\n",
        "        print('      %-32s %s' % (key, value))\n",
        "    print()\n",
        "\n",
        "# Now that every stage has recorded its decisions, check the whole chain.\n",
        "prov_gates = checks.check_provenance(receipt['provenance'])\n",
        "print(checks.format_gates(prov_gates))\n",
        "prov_summary = checks.summarise(prov_gates)\n",
        "print()\n",
        "print('%d/%d provenance gates passed' % (prov_summary['passed'], prov_summary['total']))\n",
        "assert prov_summary['ok'], 'a provenance gate failed'\n",
    ))
    cells.append(md("### 7b · Reproducibility\n"))
    cells.append(code(
        "import hashlib\n",
        "\n",
        "def sha256(path):\n",
        "    h = hashlib.sha256()\n",
        "    with open(path, 'rb') as fh:\n",
        "        for chunk in iter(lambda: fh.read(1 << 20), b''):\n",
        "            h.update(chunk)\n",
        "    return h.hexdigest()\n",
        "\n",
        "# Re-render the same prompt into a separate directory and compare bytes.\n",
        "again = Pipeline(backend=backend, size=384, fps=12, sr=22050, frame_repeats=2)\n",
        "again_built = again.build(PROMPT)\n",
        "again_paths = again.write(again_built, 'notebook_output_repeat')\n",
        "\n",
        "for key in ('audio', 'video', 'poster'):\n",
        "    match = sha256(paths[key]) == sha256(again_paths[key])\n",
        "    print('%-8s %s  %s' % (key, sha256(paths[key])[:16], 'identical' if match else 'DIFFERS'))\n",
        "    assert match, f'{key} is not reproducible'\n",
        "print()\n",
        "print('Same prompt, same seed -> byte-identical artifacts.')\n",
    ))

    # ---------------------------------------------------------------- atlas
    cells.append(md(
        "---\n",
        "## 8 · Running the same pipeline on the real Atlas API\n",
        "\n",
        "Everything above ran on the bundled simulator so this notebook is self-contained.\n",
        "The pipeline is written against a backend interface, so the identical composition\n",
        "logic runs on Moth's engines instead — including, when the account carries the\n",
        "`run_quantum` feature, execution on real quantum hardware.\n",
        "\n",
        "`AtlasBackend` raises `FeatureMissing` if a required platform feature is absent, so a\n",
        "missing capability degrades *honestly and visibly* rather than silently falling back\n",
        "to a simulator while still claiming hardware execution.\n",
        "\n",
        "Set `MOTH_API_KEY` (or place the key in `moth/.moth_api_key`) and this cell uses the\n",
        "live API; without a key it reports that and moves on.\n",
    ))
    cells.append(code(
        "def try_atlas(engine_id='coin-toss-v1', mode='emu', shots=1024):\n",
        "    \"\"\"Attempt a real Atlas run; report clearly if unavailable.\"\"\"\n",
        "    try:\n",
        "        from moth_client import MothClient, MothError\n",
        "    except ImportError as exc:\n",
        "        print('moth_client not importable:', exc)\n",
        "        return None\n",
        "    try:\n",
        "        client = MothClient()\n",
        "    except SystemExit:\n",
        "        print('No Atlas API key configured -- skipping the live section.')\n",
        "        print('Set MOTH_API_KEY to enable it.')\n",
        "        return None\n",
        "\n",
        "    me = client.me()\n",
        "    features = me.get('features') or []\n",
        "    print('authenticated as :', me.get('email'))\n",
        "    print('platform features:', features)\n",
        "    print('run_quantum      :', 'run_quantum' in features,\n",
        "          '(enables mode=\"qpu\" on real hardware)')\n",
        "\n",
        "    backend_atlas = AtlasBackend(client, engine_id=engine_id, mode=mode, shots=shots)\n",
        "    try:\n",
        "        prims, prov = backend_atlas.primitives(cp['seed'])\n",
        "    except AtlasBackend.FeatureMissing as exc:\n",
        "        print('feature missing for mode=%r: %s' % (mode, exc))\n",
        "        print('falling back to emulation would be dishonest to claim as QPU; not doing it.')\n",
        "        return None\n",
        "    print()\n",
        "    print('Atlas run OK')\n",
        "    print('  engine  :', engine_id, '| mode:', mode)\n",
        "    print('  outcomes:', prims.bits[:8], '...')\n",
        "    for entry in prov:\n",
        "        print('  provenance:', entry.choice, '<-', entry.engine)\n",
        "        for key, value in entry.detail.items():\n",
        "            print('      %-24s %s' % (key, value))\n",
        "    return prims\n",
        "\n",
        "atlas_primitives = try_atlas(engine_id='coin-toss-v1', mode='emu', shots=512)\n",
    ))
    cells.append(md(
        "### 8b · Where Atlas engines replace local ones\n",
        "\n",
        "The pipeline's creative *decisions* come from a primitive engine. For the **media**\n",
        "rendering stage there are direct Atlas counterparts, and the honest position is that\n",
        "they are the better choice where they exist:\n",
        "\n",
        "| stage | local implementation | Atlas engine |\n",
        "|---|---|---|\n",
        "| image blur / interference | `film.quantum_field` | `blur-v1`, `blur-core-v1` |\n",
        "| image generation | `film.correlation_field` | `tessa-image-v1` |\n",
        "| two-image blend | `film.entangle_frames` | `telablur-v1` |\n",
        "| 3D / shader pass | — | `entanglement-shader-v1` |\n",
        "| reverb / space | `synth.convolve_ir` | `retrocausal-echo-v1` |\n",
        "| melody generation | `qsim.Reservoir` + readout | `qrc-midi-v1`, `qrc-audio-v1` |\n",
        "| MIDI transform | — | `blur-midi-v1` |\n",
        "\n",
        "The local path exists so this notebook runs anywhere with no account and no credits,\n",
        "and so the composition logic is testable in isolation. It is a fallback, not a\n",
        "replacement — the submission's intent is to run the media stages on Atlas.\n",
    ))

    # ---------------------------------------------------------------- close
    cells.append(md(
        "---\n",
        "## 9 · Conclusions and limitations\n",
        "\n",
        "**What is established.** The pipeline runs end to end and produces real media\n",
        "(H.264 film, 16-bit stereo audio, poster, receipt). The circuit is verified to be\n",
        "entangled, un-saturated and seed-dependent, and every creative decision is traceable\n",
        "to a recorded measurement. The output is byte-reproducible from the prompt.\n",
        "\n",
        "**Honest limitations.**\n",
        "\n",
        "- The default path is an **exact classical simulation** of the circuit, not hardware\n",
        "  execution. It is a faithful simulation, and §8 is where hardware enters — but the\n",
        "  numbers above were not produced by a QPU, and this notebook does not imply they were.\n",
        "- A circuit is not *needed* to make these choices; the argument for using one is that\n",
        "  its correlation structure is used as a compositional material, not merely as a\n",
        "  source of randomness.\n",
        "- Entropy and mutual information are computed from the statevector exactly; the\n",
        "  sampled shot counts are used only for ranking outcomes, never for the metrics.\n",
        "\n",
        "**Reproducing everything.**\n",
        "\n",
        "```bash\n",
        "python -B verify_pipeline.py    # 44 pipeline checks, offline\n",
        "python -B test_qsim.py          # 44 quantum-core checks\n",
        "```\n",
    ))

    return {
        "cells": cells,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python",
                           "name": "python3"},
            "language_info": {"name": "python", "version": "3.11"},
            "title": "QUANTUM NEGATIVE — a quantum-native film generator",
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def execute_notebook(nb, verbose: bool = True) -> int:
    """Run every code cell in one shared namespace, capturing outputs.

    This exists because `nbclient` is not installed here and pip cannot reach the
    network. It is deliberately small: notebooks in this repo only ever produce
    stdout and exceptions, and the display calls are guarded behind
    `get_ipython()`, so no rich output has to be synthesised.
    """
    import contextlib
    import io
    import traceback

    import nbformat

    namespace: dict = {"__name__": "__main__", "get_ipython": lambda: None}
    errors = 0
    for index, cell in enumerate(nb.cells):
        if cell.cell_type != "code":
            continue
        cell.outputs = []
        cell.execution_count = index
        # nbformat stores `source` as a list of lines; join before compiling.
        source = cell.source
        if isinstance(source, list):
            source = "".join(source)
        cell.source = source
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                exec(compile(source, f"<cell {index}>", "exec"), namespace)
        except Exception as exc:                       # noqa: BLE001
            errors += 1
            traceback.print_exc(file=out)
            # Record the failure as a real error output so it shows up in the
            # saved notebook instead of being silently swallowed.
            cell.outputs.append(nbformat.v4.new_output(
                "error", ename=type(exc).__name__, evalue=str(exc),
                traceback=traceback.format_exc().splitlines()))
            if verbose:
                print(f"  cell {index} FAILED: {type(exc).__name__}: {exc}")
        text = out.getvalue()
        if text:
            # nbformat.write expects output OBJECTS with attribute access, not
            # plain dicts, or split_lines() raises AttributeError on save.
            cell.outputs.append(nbformat.v4.new_output(
                "stream", name="stdout", text=text))
        if verbose and text:
            head = "\n".join(text.strip().splitlines()[:6])
            print(f"  cell {index:>2} ok   {head[:150]}")
    return errors


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true",
                    help="execute the notebook after writing it")
    args = ap.parse_args()

    import nbformat

    nb = nbformat.from_dict(build())
    nbformat.validate(nb)
    with open(NB_PATH, "w", encoding="utf-8") as fh:
        nbformat.write(nb, fh)
    print(f"wrote {NB_PATH}: {len(nb.cells)} cells "
          f"({sum(1 for c in nb.cells if c.cell_type == 'code')} code)")

    if not args.execute:
        return 0

    print("executing (renders the piece, so this takes a minute) ...")
    errors = execute_notebook(nb)
    with open(NB_PATH, "w", encoding="utf-8") as fh:
        nbformat.write(nb, fh)
    print(f"executed: {errors} cell error(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
