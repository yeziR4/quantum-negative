"""Minimal, dependency-free client for the Moth Atlas API.

Only the Python standard library is used, so this runs anywhere (including the
platform notebook runner) with no install step.

Spec: moth-api v0.41.0 (OpenAPI 3.1) — see NOTES.md and api-notes.txt.

Auth
----
Set the key in the environment; never hard-code it:

    MOTH_API_KEY=moth_...            (required)
    MOTH_API_BASE=https://...        (optional; defaults to DEFAULT_BASE)

The spec declares no `servers`, so the base URL must be confirmed from the
platform's API docs page. If the default is wrong you will get 404s — set
MOTH_API_BASE and re-run.

Usage
-----
    from moth_client import MothClient
    m = MothClient()
    print(m.me())                       # account + feature flags
    print([e["engine_id"] for e in m.engines()])

    asset = m.upload_file("photo.png", content_type="image/png")
    job = m.submit("tessa-image-v1", params={"shots": 4096},
                   input_files={"image": asset["asset_id"]})
    done = m.wait(job["job_id"])
    for out in m.result(job["job_id"])["outputs"] or []:
        m.download(out["url"], f"out_{out.get('slot', 'x')}_{out['filename']}")
"""

from __future__ import annotations

import json
import mimetypes
import os
import time
import urllib.error
import urllib.request

DEFAULT_BASE = "https://api.mothquantum.com"
DEFAULT_TIMEOUT = 60

# Cloudflare in front of the API rejects the default Python urllib signature, so
# we identify ourselves honestly. Override with MOTH_USER_AGENT if needed.
DEFAULT_USER_AGENT = "moth-hack-quantum-pipeline/0.1 (python-urllib; hackathon entry)"

# Key resolution order: explicit arg -> MOTH_API_KEY -> this file (first line).
# Keeping the secret in a local file avoids it appearing in shell history,
# process listings, or chat logs.
KEY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".moth_api_key")


