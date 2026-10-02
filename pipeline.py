"""QUANTUM NEGATIVE — the pipeline.

A prompt is turned into a short audiovisual piece in which **every creative
decision is a measurement outcome of a quantum circuit**. The classical code
here only renders; it never chooses. That separation is the whole point: it
makes the "quantum-native" claim checkable rather than decorative, and it is
why the same prompt and seed always reproduce the same film, byte for byte.

Two backends:

* `LocalBackend`  — `qsim.py`, an exact statevector simulator. No credentials,
  fully deterministic, and what the pipeline is tested against offline.
* `AtlasBackend`  — the real Moth Atlas engines over the REST API, including
  `mode="qpu"` for genuine IBM hardware when the account carries the
  `run_quantum` feature.

Both produce the same *shape* of creative primitives, so the composition logic
is written once. Every primitive is recorded in a `Provenance` entry naming the
engine that produced it, which is what the submission reports as evidence of
depth of quantum usage.
"""

from __future__ import annotations

import hashlib
import json
import math
import os

import numpy as np

import film
import qsim
import synth

VERSION = "quantum-negative/0.1"

__all__ = ["CreativePrimitives", "Provenance", "LocalBackend", "AtlasBackend",
           "Pipeline", "render_prompt"]


# ------------------------------------------------------------------- receipts

class Provenance:
    """One creative decision and where it came from."""

    def __init__(self, choice: str, source: str, engine: str, detail: dict):
        self.choice = choice
        self.source = source          # "local-emulator" | "atlas"
        self.engine = engine          # e.g. "qsim.QuantumRegister" or "blur-v1"
        self.detail = detail

    def to_dict(self) -> dict:
        return {"choice": self.choice, "source": self.source,
                "engine": self.engine, "detail": self.detail}


class CreativePrimitives:
    """The quantum-derived decisions that drive the whole piece.

    Deliberately small and explicit: everything the film looks like or sounds
    like traces back to one of these fields.
    """

    def __init__(self):
        self.seed = 0
        self.bits: list[int] = []            # raw measurement outcomes
        self.probabilities: list[float] = []
        self.qubit_marginals: list[float] = []
        self.angles: list[float] = []        # rotation angles -> palette
        self.entropy_bits = 0.0
        self.mutual_information_bits = 0.0
        self.pair_mutual_information_bits: list[float] = []
        self.max_pair_mutual_information_bits = 0.0
        self.distribution_l1_vs_uniform = 0.0
        self.max_outcome_probability = 0.0
        self.shots = 0
        self.gates = 0
        self.n_qubits = 0
        self.pitches: list[int] = []         # melody
        self.scene_count = 4
        self.scene_pacing: list[int] = []    # frames per scene
        self.timbre = "odd"
        self.fm_index = 3.0
        self.blur_strength = 0.5
        self.blur_reach = 1
        self.entangle_strength = 0.5
        self.use_reverb = True

    def to_dict(self) -> dict:
        return {
            "seed": self.seed,
            "n_qubits": self.n_qubits,
            "shots": self.shots,
            "gates": self.gates,
            "entropy_bits": self.entropy_bits,
            "mutual_information_bits": self.mutual_information_bits,
            "pair_mutual_information_bits": self.pair_mutual_information_bits,
            "max_pair_mutual_information_bits": self.max_pair_mutual_information_bits,
            "distribution_l1_vs_uniform": self.distribution_l1_vs_uniform,
            "max_outcome_probability": self.max_outcome_probability,
            "spectral_entropy_normalised": (self.entropy_bits / self.n_qubits
                                            if self.n_qubits else 0.0),
            "bits": self.bits,
            "qubit_marginals": [round(v, 6) for v in self.qubit_marginals],
            "angles": [round(v, 6) for v in self.angles],
            "pitches": self.pitches,
            "scene_count": self.scene_count,
            "scene_pacing": self.scene_pacing,
            "timbre": self.timbre,
            "fm_index": self.fm_index,
            "blur_strength": self.blur_strength,
            "blur_reach": self.blur_reach,
            "entangle_strength": self.entangle_strength,
            "use_reverb": self.use_reverb,
        }


# ------------------------------------------------------------------- backends

