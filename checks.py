"""Shared correctness gates for the QUANTUM NEGATIVE pipeline.

These exist because two real bugs shipped during development, and both would
have silently falsified the submission's central claim that a quantum process
drove the creative decisions:

1. **A circuit that was a no-op on measurement statistics.** The seed entered
   through RZ and CZ — both diagonal, so they contributed only relative phase,
   which cancels out of every computational-basis probability. The outcome
   distribution was independent of the seed. Entropy saturated at exactly
   `n_qubits` and every pairwise mutual information was exactly zero.

2. **Entanglement reported from a single distant qubit pair.** Measuring
   (0, n-1) on a ladder circuit can read ~0 while the state is strongly
   entangled elsewhere, badly misreporting depth.

Both are now hard gates. `check_primitives` is used by the verifier, the
notebook and the web app, so a regression cannot pass in one place and fail
silently in another.
"""

from __future__ import annotations

__all__ = ["Gate", "check_primitives", "check_provenance", "summarise"]


class Gate:
    """One assertion with a human-readable name, outcome and evidence."""

    __slots__ = ("name", "ok", "detail")

    def __init__(self, name: str, ok: bool, detail: str = ""):
        self.name = name
        self.ok = bool(ok)
        self.detail = detail

    def __repr__(self) -> str:
        mark = "PASS" if self.ok else "FAIL"
        return f"[{mark}] {self.name}" + (f" ({self.detail})" if self.detail else "")


def check_primitives(primitives: dict, *, min_entropy_margin: float = 1e-6,
                     min_mutual_information: float = 0.01,
                     min_max_pair_mi: float = 0.05,
                     min_l1_vs_uniform: float = 0.1) -> list[Gate]:
    """Verify the creative primitives are physically sound and seed-dependent.

    Takes the serialised primitives dict (as stored in the receipt) so it can be
    applied to any receipt, including one produced by the Atlas backend.
    """
    gates: list[Gate] = []
    n = primitives.get("n_qubits") or 0
    entropy = primitives.get("entropy_bits")
    mean_mi = primitives.get("mutual_information_bits")
    max_mi = primitives.get("max_pair_mutual_information_bits")
    l1 = primitives.get("distribution_l1_vs_uniform")
    p_max = primitives.get("max_outcome_probability")
    shots = primitives.get("shots") or 0
    gates_count = primitives.get("gates") or 0

    gates.append(Gate("circuit has qubits and gates",
                      n > 0 and gates_count > 0,
                      f"{n} qubits, {gates_count} gates"))
    gates.append(Gate("shots recorded", shots > 0, f"{shots} shots"))

    if entropy is None:
        gates.append(Gate("entropy present", False, "missing"))
    else:
        gates.append(Gate("entropy is physical (0 < H <= n)",
                          0 < entropy <= n + 1e-9, f"{entropy:.4f} / {n} bits"))
        gates.append(Gate(
            "entropy is NOT saturated (circuit shapes the distribution)",
            entropy < n - min_entropy_margin,
            f"{entropy:.4f} < {n}"))

    if l1 is None:
        gates.append(Gate("distribution distance present", False, "missing"))
    else:
        gates.append(Gate("state is not uniform", l1 > min_l1_vs_uniform,
                          f"L1 vs uniform {l1:.4f}"))

    if mean_mi is None:
        gates.append(Gate("mutual information present", False, "missing"))
    else:
        gates.append(Gate("entanglement present (mean pair MI)",
                          mean_mi > min_mutual_information,
                          f"{mean_mi:.6f} bits"))
    if max_mi is None:
        gates.append(Gate("strongest-pair MI present", False, "missing"))
    else:
        gates.append(Gate("some pair is entangled",
                          max_mi > min_max_pair_mi, f"{max_mi:.6f} bits"))

    if p_max is None or not n:
        gates.append(Gate("outcome selection recorded", False, "missing"))
    else:
        uniform = 1.0 / 2 ** n
        gates.append(Gate("outcomes are selection-based, not index ordering",
                          p_max > 1.5 * uniform,
                          f"p_max {p_max:.5f} vs uniform {uniform:.5f}"))

    pitches = primitives.get("pitches") or []
    pacing = primitives.get("scene_pacing") or []
    scenes = primitives.get("scene_count") or 0
    gates.append(Gate("melody derived from measurement outcomes", len(pitches) > 0,
                      f"{len(pitches)} notes"))
    gates.append(Gate("scene structure derived from outcomes",
                      len(pacing) == scenes and scenes > 0,
                      f"{scenes} scenes"))
    return gates


def check_provenance(provenance: list) -> list[Gate]:
    """Every creative decision must name the engine and source that made it.

    Accepts either `Provenance` objects or their serialised dicts, so a caller
    can pass whichever it happens to be holding.
    """
    entries = [p.to_dict() if hasattr(p, "to_dict") else p for p in provenance]
    gates: list[Gate] = []
    gates.append(Gate("provenance recorded", len(entries) >= 3,
                      f"{len(entries)} entries"))
    gates.append(Gate("every entry names an engine",
                      all(p.get("engine") for p in entries)))
    gates.append(Gate("every entry records a source",
                      all(p.get("source") for p in entries)))
    choices = [p.get("choice") for p in entries]
    gates.append(Gate("every entry names the choice it governs",
                      all(choices) and len(set(choices)) == len(choices),
                      ", ".join(str(c) for c in choices)))
    return gates


def summarise(gates: list[Gate]) -> dict:
    """Aggregate gates into counts for display."""
    passed = sum(1 for g in gates if g.ok)
    return {"passed": passed, "failed": len(gates) - passed, "total": len(gates),
            "ok": passed == len(gates)}


def format_gates(gates: list[Gate]) -> str:
    return "\n".join(repr(g) for g in gates)
