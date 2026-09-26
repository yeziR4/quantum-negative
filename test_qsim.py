"""Tests for qsim.py — run with:  python -B test_qsim.py

These are the correctness backstop for the notebook: they prove the local
quantum core actually behaves quantum-mechanically (unitarity, entanglement,
Born-rule readout) before any of it is used to generate media.

Always run with `-B`. A stale `__pycache__/qsim.*.pyc` will silently execute an
older revision of the module, which produces "impossible" test results and
wastes a lot of debugging time — this bit us once already.
"""

from __future__ import annotations

import math
import os
import shutil

_HERE = os.path.dirname(os.path.abspath(__file__))
_CACHE = os.path.join(_HERE, "__pycache__")
if os.path.isdir(_CACHE):
    # Drop cached bytecode for our own modules before importing them.
    for _name in os.listdir(_CACHE):
        if _name.startswith(("qsim.", "moth_client.")):
            try:
                os.remove(os.path.join(_CACHE, _name))
            except OSError:
                pass

import qsim  # noqa: E402  (import must follow the cache purge)

PASS, FAIL = 0, 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS  {name}" + (f"  ({detail})" if detail else ""))
    else:
        FAIL += 1
        print(f"  FAIL  {name}" + (f"  ({detail})" if detail else ""))


def close(a: float, b: float, tol: float = 1e-9) -> bool:
    return abs(a - b) <= tol


def test_gray_and_bitreverse() -> None:
    print("\ngray code / bit reverse")
    check("gray(0) == 0", qsim.gray_code(0) == 0)
    check("gray(1) == 1", qsim.gray_code(1) == 1)
    check("gray(2) == 3", qsim.gray_code(2) == 3)
    check("gray(3) == 2", qsim.gray_code(3) == 2)
    # Consecutive Gray codes must differ in exactly one bit.
    ok = all(bin(qsim.gray_code(i) ^ qsim.gray_code(i + 1)).count("1") == 1
             for i in range(64))
    check("consecutive gray codes differ by 1 bit", ok)
    check("bit_reverse(0b001, 3) == 0b100", qsim.bit_reverse(0b001, 3) == 0b100)


def test_unitarity() -> None:
    print("\nunitarity (norm preserved through random circuits)")
    import random
    worst = 0.0
    for trial in range(25):
        rng = random.Random(trial)
        n = rng.randint(2, 6)
        reg = qsim.QuantumRegister(n, seed=trial)
        for _ in range(40):
            op = rng.choice(["rx", "ry", "rz", "h", "x", "z", "phase", "cnot", "cz", "iswap"])
            if op in ("cnot", "cz", "iswap"):
                a = rng.randrange(n)
                b = rng.randrange(n)
                while b == a:
                    b = rng.randrange(n)
                getattr(reg, {"h": "hadamard", "x": "pauli_x", "z": "pauli_z"}.get(op, op))(a, b)
            else:
                q = rng.randrange(n)
                if op in ("h", "x", "z"):
                    getattr(reg, {"h": "hadamard", "x": "pauli_x", "z": "pauli_z"}[op])(q)
                else:
                    getattr(reg, op)(q, rng.uniform(-math.pi, math.pi))
        worst = max(worst, reg.verify_normalised())
    check("norm stays 1 to <1e-9 over 25 random circuits", worst < 1e-9,
          f"worst error {worst:.2e}")


def test_bell_state() -> None:
    print("\nBell state |Phi+> = (|00> + |11>)/sqrt(2)")
    reg = qsim.QuantumRegister(2, seed=1)
    reg.hadamard(0)
    reg.cnot(0, 1)
    probs = reg.probabilities()
    check("P(00) == 0.5", close(probs[0b00], 0.5), f"{probs[0b00]:.6f}")
    check("P(11) == 0.5", close(probs[0b11], 0.5), f"{probs[0b11]:.6f}")
    check("P(01) == 0", close(probs[0b01], 0.0))
    check("P(10) == 0", close(probs[0b10], 0.0))

    joint = reg.pair_joint(0, 1)
    mi = qsim.mutual_information(joint)
    check("mutual information == 1 bit (maximally entangled)", close(mi, 1.0),
          f"{mi:.9f} bits")
    check("entropy == 1 bit", close(qsim.entropy_bits(probs), 1.0))

    # Bell state must be a product state's opposite: marginals are uniform.
    check("marginal P(q0=1) == 0.5", close(reg.marginal(0), 0.5))
    check("marginal P(q1=1) == 0.5", close(reg.marginal(1), 0.5))

    # Correlated sampling: the two bits must always agree.
    counts = reg.sample(400)
    disagree = sum(1 for i in counts if ((i >> 0) & 1) != ((i >> 1) & 1))
    check("400 shots never disagree (perfect correlation)", disagree == 0)