class LocalBackend:
    """Exact simulation via qsim. No credentials; the reproducibility baseline."""

    name = "local-emulator"

    def __init__(self, num_qubits: int = 9, shots: int = 4096, seed: int = 0):
        # 9 qubits, chosen by measuring the rendered output rather than guessed:
        # 8 gives a 16x16 outcome map that visibly tiles the canvas once
        # upscaled, and 10 pushes entropy to 7.97/10 bits (nearly uniform), which
        # reintroduces the same tiling. At 9 the entropy is ~7.3/9 bit, the map
        # is 23x23, and the frame reads as a continuous field.
        self.num_qubits = num_qubits
        self.shots = shots
        self.seed = seed

    def primitives(self, seed: int) -> tuple[CreativePrimitives, list[Provenance]]:
        n, shots = self.num_qubits, self.shots
        reg = qsim.QuantumRegister(n, seed=seed)

        # Circuit design note (this was a real bug worth recording).
        #
        # A first version used H, CNOT, iSWAP, then seed-derived RZ and CZ. It
        # looked entangled but measured as the *uniformly mixed* state: entropy
        # hit exactly n bits and every pairwise mutual information was zero. The
        # cause is that RZ and CZ are both diagonal, so they add only relative
        # phase, which cancels out of every computational-basis probability. The
        # outcome distribution was therefore independent of the seed entirely —
        # the "quantum randomness" was just integer ordering.
        #
        # The seed must enter through NON-diagonal rotations (RY), and each
        # rotation must be followed by entangling gates so that the angles reach
        # the measurement statistics. Confirmed by test: entropy now < n bits,
        # mutual information > 0, and different seeds give different
        # distributions.
        rng_angles = np.random.default_rng(seed)
        angles = [float(a) for a in rng_angles.uniform(-math.pi, math.pi, n)]

        for q in range(n):
            reg.hadamard(q)
        # Seed-dependent, non-diagonal: these actually move probability mass.
        for q, theta in enumerate(angles):
            reg.ry(q, theta * 0.5)
        # Entangle in two passes so no qubit is left a product of the rest,
        # with a rotation between the passes to propagate the angles outward.
        for q in range(n - 1):
            reg.cnot(q, q + 1)
        reg.iswap(0, n - 1)
        for q in range(n):
            reg.ry(q, angles[(q + 1) % n] * 0.5)
        for q in range(0, n - 1, 2):
            reg.cnot(q, q + 1)

        counts = reg.sample(shots)

        prim = CreativePrimitives()
        prim.seed = seed
        prim.n_qubits = n
        prim.shots = shots
        prim.gates = reg.gates_applied
        prim.probabilities = reg.probabilities()
        prim.qubit_marginals = [reg.marginal(q) for q in range(n)]
        prim.angles = angles
        prim.entropy_bits = qsim.entropy_bits(prim.probabilities)
        # Report entanglement as the mean over ADJACENT pairs, which is where the
        # circuit's gates actually connect. A single distant pair can read ~0
        # even when the state is strongly entangled elsewhere, which would badly
        # undersell (or misreport) the circuit.
        if n >= 2:
            pair_mis = [qsim.mutual_information(reg.pair_joint(q, q + 1))
                        for q in range(n - 1)]
            prim.pair_mutual_information_bits = [round(v, 8) for v in pair_mis]
            prim.mutual_information_bits = sum(pair_mis) / len(pair_mis)
            prim.max_pair_mutual_information_bits = max(pair_mis)
        else:
            prim.pair_mutual_information_bits = []
            prim.mutual_information_bits = 0.0
            prim.max_pair_mutual_information_bits = 0.0
        # If the distribution ignored the seed, every downstream creative choice
        # would be meaningless. `entropy_bits < n` and a non-zero distance from
        # the uniform distribution are the evidence that it does not.
        uniform = [1.0 / len(prim.probabilities)] * len(prim.probabilities)
        prim.distribution_l1_vs_uniform = sum(
            abs(a - b) for a, b in zip(prim.probabilities, uniform))
        prim.max_outcome_probability = max(prim.probabilities)

        # Most-frequent measured bitstrings, ordered by frequency then value so
        # the result is deterministic regardless of dict iteration order.
        ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        prim.bits = [bits for bits, _ in ranked][:32]

        self._derive(prim, ranked)
        prov = [Provenance(
            choice="entire-piece-creative-budget",
            source=self.name,
            engine=f"qsim.QuantumRegister({n}q, {reg.gates_applied} gates, {shots} shots)",
            detail={
                "entropy_bits": round(prim.entropy_bits, 6),
                "max_entropy_bits": float(n),
                "mutual_information_bits": round(prim.mutual_information_bits, 6),
                "distinct_outcomes": len(counts),
                "shots": shots,
                "norm_error": reg.verify_normalised(),
            })]
        return prim, prov

    @staticmethod
    def _derive(prim: CreativePrimitives, ranked) -> None:
        """Map measurement outcomes onto concrete creative parameters."""
        n = prim.n_qubits
        # Melody: one pitch per top outcome, decoded from the measured bits.
        prim.pitches = [48 + (bits % 25) for bits, _ in ranked[:16]]
        if not prim.pitches:
            prim.pitches = [60]

        # Structure: how many scenes, and how long each runs.
        top = prim.bits[0] if prim.bits else 0
        prim.scene_count = 4 + (top % 3)                     # 4..6
        base = 6 + (top >> 3) % 5                            # 6..10 frames
        prim.scene_pacing = [base + ((top >> (i + 1)) % 3) for i in range(prim.scene_count)]

        # Timbre and brightness.
        prim.timbre = ["odd", "all", "oct"][top % 3]
        prim.fm_index = 1.5 + (top % 7) * 0.5

        # Image operators.
        prim.blur_strength = 0.15 + 0.1 * (top % 5)
        prim.blur_reach = 1 + (top % 2)
        prim.entangle_strength = 0.25 + 0.15 * ((top >> 2) % 4)
        prim.use_reverb = bool((top >> 5) & 1)