def _load_key() -> str:
    env = os.environ.get("MOTH_API_KEY")
    if env:
        return env.strip()
    try:
        with open(KEY_FILE, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#"):
                    return line
    except FileNotFoundError:
        pass
    return ""


class MothError(RuntimeError):
    """An API call failed. Carries the HTTP status and the server's detail."""

    def __init__(self, status: int, detail: str, body: object = None):
        super().__init__(f"HTTP {status}: {detail}")
        self.status = status
        self.detail = detail
        self.body = body

    @property
    def gated_feature(self) -> str | None:
        """If this is a 403 naming a platform feature, return that feature name.

        The spec: "Some param values are reserved for accounts holding a
        platform feature (for example mode=qpu requires run_quantum) and answer
        403 naming the feature." We surface it so callers can degrade to emu.
        """
        if self.status != 403:
            return None
        text = self.detail or ""
        for token in ("run_quantum", "publish_engines", "run_qpu"):
            if token in text:
                return token
        return None


class MothClient:
    def __init__(self, api_key: str | None = None, base_url: str | None = None,
                 timeout: int = DEFAULT_TIMEOUT):
        self.api_key = api_key or _load_key()
        if not self.api_key:
            raise SystemExit(
                "No API key. Put it in moth/.moth_api_key (first line, "
                "preferred) or set MOTH_API_KEY. Create one in the Moth "
                "dashboard, or POST /api/v1/keys."
            )
        self.base = (base_url or os.environ.get("MOTH_API_BASE") or DEFAULT_BASE).rstrip("/")
        self.timeout = timeout
        self.user_agent = os.environ.get("MOTH_USER_AGENT", DEFAULT_USER_AGENT)

    # ---------------------------------------------------------------- transport

    def _request(self, method: str, path: str, *, json_body=None, raw_body=None,
                 headers=None, absolute: bool = False,
                 auth: bool = True) -> tuple[int, bytes, dict]:
        """One HTTP call.

        `auth=False` suppresses the Authorization header. This matters for
        **presigned URLs**: the upload and download URLs point at storage, not
        the API, and are authorised by their own signature. Sending the API key
        there would leak the credential to a third-party host for no benefit —
        an earlier version did exactly that, and the mock-Atlas suite now
        asserts the header is absent.
        """
        url = path if absolute else f"{self.base}{path}"
        hdrs = {"Accept": "application/json",
                # The API sits behind Cloudflare, which rejects the default
                # "Python-urllib/3.x" signature outright with a 403 ("blocked
                # based on your browser's signature"). Identify honestly and
                # allow an override, rather than impersonating a browser.
                "User-Agent": self.user_agent}
        if auth:
            hdrs["Authorization"] = f"Bearer {self.api_key}"
        data = None
        if json_body is not None:
            data = json.dumps(json_body).encode()
            hdrs["Content-Type"] = "application/json"
        elif raw_body is not None:
            data = raw_body
        if headers:
            hdrs.update(headers)

        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.status, resp.read(), dict(resp.headers)
        except urllib.error.HTTPError as exc:
            body = exc.read()
            detail = ""
            parsed = None
            try:
                parsed = json.loads(body)
                detail = parsed.get("detail") or parsed.get("title") or ""
            except Exception:
                detail = body[:400].decode("utf-8", "replace")
            raise MothError(exc.code, detail, parsed) from None
        except urllib.error.URLError as exc:
            raise MothError(0, f"connection failed for {url}: {exc.reason}") from None

    def _json(self, method: str, path: str, **kw):
        status, body, _ = self._request(method, path, **kw)
        if not body:
            return {}
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            raise MothError(status, "response was not JSON", body[:400]) from None

    # ------------------------------------------------------------------ account

    def me(self) -> dict:
        """Current user: id, email, features[], platform_role."""
        return self._json("GET", "/api/v1/me")

    def features(self) -> list[str]:
        return self.me().get("features") or []

    def has_feature(self, name: str) -> bool:
        return name in self.features()

    def storage(self) -> dict:
        """Storage usage and quota — check before uploading big files."""
        return self._json("GET", "/api/v1/me/storage")

    def list_keys(self) -> dict:
        return self._json("GET", "/api/v1/keys")

    def create_key(self, name: str) -> dict:
        """Returns {key, key_id, name}. `key` is the secret; store it safely."""
        return self._json("POST", "/api/v1/keys", json_body={"name": name})

    # ------------------------------------------------------------------ engines

    def engines(self, limit: int = 200) -> list[dict]:
        """Every visible engine, following next_cursor to exhaustion."""
        out, cursor = [], None
        while True:
            q = f"/api/v1/engines?limit={limit}"
            if cursor:
                q += f"&cursor={cursor}"
            page = self._json("GET", q)
            out.extend(page.get("engines") or [])
            cursor = page.get("next_cursor")
            if not cursor:
                return out

    def engine(self, engine_id: str) -> dict:
        """Full definition of one engine, including params_schema."""
        return self._json("GET", f"/api/v1/engines/{engine_id}")

    def params_schema(self, engine_id: str) -> dict:
        return self.engine(engine_id).get("params_schema") or {}

    # ------------------------------------------------------------------- assets

    def create_asset(self, filename: str, size_bytes: int,
                     content_type: str = "application/octet-stream") -> dict:
        return self._json("POST", "/api/v1/assets", json_body={
            "filename": filename,
            "content_type": content_type,
            "size_bytes": size_bytes,
        })

    def complete_asset(self, asset_id: str) -> dict:
        return self._json("POST", f"/api/v1/assets/{asset_id}/complete")

    def upload_file(self, path: str, content_type: str | None = None) -> dict:
        """Create -> PUT bytes -> complete. Returns the finished Asset."""
        with open(path, "rb") as fh:
            blob = fh.read()
        name = os.path.basename(path)
        ctype = content_type or mimetypes.guess_type(name)[0] or "application/octet-stream"
        created = self.create_asset(name, len(blob), ctype)

        upload = created.get("upload") or {}
        url, headers = upload.get("url"), upload.get("headers") or {}
        if not url:
            raise MothError(0, "create_asset returned no upload URL", created)
        self._request("PUT", url, raw_body=blob, headers=headers, absolute=True,
                      auth=False)
        return self.complete_asset(created["asset_id"])

    def upload_bytes(self, filename: str, blob: bytes,
                     content_type: str = "application/octet-stream") -> dict:
        created = self.create_asset(filename, len(blob), content_type)
        upload = created.get("upload") or {}
        url, headers = upload.get("url"), upload.get("headers") or {}
        if not url:
            raise MothError(0, "create_asset returned no upload URL", created)
        self._request("PUT", url, raw_body=blob, headers=headers, absolute=True,
                      auth=False)
        return self.complete_asset(created["asset_id"])

    def assets(self, **filters) -> dict:
        q = "&".join(f"{k}={v}" for k, v in filters.items() if v is not None)
        return self._json("GET", "/api/v1/assets" + (f"?{q}" if q else ""))

    def download(self, url: str, dest: str, chunk: int = 1 << 20) -> str:
        """Stream a presigned output URL to disk. No auth header on presigned URLs."""
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=self.timeout) as resp, open(dest, "wb") as fh:
            while True:
                block = resp.read(chunk)
                if not block:
                    break
                fh.write(block)
        return dest

    # --------------------------------------------------------------------- jobs

    def submit(self, engine_id: str, *, params: dict | None = None,
               input_files: dict | None = None, mode: str | None = None,
               start_from: str | None = None, stop_after: str | None = None) -> dict:
        """POST /engines/{id}/process -> 202 {job_id, status, submitted_at}.

        Raises MothError with .gated_feature set if the account lacks a required
        platform feature (e.g. mode='qpu' needs 'run_quantum').
        """
        body: dict = {}
        if params:
            body["params"] = params
        if input_files:
            body["input_files"] = input_files
        if mode:
            body["mode"] = mode
        if start_from:
            body["start_from"] = start_from
        if stop_after:
            body["stop_after"] = stop_after
        return self._json("POST", f"/api/v1/engines/{engine_id}/process", json_body=body)

    def job(self, job_id: str) -> dict:
        return self._json("GET", f"/api/v1/jobs/{job_id}")

    def status(self, job_id: str) -> dict:
        return self._json("GET", f"/api/v1/jobs/{job_id}/status")

    def result(self, job_id: str) -> dict:
        return self._json("GET", f"/api/v1/jobs/{job_id}/result")

    @staticmethod
    def outputs_of(result: dict) -> list[dict]:
        """Downloadable file outputs, or [] for engines that return JSON only.

        Verified against the live API: engines fall into two shapes. File
        engines (blur-v1, telablur-v1, tessa-image-v1, retrocausal-echo-v1)
        return `outputs: [...]` with presigned URLs. JSON engines
        (tamagotchi-v1, coin-toss-v1) return `outputs: null` and put their data
        in `result.output` instead. Treating the second case as "no result"
        would silently discard a successful run.
        """
        return list(result.get("outputs") or [])

    @staticmethod
    def inline_output(result: dict) -> dict | None:
        """The JSON payload for engines that answer in-body, else None.

        The live shape is `{"result": {"output": {...}}}`, but tolerate a bare
        `{"result": {...}}` too rather than assuming one nesting depth.
        """
        raw = result.get("result")
        if not isinstance(raw, dict):
            return None
        inner = raw.get("output")
        if isinstance(inner, dict):
            return inner
        return raw

    def jobs(self, **filters) -> dict:
        q = "&".join(f"{k}={v}" for k, v in filters.items() if v is not None)
        return self._json("GET", "/api/v1/jobs" + (f"?{q}" if q else ""))

    def wait(self, job_id: str, poll: float = 2.0, timeout: float = 1800.0,
             verbose: bool = True) -> dict:
        """Poll until the job leaves queued/processing. Returns the final status."""
        started = time.time()
        last = None
        while True:
            st = self.status(job_id)
            state = (st.get("status") or "").lower()
            if verbose and state != last:
                progress = st.get("progress")
                print(f"  [{int(time.time() - started):>4}s] {state}"
                      + (f" progress={progress}" if progress is not None else ""))
                last = state
            if state in ("completed", "failed", "cancelled"):
                if state != "completed" and st.get("error"):
                    raise MothError(0, f"job {state}: {st['error']}", st)
                return st
            if time.time() - started > timeout:
                raise TimeoutError(f"job {job_id} still {state} after {timeout}s")
            time.sleep(poll)

    def run(self, engine_id: str, *, download_to: str | None = None, **kw) -> dict:
        """submit -> wait -> result, optionally downloading every output."""
        job = self.submit(engine_id, **kw)
        self.wait(job["job_id"])
        res = self.result(job["job_id"])
        if download_to:
            os.makedirs(download_to, exist_ok=True)
            for i, out in enumerate(res.get("outputs") or []):
                slot = out.get("slot") or f"out{i}"
                dest = os.path.join(download_to, f"{slot}_{out.get('filename', f'output{i}')}")
                out["local_path"] = self.download(out["url"], dest)
        return res

    # ------------------------------------------------------------------ helpers

    def cheap_engines(self, limit: int = 10) -> list[tuple[int, str]]:
        """Engines sorted by credits_per_run — pick the cheapest for smoke tests."""
        rows = [(e.get("credits_per_run") or 0, e["engine_id"]) for e in self.engines()]
        return sorted(rows)[:limit]


if __name__ == "__main__":
    import sys

    client = MothClient()
    print(f"base: {client.base}")
    me = client.me()
    print(f"me: {me.get('email')} role={me.get('platform_role')}")
    print(f"features: {me.get('features')}")
    print(f"run_quantum: {client.has_feature('run_quantum')}")
    if len(sys.argv) > 1 and sys.argv[1] == "engines":
        for e in client.engines():
            print(f"  {e['engine_id']:<28} credits={e.get('credits_per_run')} "
                  f"in={e.get('input_type')} out={e.get('output_type')}")
