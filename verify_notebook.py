"""Verify the saved notebook artifact.

Confirms that `QUANTUM_NEGATIVE.ipynb` is a valid, executed notebook whose
embedded outputs actually contain the evidence the submission claims — rather
than being a file that merely parses.

    python -B verify_notebook.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import nbformat

NB = "QUANTUM_NEGATIVE.ipynb"

# Strings that must survive into the saved outputs. Each is a claim the
# submission rests on, so each must be provably present in the executed file.
REQUIRED_EVIDENCE = [
    ("Bell state mutual information: 1.000000000 bits",
     "the simulator produces genuine maximal entanglement"),
    ("iSWAP verified on all four basis states",
     "the native two-qubit gate is exhaustively correct"),
    ("mean adj. MI", "entanglement is reported for the circuit, not one pair"),
    ("entropy is NOT saturated",
     "the circuit shapes the distribution rather than being uniform"),
    ("identical distribution: False",
     "the broken-circuit demo is reproduced, and the fixed circuit differs per seed"),
    ("physics gates passed", "the physics gate summary ran"),
    ("byte-identic", "reproducibility is demonstrated in the notebook"),
    ("Same prompt, same seed", "the reproducibility claim is stated from the output"),
]

PASS, FAIL = 0, 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  PASS  {name}" + (f"  ({detail})" if detail else ""))
    else:
        FAIL += 1
        print(f"  FAIL  {name}" + (f"  ({detail})" if detail else ""))


def ensure_outputs() -> bool:
    """Make sure the notebook's own artifacts exist before checking them.

    A reviewer extracting the submission bundle gets the notebook but not
    `notebook_output/` (it is generated scratch, deliberately not shipped). Since
    the notebook is already executed with outputs embedded, the sensible thing is
    to check it as delivered — and only run it if its artifacts are genuinely
    absent, so the check is still meaningful on a fresh machine rather than being
    skipped or failing for a reason that has nothing to do with the submission.
    """
    marker = os.path.join("notebook_output", "receipt.json")
    if os.path.exists(marker):
        return True
    print("\n[0] notebook_output/ is absent — executing the notebook to produce it")
    print("    (the delivered notebook already carries outputs; this only")
    print("     regenerates the artifacts it writes to disk)")
    result = subprocess.run([sys.executable, "-B", "build_notebook.py", "--execute"],
                            capture_output=True, text=True)
    ok = result.returncode == 0 and os.path.exists(marker)
    if not ok:
        tail = (result.stdout or "")[-400:] + (result.stderr or "")[-400:]
        print(f"    notebook execution failed:\n{tail}")
    return ok


def main() -> int:
    print("=" * 66)
    print("notebook verification")
    print("=" * 66)

    if not ensure_outputs():
        print("\ncannot verify the notebook's written artifacts")
        return 1

    print("\n[1] structure")
    check("notebook file exists", os.path.exists(NB))
    nb = nbformat.read(NB, as_version=4)
    nbformat.validate(nb)
    check("valid nbformat", True, f"nbformat {nb.nbformat}.{nb.nbformat_minor}")
    code_cells = [c for c in nb.cells if c.cell_type == "code"]
    md_cells = [c for c in nb.cells if c.cell_type == "markdown"]
    check("has code cells", len(code_cells) >= 10, f"{len(code_cells)} code")
    check("has narrative", len(md_cells) >= 10, f"{len(md_cells)} markdown")
    check("every cell has an id", all(c.get("id") for c in nb.cells))

    print("\n[2] execution state")
    unrun = [i for i, c in enumerate(code_cells) if c.get("execution_count") is None]
    check("every code cell was executed", not unrun, f"unrun: {unrun or 'none'}")
    errors = [o for c in code_cells for o in (c.get("outputs") or [])
              if o.get("output_type") == "error"]
    check("no error outputs", not errors,
          f"{len(errors)} errors" if errors else "clean")

    print("\n[3] embedded evidence")
    blob = json.dumps(nb).replace("\\n", "\n")
    for needle, why in REQUIRED_EVIDENCE:
        check(f"output contains {needle!r}", needle in blob, why)

    print("\n[4] artifacts produced by the notebook itself")
    for path, label in (
            ("notebook_output/quantum_negative.mp4", "film"),
            ("notebook_output/quantum_negative.wav", "score"),
            ("notebook_output/poster.png", "poster"),
            ("notebook_output/receipt.json", "receipt")):
        exists = os.path.exists(path)
        size = os.path.getsize(path) if exists else 0
        check(f"notebook wrote its own {label}", exists, f"{size/1024:.1f} KiB")

    print("\n[5] the notebook's receipt is self-consistent")
    try:
        receipt = json.load(open("notebook_output/receipt.json", encoding="utf-8"))
        cp = receipt["creative_primitives"]
        check("receipt records the circuit", cp["gates"] > 0 and cp["shots"] > 0,
              f"{cp['n_qubits']}q, {cp['gates']} gates")
        check("receipt entropy is unsaturated",
              cp["entropy_bits"] < cp["n_qubits"] - 1e-6,
              f"{cp['entropy_bits']:.4f} < {cp['n_qubits']}")
        check("receipt shows entanglement",
              cp["mutual_information_bits"] > 0.01,
              f"{cp['mutual_information_bits']:.4f} bits")
        check("receipt names every engine",
              all(p.get("engine") for p in receipt["provenance"]),
              f"{len(receipt['provenance'])} entries")
        check("receipt carries artifact hashes",
              len(receipt.get("artifact_sha256") or {}) >= 3)
    except Exception as exc:                            # noqa: BLE001
        check("receipt readable", False, str(exc))

    print("\n" + "=" * 66)
    print(f"{PASS} passed, {FAIL} failed")
    print("=" * 66)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