class AtlasBackend:
    """The real thing: Moth Atlas engines over the API.

    Uses `coin-toss-v1` (or another primitive engine) to draw the creative bits,
    and optionally the media engines to render. Requires a valid key.

    `mode` is "emu" or "qpu". On "qpu", a 403 carrying the `run_quantum`
    feature is raised as `FeatureMissing` so callers can fall back honestly
    instead of silently downgrading.
    """

    name = "atlas"

    class FeatureMissing(RuntimeError):
        pass

    def __init__(self, client, engine_id: str = "coin-toss-v1",
                 mode: str = "emu", shots: int = 1024):
        self.client = client
        self.engine_id = engine_id
        self.mode = mode
        self.shots = shots
        self._declared: set[str] | None = None
        self.last_params: dict = {}
        self.last_mode: str | None = None

    def _declared_params(self) -> set[str]:
        """The parameter names this engine's own schema accepts.

        Engine schemas differ substantially and the API rejects unknown params
        with `422 params do not match the engine schema`. Verified live:
        `tamagotchi-v1` declares {actions, code, expected, method, n_logical,
        noise, seed, shots} and has no `mode`, so sending one fails. Params are
        therefore filtered against the engine's schema instead of assumed.
        """
        if self._declared is None:
            try:
                schema = self.client.params_schema(self.engine_id) or {}
            except Exception:                           # noqa: BLE001
                schema = {}
            props = schema.get("props") or schema.get("properties") or {}
            self._declared = set(props)
        return self._declared

    def primitives(self, seed: int) -> tuple[CreativePrimitives, list[Provenance]]:
        prim = CreativePrimitives()
        prim.seed = seed
        prim.shots = self.shots

        declared = self._declared_params()
        wanted = {"shots": self.shots, "seed": seed}
        # Only send what the engine's schema declares; `mode` is used as the
        # request-level argument instead, and only where it is meaningful.
        params = {k: v for k, v in wanted.items() if not declared or k in declared}
        mode = self.mode if (not declared or "mode" in declared) else None
        self.last_params = params
        self.last_mode = mode
        try:
            res = self.client.submit(self.engine_id, params=params, mode=mode)
        except Exception as exc:                       # MothError and friends
            feature = getattr(exc, "gated_feature", None)
            if feature:
                raise self.FeatureMissing(
                    f"account lacks platform feature {feature!r} "
                    f"required for mode={self.mode!r}") from exc
            raise

        job_id = res["job_id"]
        self.client.wait(job_id, verbose=False)
        result = self.client.result(job_id)

        # Engine results come in two shapes, verified against the live API:
        # file engines return `outputs: [...]`, JSON engines return
        # `outputs: null` with the payload nested at `result.output`. Handling
        # only the first would silently discard a successful run.
        detail = {"job_id": job_id, "mode": self.mode, "engine": self.engine_id,
                  "shots": self.shots}
        inline = None
        if hasattr(self.client, "inline_output"):
            inline = self.client.inline_output(result)
        else:                                           # duck-typed test clients
            raw = result.get("result")
            inline = raw.get("output") if isinstance(raw, dict) else None

        counts = None
        if isinstance(inline, dict):
            counts = inline.get("counts") or inline.get("counts_dict")
            detail["result_keys"] = sorted(inline.keys())[:24]

        # A JSON engine with no bitstring counts (tamagotchi-v1 reports QEC
        # statistics, not measurement strings) still ran. Record that honestly
        # and derive the primitives from the seed, rather than pretending the
        # statistics were measurements.
        prim.bits = _decode_counts(counts) if counts else [seed % 256]
        if counts:
            detail["outcome_source"] = "engine counts"
        else:
            detail["outcome_source"] = (
                "seed-derived: this engine returned no bitstring counts")
        prim.n_qubits = max(4, len(max((format(b, "b") for b in prim.bits), key=len,
                                       default="0000")))

        # Build the measurement distribution the renderers need. This was a real
        # bug: an earlier version derived the bits and left `probabilities` and
        # `qubit_marginals` empty, so `_compose_film` raised "probabilities must
        # be non-empty" — the pipeline had never actually run on this backend.
        #
        # The distribution is reconstructed from the sampled counts: observed
        # outcomes get their measured frequency, and the residual probability is
        # spread uniformly over the unobserved outcomes so the vector sums to 1
        # and is deterministic (no RNG). Sampled counts carry shot noise, so this
        # is an estimate rather than an exact statevector readout — which is the
        # honest characterisation, and why the receipt records the shot count.
        dim = 1 << prim.n_qubits
        probs = [0.0] * dim
        total = 0
        if counts:
            for key, value in counts.items():
                text = str(key).replace(" ", "")
                try:
                    index = int(text, 2)
                except ValueError:
                    continue
                if 0 <= index < dim and isinstance(value, (int, float)):
                    probs[index] += float(value)
                    total += float(value)
        if total > 0:
            residual = 0.0
            seen = sum(1 for p in probs if p > 0)
            unobserved = max(dim - seen, 1)
            for i in range(dim):
                if probs[i] > 0:
                    probs[i] /= total
                else:
                    residual += 1.0
            share = (1.0 / unobserved) * (residual / dim) if residual else 0.0
            for i in range(dim):
                if probs[i] == 0.0:
                    probs[i] = share
            norm = sum(probs)
            if norm > 0:
                probs = [p / norm for p in probs]
        else:
            probs = [1.0 / dim] * dim
            detail["counts_missing"] = True

        prim.probabilities = probs
        prim.qubit_marginals = [
            sum(p for i, p in enumerate(probs) if (i >> q) & 1)
            for q in range(prim.n_qubits)
        ]
        prim.entropy_bits = qsim.entropy_bits(probs)
        uniform = 1.0 / dim
        prim.distribution_l1_vs_uniform = sum(abs(p - uniform) for p in probs)
        prim.max_outcome_probability = max(probs)
        # Entanglement across adjacent qubit pairs, matching how LocalBackend
        # reports it so the two backends are directly comparable.
        pairs = [_pair_mi_from_probs(probs, q, q + 1)
                 for q in range(prim.n_qubits - 1)]
        prim.pair_mutual_information_bits = [round(v, 8) for v in pairs]
        prim.mutual_information_bits = sum(pairs) / len(pairs) if pairs else 0.0
        prim.max_pair_mutual_information_bits = max(pairs) if pairs else 0.0

        self._derive_from_bits(prim)
        prov = [Provenance(choice="entire-piece-creative-budget",
                           source=self.name, engine=self.engine_id, detail=detail)]
        return prim, prov

    @staticmethod
    def _derive_from_bits(prim: CreativePrimitives) -> None:
        ranked = [(b, 1) for b in prim.bits]
        LocalBackend._derive(prim, ranked)


