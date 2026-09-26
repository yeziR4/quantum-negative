"""Build a self-contained submission bundle for the Moth Hack form.

The form asks for a repo or file-share link, so this produces a single archive
containing everything needed to evaluate and reproduce the submission, plus a
manifest of SHA-256 checksums so the recipient can verify it survived transfer.

    python -B make_bundle.py                 # writes dist/quantum-negative-<date>.zip
    python -B make_bundle.py --verify-only   # re-check an existing bundle

Excluded from the bundle, deliberately: the API key, `__pycache__`, and the
scratch output directories (`web_output/`, `_verify_*`, `smoke_outputs/`).
Included, deliberately: the demo film/score/poster, because they are the
deliverables and a reviewer should not have to run anything to see the work.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(HERE, "dist")

# Never ship these, whatever the ignore rules say.
EXCLUDE_NAMES = {".moth_api_key"}
EXCLUDE_DIRS = {"__pycache__", ".git", "dist", "web_output", "notebook_output",
                "notebook_output_repeat", "smoke_outputs",
                "_verify_a", "_verify_b", "_verify_c",
                ".venv", "venv"}
EXCLUDE_SUFFIXES = (".pyc", ".pyo", ".log")

# Default-deny at the top level: only these directories ship. A scratch
# directory created by some future script therefore cannot leak into the bundle
# merely because nobody remembered to ignore it — which is exactly how
# `notebook_output_repeat/` (the notebook's reproducibility-comparison output)
# first got in, inflating the archive from ~2.1 MB to ~3.6 MB.
SHIP_DIRS = {"demo"}

# Warn if the archive grows past this: a surprise here means scratch is leaking.
SIZE_WARN_KIB = 2500

# These must be present or the bundle is not a submission.
REQUIRED = [
    "README.md", "SUBMISSION.md", "NOTES.md",
    "QUANTUM_NEGATIVE.ipynb", "webapp.py", "game.py", "pipeline.py", "qsim.py",
    "synth.py", "film.py", "checks.py", "moth_client.py", "smoke_test.py",
    "build_notebook.py", "make_bundle.py",
    "test_qsim.py", "verify_pipeline.py", "verify_notebook.py",
    "verify_webapp.py", "verify_game.py", "verify_mock_atlas.py",
    "demo/quantum_negative.mp4", "demo/quantum_negative.wav",
    "demo/poster.png", "demo/receipt.json",
    "api-notes.txt",
]


def iter_files() -> list[str]:
    """Every file that belongs in the bundle, relative to HERE.

    Default-deny: top-level directories must be listed in SHIP_DIRS to be walked
    at all, so newly created scratch cannot silently join the submission.
    """
    out: list[str] = []
    for name in sorted(os.listdir(HERE)):
        full = os.path.join(HERE, name)
        if os.path.isfile(full):
            if name in EXCLUDE_NAMES or name.endswith(EXCLUDE_SUFFIXES):
                continue
            if name.endswith(".zip"):
                continue                      # never nest a previous bundle
            out.append(name)
            continue
        if not os.path.isdir(full) or name not in SHIP_DIRS:
            continue
        for root, dirs, files in os.walk(full):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            for fname in files:
                if fname in EXCLUDE_NAMES or fname.endswith(EXCLUDE_SUFFIXES):
                    continue
                rel = os.path.relpath(os.path.join(root, fname), HERE)
                out.append(rel.replace(os.sep, "/"))
    return sorted(out)


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build() -> int:
    files = iter_files()

    missing = [r for r in REQUIRED if r not in files]
    leaked = [f for f in files if os.path.basename(f) in EXCLUDE_NAMES]
    if leaked:
        print(f"REFUSING to build: secret files matched: {leaked}")
        return 1

    stamp = time.strftime("%Y-%m-%d")
    os.makedirs(DIST, exist_ok=True)
    zip_path = os.path.join(DIST, f"quantum-negative-{stamp}.zip")
    manifest_path = os.path.join(DIST, f"quantum-negative-{stamp}.manifest.json")

    manifest = {
        "name": "QUANTUM NEGATIVE",
        "event": "Moth Hack 2026",
        "challenges": [
            {"id": 10, "tier": "Expert", "title": "Quantum-native 2",
             "artifact": "QUANTUM_NEGATIVE.ipynb"},
            {"id": 8, "tier": "Intermediate", "title": "Make a web app",
             "artifact": "webapp.py"},
            {"id": 5, "tier": "Intermediate", "title": "Quantum game",
             "artifact": "game.py"},
        ],
        "built": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "requirements": "Python 3.11+, numpy, Pillow, ffmpeg on PATH",
        "quickstart": [
            "jupyter lab QUANTUM_NEGATIVE.ipynb",
            "python webapp.py            # http://127.0.0.1:8000, game at /game",
            "python test_qsim.py verify_pipeline.py verify_notebook.py "
            "verify_webapp.py verify_game.py verify_mock_atlas.py",
        ],
        "file_count": len(files),
        "files": {rel: {"sha256": sha256(os.path.join(HERE, rel)),
                        "bytes": os.path.getsize(os.path.join(HERE, rel))}
                  for rel in files},
    }

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for rel in files:
            zf.write(os.path.join(HERE, rel), arcname=f"quantum-negative/{rel}")
        # The manifest travels inside the archive as well, so the bundle is
        # self-describing even if the sidecar file is lost.
        zf.writestr("quantum-negative/MANIFEST.json",
                    json.dumps(manifest, indent=2, sort_keys=True))

    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)

    total = sum(v["bytes"] for v in manifest["files"].values())
    archive_kib = os.path.getsize(zip_path) / 1024
    print(f"bundle    : {zip_path}")
    print(f"manifest  : {manifest_path}")
    print(f"files     : {len(files)}  ({total/1024:.1f} KiB uncompressed)")
    print(f"archive   : {archive_kib:.1f} KiB")
    print(f"sha256    : {sha256(zip_path)}")
    print(f"top-level : {sorted({f.split('/')[0] for f in files})}")
    if missing:
        print(f"\nWARNING: required files missing from the bundle: {missing}")
        return 1
    if archive_kib > SIZE_WARN_KIB:
        print(f"\nWARNING: archive is {archive_kib:.0f} KiB, over the "
              f"{SIZE_WARN_KIB} KiB budget — scratch may be leaking in. Check "
              f"the largest entries above.")
        return 1
    print("\nall required files present")
    return 0


def verify(zip_path: str) -> int:
    """Re-check an existing bundle against its embedded manifest."""
    problems: list[str] = []
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        if "quantum-negative/MANIFEST.json" not in names:
            print("no embedded MANIFEST.json")
            return 1
        manifest = json.loads(zf.read("quantum-negative/MANIFEST.json"))
        for rel, meta in manifest["files"].items():
            arc = f"quantum-negative/{rel}"
            if arc not in names:
                problems.append(f"missing from archive: {rel}")
                continue
            data = zf.read(arc)
            digest = hashlib.sha256(data).hexdigest()
            if digest != meta["sha256"]:
                problems.append(f"checksum mismatch: {rel}")
            elif len(data) != meta["bytes"]:
                problems.append(f"size mismatch: {rel}")
    if problems:
        print("bundle verification FAILED:")
        for p in problems[:20]:
            print("  ", p)
        return 1
    print(f"bundle verified: {len(manifest['files'])} files, "
          f"{len(manifest['challenges'])} challenges")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify-only", action="store_true")
    ap.add_argument("--zip", help="path to an existing bundle to verify")
    args = ap.parse_args()

    if args.verify_only:
        path = args.zip
        if not path:
            candidates = sorted(f for f in os.listdir(DIST) if f.endswith(".zip")) \
                if os.path.isdir(DIST) else []
            if not candidates:
                print("no bundle found in dist/")
                return 1
            path = os.path.join(DIST, candidates[-1])
        print(f"verifying {path}")
        return verify(path)
    return build()


if __name__ == "__main__":
    sys.exit(main())
