#!/usr/bin/env python3
"""Skima Web UI server.

Local-only, stdlib-only (no pip dependencies). Serves the static UI in this
directory plus a small JSON API that reads `../sources.json` and scans
`../library/` on every request (the Library is the source of truth on disk,
so there is nothing to cache or invalidate).

`GET /api/status` reads `../.skima/status.json`, written by `cli/skima check`.
`POST /api/check` runs `cli/skima check` as a subprocess (localhost only) and
returns the refreshed status. Both degrade gracefully if the CLI doesn't
implement `check` yet.

Run:
    python3 server.py [port]        # from web/
    python3 web/server.py [port]    # from repo root

Then open http://127.0.0.1:4567 (default port).
"""
import json
import mimetypes
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

WEB_DIR = Path(__file__).resolve().parent
ROOT = WEB_DIR.parent
SOURCES_JSON = ROOT / "sources.json"
LIBRARY_DIR = ROOT / "library"
STATUS_JSON = ROOT / ".skima" / "status.json"
CLI_BIN = ROOT / "cli" / "skima"

DEFAULT_PORT = 4567
CHECK_TIMEOUT_SECONDS = 120

# Contract for .skima/status.json, written by `cli/skima check` / `sync`:
#   {
#     "checked_at": "<ISO-8601 timestamp>",
#     "sources": {
#       "<source name>": {
#         "url": "<upstream url>",
#         "pinned": "<sha>",
#         "remote": "<sha>" | null,
#         "status": "up-to-date" | "behind" | "unreachable",
#         "error": "<short human-readable detail>" | null
#       }
#     }
#   }
# A source absent from "sources" (e.g. added after the last check) has no
# recorded status; the Web UI treats that as "unknown".
DEFAULT_STATUS = {"checked_at": None, "sources": {}, "message": "Run skima check"}

STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "application/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
}

# Only these filenames can be fetched via /api/file, and only from inside a
# single capability directory (see find_capability_dir).
SAFE_DOC_NAMES = {
    "SKILL.md",
    "README.md",
    "USAGE.md",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "LICENSE",
    ".skima.json",
}