def test_product_state_has_no_entanglement() -> None:
    print("\nproduct state carries no entanglement")
    reg = qsim.QuantumRegister(2, seed=2)
    reg.ry(0, 0.7)
    reg.ry(1, 1.1)
    mi = qsim.mutual_information(reg.pair_joint(0, 1))
    check("mutual information ~ 0 bits", mi < 1e-12, f"{mi:.3e} bits")


def test_iswap_entangles() -> None:
    print("\niSWAP (native two-qubit gate) maps every basis state correctly")
    # Exhaustive check against the definition:
    # |00>->|00>, |01>->i|10>, |10>->i|01>, |11>->|11>.
    expected = {0b00: (0b00, 1 + 0j), 0b01: (0b10, 1j),
                0b10: (0b01, 1j), 0b11: (0b11, 1 + 0j)}
    all_ok = True
    for basis, (want_index, want_amp) in expected.items():
        reg = qsim.QuantumRegister(2, seed=3)
        reg.state = [0j] * 4
        reg.state[basis] = 1 + 0j
        reg.iswap(0, 1)
        got_index = max(range(4), key=lambda i: abs(reg.state[i]))
        amp = reg.state[got_index]
        ok = (got_index == want_index
              and abs(amp - want_amp) < 1e-12
              and reg.verify_normalised() < 1e-12)
        all_ok = all_ok and ok
        print(f"        |{basis:02b}> -> {amp:.3g}|{got_index:02b}> "
              f"(want {want_amp:.3g}|{want_index:02b}>) {'ok' if ok else 'WRONG'}")
    check("all four basis states transform correctly", all_ok)

    # Qubit 0 is the LEAST-significant bit of the index, so the state with qubit
    # 0 = 1 and qubit 1 = 0 is |10> = index 0b10, and iSWAP sends it to i|01>.
    reg = qsim.QuantumRegister(2, seed=3)
    reg.pauli_x(0)          # sets qubit 0 -> index 0b01
    reg.iswap(0, 1)
    probs = reg.probabilities()
    check("P(index 0b10 == q1q0 = 10) == 1 after iSWAP|x0>",
          close(probs[0b10], 1.0), f"{probs[0b10]:.9f}")
    check("norm preserved", reg.verify_normalised() < 1e-12)


def test_sampling_reproducible() -> None:
    print("\nsampling determinism (needed for reproducible media)")
    a = qsim.QuantumRegister(4, seed=42)
    a.hadamard(0)
    a.iswap(0, 3)
    b = qsim.QuantumRegister(4, seed=42)
    b.hadamard(0)
    b.iswap(0, 3)
    check("same seed -> identical shot counts", a.sample(500) == b.sample(500))


def test_blur_grid() -> None:
    print("\nblur_grid (local stand-in for blur-core-v1)")
    values = [math.sin(i / 4.0) for i in range(64)]
    out, metrics = qsim.blur_grid(values, qubits=6, strength=0.5, reach=1, seed=7)
    check("output length matches input", len(out) == len(values))
    check("all outputs finite", all(math.isfinite(v) for v in out))
    check("unit norm preserved", metrics["norm_error"] < 1e-9,
          f"{metrics['norm_error']:.2e}")
    check("gates were applied", metrics["gates"] > 0, f"{metrics['gates']} gates")
    check("mutual information > 0 (interference entangles neighbours)",
          metrics["entanglement_mi_bits"] > 0.0,
          f"{metrics['entanglement_mi_bits']:.6f} bits")
    check("entropy within bounds",
          0.0 <= metrics["entropy_bits"] <= metrics["max_entropy_bits"] + 1e-9,
          f"{metrics['entropy_bits']:.4f} / {metrics['max_entropy_bits']:.1f}")

    # Determinism: identical inputs and seed must reproduce bit-for-bit.
    out2, m2 = qsim.blur_grid(values, qubits=6, strength=0.5, reach=1, seed=7)
    check("deterministic for fixed seed", out == out2 and metrics == m2)

    # Information preservation: a flat grid stays flat.
    flat, _ = qsim.blur_grid([1.0] * 32, qubits=5, strength=0.5, seed=1)
    spread = max(flat) - min(flat)
    check("flat input stays (near) flat — information preserved", spread < 1e-9,
          f"spread {spread:.2e}")

    # The exact (shot-free) readout is twirl-independent by construction, so the
    # seed must NOT change it — that is precisely what Pauli twirling guarantees.
    out3, m3 = qsim.blur_grid(values, qubits=6, strength=0.5, reach=1, seed=8)
    check("exact readout is seed-independent (twirl leaves expectations unbiased)",
          out == out3 and m3["entropy_bits"] == metrics["entropy_bits"])

    # A sampled readout carries shot noise, so the seed shapes the individual
    # shot record while the mean still tracks the exact answer.
    s1, _ = qsim.blur_grid(values, qubits=6, strength=0.5, seed=7, shots=4000)
    s2, _ = qsim.blur_grid(values, qubits=6, strength=0.5, seed=8, shots=4000)
    check("sampled readout varies with seed (shot noise + twirl)", s1 != s2)
    exact_mean = sum(out) / len(out)
    peak = max(abs(v) for v in values)
    mean_gap = abs(sum(s1) / len(s1) - exact_mean)
    check("sampled mean tracks the exact mean", mean_gap < 0.25 * peak,
          f"gap {mean_gap:.4f} vs peak {peak:.2f}")