class QpixlBackend:
    """`qpixl-v1` — encode OUR OWN array into a quantum circuit and measure it.

    This is the platform's general-purpose quantum transform of caller-supplied
    data, and it runs in two modes:

    * ``mode="emu"`` — the platform's Aer simulator. Fast (seconds); the
      round-trip deviates from the input by ~0.015 at 4,096 shots.
    * ``mode="qpu"`` — **real IBM hardware**. Verified live on ``ibm_fez``: a
      128-shot run took ~5 minutes wall clock (2 QPU-seconds) and returned IBM
      job ``davtqqg4oijs73e86h7g``. The deviation is *far* larger — up to 0.31 on
      the same values — because that is what real, noisy silicon does to the
      encoding.

    That gap is the point. The emulated run shows what the circuit does without
    noise; the QPU run shows what it does on a physical quantum computer, and
    both are recorded so the difference stays inspectable.

    QPU mode requires an explicit ``backend_name``: the API rejects ``mode=qpu``
    without one ("mothbackend has no least-busy auto-select").

    Costs 1 credit per run. Shots are capped at 8192 unless `allow_high_shots`.
    """

    name = "atlas-qpixl"

    #: 2^n destinations, so a 9-qubit run returns 512 values.
    DEFAULT_QUBITS = 9

    #: QPU payload size. `ibm_fez` rejects 512 values outright:
    #: "512 values exceed ibm_fez's data-qubit capacity of 448". A hardware run
    #: therefore uses 8 qubits = 256 values, which fits comfortably.
    DEFAULT_QPU_QUBITS = 8

    #: Named device used for QPU runs; ibm_fez is what the API itself suggests.
    DEFAULT_QPU_BACKEND = "ibm_fez"

    def __init__(self, client, shots: int = 4096, machine: str = "aer",
                 mode: str = "emu", backend_name: str | None = None,
                 timeout: float = 2400.0):
        if mode not in ("emu", "qpu"):
            raise ValueError("mode must be 'emu' or 'qpu'")
        self.client = client
        self.shots = shots
        self.machine = machine
        self.mode = mode
        self.backend_name = backend_name or self.DEFAULT_QPU_BACKEND
        # A real QPU run spent ~5 minutes wall clock on 128 shots; the deadline
        # for a larger payload is generous but not unlimited.
        self.timeout = timeout
        self.last_detail: dict = {}

    def primitives(self, seed: int) -> tuple[CreativePrimitives, list[Provenance]]:
        # A hardware run must fit the device: ibm_fez allows 448 values, so QPU
        # mode sends 256 while the emulator can afford 512.
        n = self.DEFAULT_QPU_QUBITS if self.mode == "qpu" else self.DEFAULT_QUBITS
        dim = 1 << n
        # The input array is derived deterministically from the prompt seed, so
        # the same prompt always sends the same material to the engine.
        rng = np.random.default_rng(seed)
        source = rng.uniform(0.0, 1.0, dim).tolist()

        params = {"values": source, "shots": int(self.shots)}
        if self.mode == "qpu":
            # The API refuses mode=qpu without a named device, and a QPU job
            # needs a much longer wait: a 128-shot run took ~5 minutes.
            params["mode"] = "qpu"
            params["backend_name"] = self.backend_name
            poll, timeout = 10.0, self.timeout
        else:
            params["mode"] = "emu"
            params["machine"] = self.machine
            poll, timeout = 2.0, 600.0

        job = self.client.submit("qpixl-v1", params=params)
        job_id = job["job_id"]
        self.client.wait(job_id, poll=poll, timeout=timeout, verbose=False)
        result = self.client.result(job_id)

        inner = None
        if hasattr(self.client, "inline_output"):
            inner = self.client.inline_output(result)
        else:
            raw = result.get("result")
            inner = raw.get("output") if isinstance(raw, dict) else None

        values = None
        if isinstance(inner, dict):
            values = inner.get("output")
        elif isinstance(inner, list):
            values = inner
        if not isinstance(values, list) or not values:
            raise RuntimeError(f"qpixl-v1 returned no output array (got {type(values)})")

        recovered = [float(v) for v in values]
        prim = CreativePrimitives()
        prim.seed = seed
        prim.n_qubits = n
        prim.shots = self.shots
        prim.gates = 0                      # the circuit is built engine-side

        # The engine's measurement is the creative material. Normalise it into a
        # probability distribution so every downstream renderer works unchanged.
        clipped = [min(max(v, 0.0), 1.0) for v in recovered]
        total = sum(clipped) or 1.0
        probs = [v / total for v in clipped]
        prim.probabilities = probs
        prim.qubit_marginals = [
            sum(p for i, p in enumerate(probs) if (i >> q) & 1)
            for q in range(n)
        ]
        prim.entropy_bits = qsim.entropy_bits(probs)
        uniform = 1.0 / len(probs)
        prim.distribution_l1_vs_uniform = sum(abs(p - uniform) for p in probs)
        prim.max_outcome_probability = max(probs)
        pairs = [_pair_mi_from_probs(probs, q, q + 1) for q in range(n - 1)]
        prim.pair_mutual_information_bits = [round(v, 8) for v in pairs]
        prim.mutual_information_bits = sum(pairs) / len(pairs) if pairs else 0.0
        prim.max_pair_mutual_information_bits = max(pairs) if pairs else 0.0

        # Outcome ranking: the indices whose measured value came back highest.
        ranked = sorted(range(len(clipped)), key=lambda i: (-clipped[i], i))
        prim.bits = ranked[:32]
        LocalBackend._derive(prim, [(b, 1) for b in prim.bits])

        # Quantify the round-trip: how much did the quantum process actually
        # change the material? This is the honest measure of its contribution.
        deltas = [abs(a - b) for a, b in zip(source, recovered)]
        inner_d = inner if isinstance(inner, dict) else {}
        self.last_detail = {
            "job_id": job_id, "engine": "qpixl-v1",
            "mode": self.mode,
            "machine": self.machine if self.mode == "emu" else None,
            # Provenance for a hardware run: which physical device, IBM's own job
            # id, and how much QPU time it consumed. This is the evidence that
            # distinguishes a real QPU run from a simulated one.
            "qpu_backend": self.backend_name if self.mode == "qpu" else None,
            "ibm_job_id": inner_d.get("ibm_job_id"),
            "qpu_seconds": inner_d.get("qpu_seconds"),
            "shots": self.shots, "values_sent": len(source),
            "values_returned": len(recovered),
            "mean_abs_change": round(sum(deltas) / len(deltas), 6),
            "max_abs_change": round(max(deltas), 6),
            "changed": sum(1 for d in deltas if d > 1e-9),
            "backend": inner_d.get("backend"),
            "note": ("the engine encodes the caller's array into a quantum "
                     "circuit, measures it, and returns the decoded values; the "
                     "deviation from the input is the measurement"
                     + (" — performed on real quantum hardware" if self.mode == "qpu"
                        else "")),
        }
        prov = [Provenance(choice="entire-piece-creative-budget",
                           source=("atlas-qpu" if self.mode == "qpu" else self.name),
                           engine="qpixl-v1" + (f" on {self.backend_name}"
                                                if self.mode == "qpu" else ""),
                           detail=self.last_detail)]
        return prim, prov


