"""Smoke test: prove the client can actually talk to Atlas, end to end.

Run order (cheapest first — stop at the first failure):

    python smoke_test.py plan      # no network: sanity-check the client itself
    python smoke_test.py auth      # GET /me  -> account + feature flags
    python smoke_test.py engines   # GET /engines -> confirm the 27 engine ids
    python smoke_test.py run       # one cheap real job, then download outputs

`run` will pick the cheapest engine that needs no input files, so it should not
burn much credit. Pass an engine id to force one:

    python smoke_test.py run coin-toss-v1
"""

from __future__ import annotations

import sys

from moth_client import MothClient, MothError

# Engine ids the spec enumerates as /process paths. Used to diff live vs spec.
SPEC_ENGINES = [
    "blur-core-v1", "blur-midi-v1", "blur-v0", "blur-v1", "coin-toss-v1",
    "comet-qrng-v1", "deep-fryer-v1", "entanglement-shader-v0",
    "entanglement-shader-v1", "graph-v1", "labyrinth-v1", "otoc-echo-v1",
    "qdrive-api-v1", "qpixl-v1", "qrc-audio-v1", "qrc-gen-v2", "qrc-image-v1",
    "qrc-midi-v1", "qrc-train-v2", "retrocausal-echo-v1", "tamagotchi-v0",
    "tamagotchi-v1", "telablur-v1", "tessa-image-v1", "tomography-api-v2",
]


def cmd_plan() -> int:
    print(f"spec enumerates {len(SPEC_ENGINES)} engine /process paths")
    for e in SPEC_ENGINES:
        print("  ", e)
    client = MothClient()
    print(f"base url resolves to: {client.base}")
    print("client constructed OK; key present:", bool(client.api_key))
    return 0


def cmd_auth() -> int:
    client = MothClient()
    me = client.me()
    print(f"base      : {client.base}")
    print(f"email     : {me.get('email')}")
    print(f"role      : {me.get('platform_role')} / {me.get('role')}")
    print(f"features  : {me.get('features')}")
    print(f"run_quantum  = {client.has_feature('run_quantum')}")
    print(f"publish_engines = {client.has_feature('publish_engines')}")
    try:
        print(f"storage   : {client.storage()}")
    except MothError as exc:
        print(f"storage   : unavailable ({exc})")
    return 0


def cmd_engines() -> int:
    client = MothClient()
    live = client.engines()
    ids = {e["engine_id"] for e in live}
    print(f"live engines: {len(ids)}")
    print(f"{'engine_id':<28} {'credits':>8} {'input':<10} output")
    for e in sorted(live, key=lambda x: x["engine_id"]):
        print(f"{e['engine_id']:<28} {str(e.get('credits_per_run')):>8} "
              f"{str(e.get('input_type')):<10} {e.get('output_type')}")

    print()
    missing = [e for e in SPEC_ENGINES if e not in ids]
    extra = sorted(ids - set(SPEC_ENGINES))
    print(f"in spec but not visible : {missing or 'none'}")
    print(f"visible but not in spec : {extra or 'none'}")
    print()
    print("cheapest engines:")
    for credits, engine_id in client.cheap_engines(10):
        print(f"  {credits:>5} credits  {engine_id}")
    return 0


def cmd_run(engine_id: str | None = None) -> int:
    client = MothClient()

    if not engine_id:
        # Cheapest engine that takes no uploaded input — safest first real call.
        candidates = []
        for e in client.engines():
            if e.get("input_type") in (None, "", "none") and not e.get("input_files"):
                candidates.append((e.get("credits_per_run") or 0, e["engine_id"]))
        if not candidates:
            print("no no-input engine found; pass an engine id explicitly")
            return 1
        candidates.sort()
        engine_id = candidates[0][1]
        print(f"auto-selected cheapest no-input engine: {engine_id} "
              f"({candidates[0][0]} credits)")
    else:
        print(f"using engine: {engine_id}")

    schema = client.params_schema(engine_id)
    print(f"params schema: {schema}")

    # Prefer an emulator run for the smoke test: cheap and always available.
    params = {}
    if isinstance(schema, dict) and "props" in schema:
        props = schema.get("props") or {}
        if "shots" in props:
            params["shots"] = min(int(props["shots"].get("default", 1024) or 1024), 1024)
    mode = "emu" if "mode" in str(schema) else None

    try:
        print(f"\nsubmitting (mode={mode}, params={params}) ...")
        job = client.submit(engine_id, params=params, mode=mode)
    except MothError as exc:
        print(f"submit failed -> {exc}")
        if exc.gated_feature:
            print(f"account is missing platform feature: {exc.gated_feature}")
        return 1

    print(f"job {job['job_id']} {job['status']}")
    client.wait(job["job_id"])
    res = client.result(job["job_id"])
    outputs = res.get("outputs") or []
    print(f"\n{len(outputs)} output(s):")
    for out in outputs:
        print(f"  slot={out.get('slot')} file={out.get('filename')} "
              f"type={out.get('content_type')} bytes={out.get('size_bytes')}")

    if outputs:
        out_dir = "smoke_outputs"
        import os
        os.makedirs(out_dir, exist_ok=True)
        for i, out in enumerate(outputs):
            slot = out.get("slot") or f"out{i}"
            dest = os.path.join(out_dir, f"{slot}_{out.get('filename', f'output{i}')}")
            client.download(out["url"], dest)
            print(f"  downloaded -> {dest}")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 1
    cmd = argv[1]
    if cmd == "plan":
        return cmd_plan()
    if cmd == "auth":
        return cmd_auth()
    if cmd == "engines":
        return cmd_engines()
    if cmd == "run":
        return cmd_run(argv[2] if len(argv) > 2 else None)
    print(f"unknown command {cmd!r}")
    print(__doc__)
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except MothError as exc:
        print(f"\nMoth API error: {exc}")
        if exc.gated_feature:
            print(f"missing platform feature: {exc.gated_feature}")
        sys.exit(1)