def test_reservoir() -> None:
    print("\nquantum reservoir computing")
    res = qsim.Reservoir(num_qubits=4, num_random_gates=8, seed=11)
    res2 = qsim.Reservoir(num_qubits=4, num_random_gates=8, seed=11)
    drive = [(math.sin(i / 3), math.cos(i / 5)) for i in range(20)]
    feats = res.run(drive)
    check("one feature row per timestep", len(feats) == len(drive))
    check("feature width consistent", len({len(r) for r in feats}) == 1,
          f"width {len(feats[0])}")
    check("features all finite and in [0,1]",
          all(0.0 <= v <= 1.0 for row in feats for v in row))
    check("same seed -> identical reservoir features", feats == res2.run(drive))

    res3 = qsim.Reservoir(num_qubits=4, num_random_gates=8, seed=12)
    check("different seed -> different features", res3.run(drive) != feats)

    # A readout must extract the drive from the reservoir state. The honest
    # claim here is a *linear* one, and sine over [-1, 1] is exactly the kind of
    # target a linear map cannot reproduce precisely — so we require that it
    # clearly beats the trivial constant predictor (the mean) rather than
    # asserting an arbitrary low absolute error.
    targets = [u for (u, _v) in drive]
    mean_mae = sum(abs(t - sum(targets) / len(targets)) for t in targets) / len(targets)
    readout = qsim.fit_readout(feats, targets, ridge=1e-8)
    preds = qsim.predict(readout, feats)
    mae = sum(abs(p - t) for p, t in zip(preds, targets)) / len(targets)
    check("linear readout beats the mean baseline by >3x",
          mae < mean_mae / 3.0,
          f"MAE {mae:.6f} vs baseline {mean_mae:.6f}")
    check("linear readout MAE is finite and bounded", 0.0 <= mae < 0.25,
          f"MAE {mae:.6f}")

    # Polynomial features are what actually close the gap on nonlinear targets.
    poly = qsim.polynomial_features(feats, degree=2)
    readout_p = qsim.fit_readout(poly, targets, ridge=1e-6)
    mae_p = sum(abs(p - t) for p, t in
                zip(qsim.predict(readout_p, poly), targets)) / len(targets)
    check("polynomial (degree 2) readout fits the drive (MAE < 0.05)",
          mae_p < 0.05, f"MAE {mae_p:.6f}")

    check("readout has one weight per feature", len(readout) == len(feats[0]))


def test_entropy_helper() -> None:
    print("\nentropy helper")
    check("deterministic distribution -> 0 bits", close(qsim.entropy_bits([1.0, 0.0]), 0.0))
    check("uniform over 4 -> 2 bits", close(qsim.entropy_bits([0.25] * 4), 2.0))
    check("empty -> 0 bits", qsim.entropy_bits([]) == 0.0)


def main() -> int:
    print("=" * 64)
    print("qsim tests — local quantum core for the Atlas pipeline")
    print("=" * 64)
    test_gray_and_bitreverse()
    test_unitarity()
    test_bell_state()
    test_product_state_has_no_entanglement()
    test_iswap_entangles()
    test_sampling_reproducible()
    test_blur_grid()
    test_reservoir()
    test_entropy_helper()
    print("\n" + "=" * 64)
    print(f"{PASS} passed, {FAIL} failed")
    print("=" * 64)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