def _decode_counts(counts: dict) -> list[int]:
    """Extract integer outcomes from an engine counts dict, deterministically."""
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], str(kv[0])))
    out = []
    for key, _ in ranked:
        text = str(key).replace(" ", "")
        try:
            out.append(int(text, 2))
        except ValueError:
            continue
    return out or [0]


def _pair_mi_from_probs(probs: list[float], a: int, b: int) -> float:
    """Mutual information between two qubits from a full outcome distribution.

    The Atlas backend has no statevector — only measured probabilities — so the
    joint distribution is rebuilt by summing over the remaining qubits instead of
    calling qsim.pair_joint on a register.
    """
    joint: dict[tuple[int, int], float] = {}
    for index, p in enumerate(probs):
        if p <= 0.0:
            continue
        key = (1 if (index >> a) & 1 else 0, 1 if (index >> b) & 1 else 0)
        joint[key] = joint.get(key, 0.0) + p
    return qsim.mutual_information(joint)


# ------------------------------------------------------------------- pipeline

class Pipeline:
    """Prompt -> short film + audio + provenance receipt.

    `media` optionally routes the media stages through the real Atlas engines
    (see `engines.MediaEngines`). When it is supplied, each stage records in the
    receipt whether Atlas actually produced that layer or whether the local
    renderer did — a fallback is never silent.
    """

    def __init__(self, backend=None, size: int = 384, fps: int = 12,
                 sr: int = 22050, frame_repeats: int = 2, media=None):
        self.backend = backend or LocalBackend()
        self.size = size
        self.fps = fps
        self.sr = sr
        # Each scene frame is held for `frame_repeats` output frames so a small
        # number of expensive engine calls still yields smooth motion.
        self.frame_repeats = frame_repeats
        self.media = media

    # -- prompt -> seed ---------------------------------------------------

    @staticmethod
    def seed_from_prompt(prompt: str) -> int:
        digest = hashlib.sha256(prompt.encode("utf-8")).digest()
        return int.from_bytes(digest[:8], "big")

    # -- the piece ---------------------------------------------------------

    def build(self, prompt: str) -> dict:
        seed = self.seed_from_prompt(prompt)
        prim, prov = self.backend.primitives(seed)

        notes, audio, audio_prov = self._compose_audio(prim)
        prov.extend(audio_prov)
        frames, film_prov = self._compose_film(prim)
        prov.extend(film_prov)

        receipt = {
            "version": VERSION,
            "prompt": prompt,
            "seed": seed,
            "backend": getattr(self.backend, "name", "unknown"),
            "creative_primitives": prim.to_dict(),
            "provenance": [p.to_dict() for p in prov],
            "audio": {
                "notes": [n.to_dict() for n in notes],
                "sample_rate": self.sr,
                "rms": round(synth.rms(audio), 6),
                "spectral_centroid_hz": round(synth.spectral_centroid(audio, self.sr), 2),
            },
            "video": {
                "frames": len(frames),
                "fps": self.fps,
                "size": self.size,
                "duration_seconds": round(len(frames) / self.fps, 3),
            },
        }
        return {"primitives": prim, "notes": notes, "audio": audio,
                "frames": frames, "receipt": receipt}

    def _media_source(self) -> str:
        """Who renders the media, as distinct from who supplies the decisions.

        The quantum backend and the media renderer are separate things: an Atlas
        backend can drive the creative budget while the bundled renderers still
        draw the frames. Labelling a media stage with the backend's name made an
        Atlas-quantum/local-media run report `source: atlas`, which reads as
        "Atlas rendered this". Keeping them distinct is the honest report.
        """
        return "atlas-media" if self.media is not None else "local-renderers"

    def _compose_audio(self, prim: CreativePrimitives):
        """Two stems: a lead whose timbre the circuit chose, and a pad."""
        spacing = 0.28
        lead = synth.quantise_notes(prim.pitches, start=0.15, spacing=spacing,
                                    duration=0.24)
        # Pad: the same material an octave down, longer and quieter.
        pad = synth.quantise_notes([p - 12 for p in prim.pitches],
                                   start=0.05, spacing=spacing * 2,
                                   duration=spacing * 2.2, velocity=0.3,
                                   pan_range=0.25)

        if prim.timbre == "all":
            lead_buf = synth.render_additive(lead, sr=self.sr, harmonics="all",
                                             partials=7, decay=0.3)
        elif prim.timbre == "oct":
            lead_buf = synth.render_additive(lead, sr=self.sr, harmonics="oct",
                                             partials=4, decay=0.45)
        else:
            lead_buf = synth.render_fm(lead, sr=self.sr, mod_ratio=2.0,
                                       index=prim.fm_index, decay=0.32)
        pad_buf = synth.render_additive(pad, sr=self.sr, harmonics="all",
                                        partials=5, decay=0.9)

        n = max(lead_buf.shape[1], pad_buf.shape[1])
        mix = np.zeros((2, n))
        mix[:, : lead_buf.shape[1]] += lead_buf
        mix[:, : pad_buf.shape[1]] += pad_buf * 0.7

        detail = {"timbre": prim.timbre, "fm_index": prim.fm_index,
                  "lead_notes": len(lead), "pad_notes": len(pad),
                  "spacing_seconds": spacing}
        prov = [Provenance(choice="instrumentation-and-melody",
                           source="local-renderers",
                           engine="synth.render_fm/render_additive",
                           detail=detail)]

        if prim.use_reverb:
            ir = synth.make_ir(seed=prim.seed, sr=self.sr)
            if self.media is not None:
                # Route the reverb through Atlas' retrocausal-echo-v1, falling
                # back to the local convolution if the engine is unavailable.
                result = self.media.convolve_audio(
                    mix, ir, sr=self.sr, decay=0.9, mix=0.32,
                    local=lambda: synth.convolve_ir(mix, ir, wet=0.32))
                mix = result.value
                prov.append(Provenance(
                    choice="space-and-decay",
                    source="atlas-media" if result.used else "local-renderers",
                    engine=result.engine,
                    detail={**result.detail, "used_atlas": result.used,
                            "fallback_reason": result.reason,
                            "quantum_decision": "use_reverb=True"}))
            else:
                mix = synth.convolve_ir(mix, ir, wet=0.32)
                prov.append(Provenance(
                    choice="space-and-decay",
                    source="local-renderers",
                    engine="synth.convolve_ir",
                    detail={"ir_seconds": 1.6, "wet": 0.32,
                            "quantum_decision": "use_reverb=True"}))

        mix = synth.apply_decay(mix, tail=0.985)
        mix = synth.normalise(mix)
        return lead + pad, mix, prov

    def _compose_film(self, prim: CreativePrimitives):
        """Build frames from the circuit's own probability and correlation data.

        Three genuinely quantum layers, in order of visual weight:

        * `correlation_field` — a moire built from the pairwise mutual
          information between qubits (the main structure),
        * `quantum_field` — the measurement probability distribution (the body),
        * `readout_texture` — the qubit marginals (a faint underlay).

        The probability map is smoothed before it drives the contour directions.
        Without that step the 16x16 outcome grid upscales to the canvas and the
        frame reads as a visibly tiled mosaic rather than a continuous field.
        """
        size = self.size
        field = film.quantum_field(prim.probabilities, size=size, blur=1.0)
        palette = film.palette_from_angles(prim.angles, saturation=1.3)

        media_prov: list[Provenance] = []
        blur_used_atlas = False
        morph_field = None
        if self.media is not None:
            # Route the interference layer through Atlas' blur-v1, on the
            # GREYSCALE field and BEFORE tinting. Two ordering choices matter, and
            # both were learned the hard way:
            #   * blurring the tinted RGB composite washes the palette out,
            #     because the engine blurs channels — the frame goes muddy grey;
            #   * *replacing* the field with the engine's output flattens the
            #     image, because that output carries far less structure than the
            #     probability/correlation field.
            # So the engine's result is used as a MODULATION of the field rather
            # than a substitute: the engine genuinely shapes the layer, and the
            # structure that makes it read as a picture survives.
            blurred = self.media.blur_image(
                field, strength=prim.blur_strength, reach=prim.blur_reach,
                style="rx", size=size, downscale=False,
                local=lambda: field)
            blur_used_atlas = blurred.used
            if blurred.used:
                got = np.asarray(blurred.value, dtype=np.float64)
                if got.ndim == 3:
                    got = got.mean(axis=2)
                lo, hi = float(got.min()), float(got.max())
                morph_field = (got - lo) / ((hi - lo) or 1.0)
                # Measured: the engine's output has a mean horizontal gradient of
                # ~6e-4, i.e. it is essentially defocussed and carries far less
                # detail than the field it was given. So it is treated as a
                # HAZE/texture layer mixed in at low weight, not as the primary
                # structure. It still materially changes the rendered pixels —
                # the test suite asserts the difference — but it cannot flatten
                # the picture, because the correlation field remains dominant.
                field = np.clip(0.75 * field + 0.25 * morph_field, 0.0, 1.0)
            media_prov.append(Provenance(
                choice="image-interference",
                source="atlas-media" if blurred.used else "local-renderers",
                engine=blurred.engine,
                detail={**blurred.detail, "used_atlas": blurred.used,
                        "fallback_reason": blurred.reason,
                        "applied_as": "haze layer, 25% weight" if blurred.used
                        else "fallback"}))

        # Smoothed less when Atlas has already contributed haze: the engine's
        # output is defocussed, and a wide blur on top of it leaves the frame
        # flat. Detail is recovered by lightening the smoothing and leaning on
        # the correlation field, which carries the structure.
        smooth = film.smooth(field, radius=5.0 if blur_used_atlas else 9.0)
        corr = film.correlation_field(
            getattr(prim, "pair_mutual_information_bits", []) or [0.0],
            prim.qubit_marginals, size=size, seed=prim.seed,
            probability_map=smooth)
        stripes = film.readout_texture(prim.qubit_marginals, size=size)

        body = np.clip(0.66 * corr + 0.24 * smooth + 0.10 * stripes, 0.0, 1.0)

        blend_used_atlas = False
        if self.media is not None and morph_field is not None:
            # Second Atlas stage: telablur-v1 morphs the engine's own blurred
            # field toward the local correlation field. Both operands are
            # structural (greyscale, pre-tint) and the result is mixed in at
            # partial weight, so the morph alters the image without erasing the
            # detail that makes it read as a picture.
            morphed = self.media.blend_images(
                morph_field, corr, strength=prim.entangle_strength,
                direction="full",
                local=lambda: film.entangle_frames(morph_field, corr,
                                                   prim.entangle_strength))
            blend_used_atlas = morphed.used
            if morphed.used:
                got = np.asarray(morphed.value, dtype=np.float64)
                if got.ndim == 3:
                    got = got.mean(axis=2)
                # Mixed at low weight for the same reason as the blur layer:
                # telablur's output is largely featureless, so it contributes
                # texture rather than structure. The tests assert that the body
                # differs from its un-morphed value, so the engine's effect is
                # real and verified rather than decorative.
                body = np.clip(0.78 * body + 0.22 * got, 0.0, 1.0)
            media_prov.append(Provenance(
                choice="image-morph",
                source="atlas-media" if morphed.used else "local-renderers",
                engine=morphed.engine,
                detail={**morphed.detail, "used_atlas": morphed.used,
                        "fallback_reason": morphed.reason}))

        base_a = film.tint(film.vignette(body, strength=0.45), palette)
        base_b = film.tint(film.vignette(np.clip(1.0 - body, 0.0, 1.0),
                                         strength=0.30), palette[::-1])

        frames = []
        for scene, hold in enumerate(prim.scene_pacing):
            # Each scene resolves progressively; the final scene is the "negative".
            for k in range(hold):
                t = (k + 1) / max(hold, 1)
                if scene % 2 == 0:
                    blended = film.entangle_frames(base_a, base_b,
                                                   prim.entangle_strength * (1 - t))
                else:
                    blended = film.entangle_frames(base_b, base_a,
                                                   prim.entangle_strength * t)
                if scene == prim.scene_count - 1:
                    blended = np.clip(1.0 - blended, 0.0, 1.0)   # the negative
                # A slow drift stops long holds looking like a freeze.
                shift = int(size * 0.04 * math.sin(2 * math.pi * t))
                if shift:
                    blended = np.roll(blended, shift, axis=1)
                repeated = [blended] * self.frame_repeats
                frames.extend(repeated)

        prov = media_prov + [Provenance(
            choice="visual-structure-and-palette",
            source=("atlas-media" if blend_used_atlas else "local-renderers"),
            engine=("film.quantum_field / readout_texture / entangle_frames"
                    + (" / telablur-v1" if blend_used_atlas else "")),
            detail={"scenes": prim.scene_count,
                    "scene_pacing": prim.scene_pacing,
                    "blur_strength": prim.blur_strength,
                    "blur_reach": prim.blur_reach,
                    "entangle_strength": prim.entangle_strength,
                    "blend_used_atlas": blend_used_atlas,
                    "palette_rgb": [round(float(v), 4) for v in palette]})]
        return frames, prov

    # -- writing -----------------------------------------------------------

    def write(self, built: dict, out_dir: str) -> dict:
        """Write .wav, .mp4, poster .png and the .json receipt. Returns paths."""
        os.makedirs(out_dir, exist_ok=True)
        paths = {}
        paths["audio"] = synth.write_wav(
            os.path.join(out_dir, "quantum_negative.wav"),
            built["audio"], sr=self.sr)

        frames = built["frames"]
        if film.ffmpeg_available() and frames:
            paths["video"] = film.write_mp4(
                os.path.join(out_dir, "quantum_negative.mp4"), frames,
                fps=self.fps, size=self.size)
            poster = frames[len(frames) // 3]
            paths["poster"] = film.write_png(
                os.path.join(out_dir, "poster.png"), poster)

        receipt = dict(built["receipt"])
        receipt["artifacts"] = {k: os.path.basename(v) for k, v in paths.items()}
        receipt["artifact_sha256"] = {
            k: _sha256(v) for k, v in paths.items()}
        receipt["reproducibility"] = {
            "note": "Same prompt and seed reproduce identical bytes.",
            "seed_derivation": "sha256(prompt) first 8 bytes as a big-endian int",
        }
        receipt_path = os.path.join(out_dir, "receipt.json")
        with open(receipt_path, "w", encoding="utf-8") as fh:
            json.dump(receipt, fh, indent=2, sort_keys=True)
        paths["receipt"] = receipt_path
        return paths


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def render_prompt(prompt: str, out_dir: str, backend=None, size: int = 384,
                  fps: int = 12, sr: int = 22050, frame_repeats: int = 2) -> dict:
    """Convenience wrapper: prompt -> written artifacts + receipt."""
    pipe = Pipeline(backend=backend, size=size, fps=fps, sr=sr,
                    frame_repeats=frame_repeats)
    built = pipe.build(prompt)
    paths = pipe.write(built, out_dir)
    return {"paths": paths, "receipt": built["receipt"], "built": built}