def load_sources():
    if not SOURCES_JSON.exists():
        return {"sources": {}}
    try:
        return json.loads(SOURCES_JSON.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return {"sources": {}, "error": f"sources.json is not valid JSON: {e}"}


def load_status():
    if not STATUS_JSON.exists():
        return dict(DEFAULT_STATUS)
    try:
        data = json.loads(STATUS_JSON.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULT_STATUS)
    if not isinstance(data, dict):
        return dict(DEFAULT_STATUS)
    data.setdefault("checked_at", None)
    data.setdefault("sources", {})
    data.setdefault("message", "")
    return data


def run_check():
    """Spawn `cli/skima check`, wait for it, and return (payload, http_status).

    Never raises — missing CLI, a non-zero exit, or a hung process all turn
    into a JSON error payload so the Web UI can always show something useful.
    """
    if not CLI_BIN.exists():
        return {
            "ok": False,
            "error": f"CLI not found at {CLI_BIN.relative_to(ROOT)}",
        }, 500

    try:
        proc = subprocess.run(
            [str(CLI_BIN), "check"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=CHECK_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "error": f"skima check timed out after {CHECK_TIMEOUT_SECONDS}s",
        }, 504
    except OSError as e:
        return {"ok": False, "error": f"failed to run skima check: {e}"}, 500

    if proc.returncode != 0:
        snippet = ((proc.stdout or "") + (proc.stderr or "")).strip()
        return {
            "ok": False,
            "returncode": proc.returncode,
            "error": "skima check exited with a non-zero status",
            "stdout": snippet[-4000:],
        }, 200

    status = load_status()
    status["ok"] = True
    return status, 200


def iter_capability_dirs():
    """Yield (bucket, capability_dir, is_deprecated) for every capability on disk."""
    if not LIBRARY_DIR.exists():
        return
    for bucket_dir in sorted(p for p in LIBRARY_DIR.iterdir() if p.is_dir()):
        if bucket_dir.name == "deprecated":
            for sub_bucket_dir in sorted(p for p in bucket_dir.iterdir() if p.is_dir()):
                for cap_dir in sorted(p for p in sub_bucket_dir.iterdir() if p.is_dir()):
                    yield sub_bucket_dir.name, cap_dir, True
        else:
            for cap_dir in sorted(p for p in bucket_dir.iterdir() if p.is_dir()):
                yield bucket_dir.name, cap_dir, False


def read_capability_meta(bucket, cap_dir, is_deprecated):
    meta_path = cap_dir / ".skima.json"
    meta = {}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            meta = {}
    return {
        "id": meta.get("id", cap_dir.name),
        "bucket": meta.get("bucket", bucket),
        "kind": meta.get("kind", "skill"),
        "status": meta.get("status") or ("deprecated" if is_deprecated else "active"),
        "provenance": meta.get("provenance"),
        "path": str(cap_dir.relative_to(ROOT)),
        "files": sorted(p.name for p in cap_dir.iterdir() if p.is_file()),
    }


def list_capabilities():
    return [read_capability_meta(bucket, cap_dir, dep) for bucket, cap_dir, dep in iter_capability_dirs()]


def list_buckets():
    buckets = {}
    for cap in list_capabilities():
        buckets.setdefault(cap["bucket"], []).append(cap)
    return buckets


def _is_safe_segment(segment):
    return bool(segment) and "/" not in segment and "\\" not in segment and ".." not in segment


def find_capability_dir(bucket, cap_id, deprecated):
    if not _is_safe_segment(bucket) or not _is_safe_segment(cap_id):
        return None
    base = (LIBRARY_DIR / "deprecated" / bucket / cap_id) if deprecated else (LIBRARY_DIR / bucket / cap_id)
    base = base.resolve()
    library_root = LIBRARY_DIR.resolve()
    if library_root != base and library_root not in base.parents:
        return None
    return base if base.is_dir() else None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write(f"{self.address_string()} - {fmt % args}\n")

    def _send_json(self, payload, status=200):
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_static(self, filename, content_type):
        path = WEB_DIR / filename
        if not path.is_file():
            return self._send_json({"error": f"missing static file {filename}"}, 500)
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urlparse(self.path)
        route = parsed.path
        query = parse_qs(parsed.query)

        if route in STATIC_FILES:
            filename, content_type = STATIC_FILES[route]
            return self._send_static(filename, content_type)

        if route == "/api/sources":
            return self._send_json(load_sources())

        if route == "/api/capabilities":
            return self._send_json({"capabilities": list_capabilities()})

        if route == "/api/buckets":
            return self._send_json({"buckets": list_buckets()})

        if route == "/api/status":
            return self._send_json(load_status())

        if route == "/api/capability":
            bucket = (query.get("bucket") or [""])[0]
            cap_id = (query.get("id") or [""])[0]
            deprecated = (query.get("status") or [""])[0] == "deprecated"
            if not bucket or not cap_id:
                return self._send_json({"error": "bucket and id query params are required"}, 400)
            cap_dir = find_capability_dir(bucket, cap_id, deprecated)
            if cap_dir is None:
                return self._send_json({"error": "capability not found"}, 404)
            return self._send_json(read_capability_meta(bucket, cap_dir, deprecated))

        if route == "/api/file":
            bucket = (query.get("bucket") or [""])[0]
            cap_id = (query.get("id") or [""])[0]
            deprecated = (query.get("status") or [""])[0] == "deprecated"
            name = (query.get("name") or [""])[0]
            if not bucket or not cap_id or not name:
                return self._send_json({"error": "bucket, id, name query params are required"}, 400)
            if name not in SAFE_DOC_NAMES:
                return self._send_json({"error": "file not allowed"}, 400)
            cap_dir = find_capability_dir(bucket, cap_id, deprecated)
            if cap_dir is None:
                return self._send_json({"error": "capability not found"}, 404)
            file_path = cap_dir / name
            if not file_path.is_file():
                return self._send_json({"error": "file not found"}, 404)
            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                return self._send_json({"error": str(e)}, 500)
            return self._send_json({"name": name, "content": content})

        if route == "/api/review":
            return self._send_json(
                {
                    "status": "coming_soon",
                    "message": "Change review is not implemented yet. Use the CLI to sync Sources in the meantime.",
                }
            )

        return self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        route = parsed.path

        if route == "/api/check":
            if self.client_address[0] not in ("127.0.0.1", "::1"):
                return self._send_json({"error": "forbidden"}, 403)
            payload, status = run_check()
            return self._send_json(payload, status)

        return self._send_json({"error": "not found"}, 404)


def main():
    port = DEFAULT_PORT
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            print(f"Ignoring invalid port {sys.argv[1]!r}, using {DEFAULT_PORT}")
    mimetypes.init()
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Skima Web UI: http://127.0.0.1:{port}  (repo root: {ROOT})")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
