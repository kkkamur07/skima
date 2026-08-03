#!/usr/bin/env python3
"""Skima Web UI server.

Local-only, stdlib-only (no pip dependencies). Serves the static Web UI in this
directory plus a small JSON API that reads `../sources.json` and scans
`../library/` on every request (the Library on disk is the source of truth, so
there is nothing to cache or invalidate).

The directory layout is authoritative for a Capability's Id, Bucket and Status:
`library/<bucket>/<id>/` is active, `library/deprecated/<bucket>/<id>/` is
deprecated. A `.skima.json` that disagrees does not win — the disagreement is
reported in the payload's `warnings` and shown in the Web UI.

`GET /api/status` reads `../.skima/status.json`, written by `cli/skima check`.
`POST /api/check` runs `cli/skima check` as a subprocess. That is the one
state-changing endpoint: it makes network calls (`git ls-remote`) and rewrites
`.skima/status.json`, so it is protected by Origin/Fetch-Metadata checks and a
single-flight lock.

Every request must carry a Host header naming the loopback address and the port
this process is bound to; that closes DNS rebinding (an attacker domain that
resolves to 127.0.0.1 still sends its own name in Host).

Run:
    python3 server.py [port]        # from web/
    python3 web/server.py [port]    # from repo root

Then open http://127.0.0.1:4567 (default port).
"""
import json
import subprocess
import sys
import threading
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

# The page is self-contained: one external script, one external stylesheet, no
# inline script/style, no remote assets. So the CSP can be maximally strict.
CONTENT_SECURITY_POLICY = (
    "default-src 'none'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "base-uri 'none'; "
    "form-action 'none'; "
    "frame-ancestors 'none'"
)
SECURITY_HEADERS = (
    ("X-Content-Type-Options", "nosniff"),
    ("Content-Security-Policy", CONTENT_SECURITY_POLICY),
    ("Referrer-Policy", "no-referrer"),
    ("X-Frame-Options", "DENY"),
    ("Cache-Control", "no-store"),
)

# Populated by configure_origins() once the listen port is known.
ALLOWED_HOSTS = set()
ALLOWED_ORIGINS = set()

# Header the Web UI sends on state-changing requests. A cross-origin page cannot
# set a custom header without a CORS preflight, and this server answers no
# preflight, so requiring it blocks form-style CSRF from non-Fetch-Metadata
# clients while leaving curl/scripts usable.
CSRF_HEADER = "X-Skima-Request"

# Only one `skima check` may run at a time: it spawns a subprocess that does
# live network I/O for up to CHECK_TIMEOUT_SECONDS, and this is a threading
# server, so without this lock a burst of requests would pile up subprocesses.
CHECK_LOCK = threading.Lock()

# /api/file may serve documentation only, and only from inside one capability
# directory (see find_capability_dir + resolve_doc_path).
DOC_SUFFIXES = {".md", ".markdown", ".txt"}
DOC_EXACT_NAMES = {"LICENSE", "LICENCE", "NOTICE", ".skima.json"}
SKIP_DIR_NAMES = {".git", ".github", "node_modules", "__pycache__", ".venv"}
DOC_SCAN_MAX_DEPTH = 3
DOC_SCAN_MAX_FILES = 400
MAX_DOC_BYTES = 512 * 1024

VALID_KINDS = {"skill", "hook", "plugin", "agent"}


def configure_origins(port):
    """Build the Host / Origin allowlist for the port we are actually bound to."""
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"}
    if port == 80:  # browsers omit the default port from Host
        hosts |= {"127.0.0.1", "localhost", "[::1]"}
    ALLOWED_HOSTS.clear()
    ALLOWED_HOSTS.update(hosts)
    ALLOWED_ORIGINS.clear()
    ALLOWED_ORIGINS.update(f"http://{h}" for h in hosts)


def load_sources():
    if not SOURCES_JSON.exists():
        return {"sources": {}}
    try:
        return json.loads(SOURCES_JSON.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return {"sources": {}, "error": f"sources.json could not be read: {e}"}


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
        return {"ok": False, "error": f"CLI not found at {CLI_BIN.relative_to(ROOT)}"}, 500

    try:
        proc = subprocess.run(
            [str(CLI_BIN), "check"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=CHECK_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"skima check timed out after {CHECK_TIMEOUT_SECONDS}s"}, 504
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


def _visible_dirs(parent):
    try:
        entries = sorted(parent.iterdir(), key=lambda p: p.name)
    except OSError:
        return []
    return [p for p in entries if p.is_dir() and not p.name.startswith(".")]


def list_bucket_names():
    """Every Bucket that exists on disk, including ones with no Capability yet.

    A Bucket is "an evolving, user-defined primary home"; creating
    `library/<name>/` must make it visible before anything is adopted into it.
    Deprecated Capabilities live at `library/deprecated/<bucket>/`, so that
    sub-level contributes Bucket names too.
    """
    names = set()
    if not LIBRARY_DIR.exists():
        return names
    for bucket_dir in _visible_dirs(LIBRARY_DIR):
        if bucket_dir.name == "deprecated":
            for sub in _visible_dirs(bucket_dir):
                names.add(sub.name)
        else:
            names.add(bucket_dir.name)
    return names


def iter_capability_dirs():
    """Yield (bucket, capability_dir, is_deprecated) for every Capability on disk."""
    if not LIBRARY_DIR.exists():
        return
    for bucket_dir in _visible_dirs(LIBRARY_DIR):
        if bucket_dir.name == "deprecated":
            for sub_bucket_dir in _visible_dirs(bucket_dir):
                for cap_dir in _visible_dirs(sub_bucket_dir):
                    yield sub_bucket_dir.name, cap_dir, True
        else:
            for cap_dir in _visible_dirs(bucket_dir):
                yield bucket_dir.name, cap_dir, False


def read_capability_meta(bucket, cap_dir, is_deprecated, include_docs=True):
    """Describe one Capability. The directory wins; .skima.json only annotates.

    Id is the directory name, Bucket is the directory it sits in, and Status is
    positional (`library/deprecated/...` is deprecated). Anything `.skima.json`
    claims that contradicts the directory is surfaced in "warnings" instead of
    being applied, so a stale `"status": "active"` under `library/deprecated/`
    can no longer paint an active badge and then 404 on the detail lookup.
    """
    disk_id = cap_dir.name
    disk_status = "deprecated" if is_deprecated else "active"
    warnings = []
    meta = {}

    meta_path = cap_dir / ".skima.json"
    if meta_path.is_file():
        try:
            loaded = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            loaded = None
            warnings.append(f".skima.json could not be read ({e}); using directory values.")
        if isinstance(loaded, dict):
            meta = loaded
        elif loaded is not None:
            warnings.append(".skima.json is not a JSON object; ignoring its contents.")
    else:
        warnings.append("No .skima.json in this capability directory.")

    for field, disk_value in (("id", disk_id), ("bucket", bucket), ("status", disk_status)):
        declared = meta.get(field)
        if declared and declared != disk_value:
            warnings.append(
                f'.skima.json says {field} "{declared}" but the directory says '
                f'"{disk_value}". The directory wins — fix .skima.json or move the directory.'
            )

    kind = meta.get("kind") or "skill"
    if kind not in VALID_KINDS:
        warnings.append(f'Unknown kind "{kind}" (expected one of: {", ".join(sorted(VALID_KINDS))}).')

    provenance = meta.get("provenance")
    if provenance is not None and not isinstance(provenance, dict):
        warnings.append("provenance in .skima.json is not an object; ignoring it.")
        provenance = None

    payload = {
        "id": disk_id,
        "bucket": bucket,
        "kind": kind,
        "status": disk_status,
        "provenance": provenance,
        "path": str(cap_dir.relative_to(ROOT)),
        "warnings": warnings,
    }
    if include_docs:
        payload["docs"] = list_doc_files(cap_dir)
    return payload


def list_capabilities():
    """Summary rows for the Library list — no doc scan, that is detail-view work."""
    return [read_capability_meta(b, d, dep, include_docs=False) for b, d, dep in iter_capability_dirs()]


def list_buckets():
    """Bucket name -> Capabilities, including Buckets that are still empty."""
    buckets = {name: [] for name in list_bucket_names()}
    for cap in list_capabilities():
        buckets.setdefault(cap["bucket"], []).append(cap)
    return buckets


def _is_safe_segment(segment):
    """Reject anything that could leave the intended directory or confuse the OS."""
    if not segment or segment == "." or ".." in segment:
        return False
    if "/" in segment or "\\" in segment:
        return False
    return all(ord(c) >= 32 for c in segment)  # also catches the NUL byte


def _resolves_inside(path, root):
    try:
        real = path.resolve()
    except (OSError, ValueError, RuntimeError):
        return False
    return root in real.parents


def find_capability_dir(bucket, cap_id, deprecated):
    if not _is_safe_segment(bucket) or not _is_safe_segment(cap_id):
        return None
    if bucket == "deprecated":  # that level holds Buckets, never Capabilities
        return None
    base = (LIBRARY_DIR / "deprecated" / bucket / cap_id) if deprecated else (LIBRARY_DIR / bucket / cap_id)
    try:
        base = base.resolve()
        library_root = LIBRARY_DIR.resolve()
    except (OSError, ValueError, RuntimeError):
        return None
    if library_root not in base.parents:
        return None
    return base if base.is_dir() else None


def is_doc_name(name):
    return name in DOC_EXACT_NAMES or Path(name).suffix.lower() in DOC_SUFFIXES


def list_doc_files(cap_dir):
    """Relative paths of every previewable doc inside cap_dir, depth-limited.

    Docs in subdirectories (`references/*.md` and friends) are included. Any
    entry that resolves outside cap_dir — i.e. an escaping symlink — is skipped,
    so the dropdown only ever offers files /api/file will actually serve.
    """
    try:
        root = cap_dir.resolve()
    except (OSError, ValueError, RuntimeError):
        return []

    found = []

    def walk(directory, rel, depth):
        if depth > DOC_SCAN_MAX_DEPTH or len(found) >= DOC_SCAN_MAX_FILES:
            return
        try:
            entries = sorted(directory.iterdir(), key=lambda p: p.name)
        except OSError:
            return
        for entry in entries:
            if len(found) >= DOC_SCAN_MAX_FILES:
                return
            name = entry.name
            rel_name = f"{rel}/{name}" if rel else name
            if entry.is_dir():
                if name.startswith(".") or name in SKIP_DIR_NAMES:
                    continue
                if not _resolves_inside(entry, root):
                    continue
                walk(entry, rel_name, depth + 1)
            elif entry.is_file() and is_doc_name(name) and _resolves_inside(entry, root):
                found.append(rel_name)

    walk(root, "", 1)
    return found


def resolve_doc_path(cap_dir, rel_name):
    """Map a client-supplied relative doc path to a real file inside cap_dir.

    Defense in depth: every path segment is screened, the filename must look
    like documentation, and the *fully resolved* path must still be strictly
    inside the capability directory. The last check is what stops a symlinked
    `README.md -> ~/.ssh/id_rsa` from being served: resolve() follows the link
    to its target and the containment assertion then fails.
    """
    parts = rel_name.split("/")
    if len(parts) > DOC_SCAN_MAX_DEPTH:
        return None
    if not all(_is_safe_segment(seg) for seg in parts):
        return None
    if any(seg.startswith(".") or seg in SKIP_DIR_NAMES for seg in parts[:-1]):
        return None
    if not is_doc_name(parts[-1]):
        return None
    try:
        root = cap_dir.resolve()
        real = root.joinpath(*parts).resolve()
    except (OSError, ValueError, RuntimeError):
        return None
    if root not in real.parents:
        return None
    return real if real.is_file() else None


class Handler(BaseHTTPRequestHandler):
    server_version = "Skima"
    sys_version = ""

    def log_message(self, fmt, *args):
        sys.stderr.write(f"{self.address_string()} - {fmt % args}\n")

    # -- response helpers -------------------------------------------------

    def _begin(self, status, content_type, length):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        for header, value in SECURITY_HEADERS:
            self.send_header(header, value)
        self.end_headers()
        self.responded = True

    def _send_json(self, payload, status=200):
        body = json.dumps(payload, indent=2).encode("utf-8")
        self._begin(status, "application/json; charset=utf-8", len(body))
        self.wfile.write(body)

    def _send_static(self, filename, content_type):
        path = WEB_DIR / filename
        if not path.is_file():
            return self._send_json({"error": f"missing static file {filename}"}, 500)
        data = path.read_bytes()
        self._begin(200, content_type, len(data))
        self.wfile.write(data)

    # -- request guards ---------------------------------------------------

    def _host_ok(self):
        """Reject any Host we did not bind — this is the DNS-rebinding guard.

        A rebound attacker page is fetched from `http://evil.example:<port>`, so
        the browser sends `Host: evil.example:<port>` even though the socket
        lands on 127.0.0.1. Pinning Host to the loopback names keeps every
        /api/* response unreadable to it.
        """
        host = (self.headers.get("Host") or "").strip().lower()
        if host in ALLOWED_HOSTS:
            return True
        self._send_json(
            {
                "error": "bad Host header",
                "detail": f"expected one of {sorted(ALLOWED_HOSTS)}; got {host or '(none)'}",
            },
            403,
        )
        return False

    def _origin_ok(self):
        """CSRF guard for state-changing requests.

        Note what the old `client_address[0] in ("127.0.0.1", "::1")` test could
        not do: a cross-site POST driven by any page the user has open *is* from
        127.0.0.1. Only the request's own origin metadata distinguishes them.
        """
        origin = self.headers.get("Origin")
        if origin is not None:
            if origin.strip().lower() in ALLOWED_ORIGINS:
                return True
            self._send_json({"error": "cross-origin request rejected", "origin": origin}, 403)
            return False

        # Some same-origin fetches omit Origin, so absence alone proves nothing.
        # Fetch Metadata answers the question directly when the client sends it.
        site = (self.headers.get("Sec-Fetch-Site") or "").strip().lower()
        if site:
            if site in ("same-origin", "none"):
                return True
            self._send_json({"error": "cross-site request rejected", "sec_fetch_site": site}, 403)
            return False

        # No Origin and no Fetch Metadata: not a browser page context. Require a
        # custom header, which cross-origin HTML forms and simple requests
        # cannot set (and no CORS preflight is ever answered here).
        if self.headers.get(CSRF_HEADER) is not None:
            return True
        self._send_json(
            {
                "error": "missing Origin",
                "detail": f"send an allowed Origin or the {CSRF_HEADER}: 1 header",
            },
            403,
        )
        return False

    # -- dispatch ---------------------------------------------------------

    def do_GET(self):
        self._dispatch("GET", self._route_get)

    def do_POST(self):
        self._dispatch("POST", self._route_post)

    def _dispatch(self, method, router):
        """Single exception boundary: every failure becomes JSON, not a traceback."""
        self.responded = False
        try:
            if not self._host_ok():
                return
            if method == "POST" and not self._origin_ok():
                return
            parsed = urlparse(self.path)
            router(parsed.path, parse_qs(parsed.query))
        except (BrokenPipeError, ConnectionResetError):
            return  # client hung up; nothing to say
        except Exception as e:  # noqa: BLE001 - deliberate catch-all boundary
            self.log_message("unhandled %s on %s %s: %s", type(e).__name__, method, self.path, e)
            if self.responded:
                return
            try:
                self._send_json(
                    {"error": "internal server error", "detail": f"{type(e).__name__}: {e}"}, 500
                )
            except Exception:  # noqa: BLE001 - the socket is gone; give up quietly
                pass

    @staticmethod
    def _param(query, key):
        return (query.get(key) or [""])[0]

    def _route_get(self, route, query):
        if route in STATIC_FILES:
            filename, content_type = STATIC_FILES[route]
            return self._send_static(filename, content_type)

        if route == "/api/sources":
            return self._send_json(load_sources())

        if route == "/api/buckets":
            return self._send_json({"buckets": list_buckets()})

        if route == "/api/status":
            return self._send_json(load_status())

        if route == "/api/capability":
            bucket = self._param(query, "bucket")
            cap_id = self._param(query, "id")
            deprecated = self._param(query, "status") == "deprecated"
            if not bucket or not cap_id:
                return self._send_json({"error": "bucket and id query params are required"}, 400)
            cap_dir = find_capability_dir(bucket, cap_id, deprecated)
            if cap_dir is None:
                return self._send_json({"error": "capability not found"}, 404)
            return self._send_json(read_capability_meta(bucket, cap_dir, deprecated))

        if route == "/api/file":
            bucket = self._param(query, "bucket")
            cap_id = self._param(query, "id")
            name = self._param(query, "name")
            deprecated = self._param(query, "status") == "deprecated"
            if not bucket or not cap_id or not name:
                return self._send_json({"error": "bucket, id, name query params are required"}, 400)
            cap_dir = find_capability_dir(bucket, cap_id, deprecated)
            if cap_dir is None:
                return self._send_json({"error": "capability not found"}, 404)
            file_path = resolve_doc_path(cap_dir, name)
            if file_path is None:
                return self._send_json({"error": "file not allowed or not found"}, 404)
            try:
                raw = file_path.read_bytes()
            except OSError as e:
                return self._send_json({"error": f"could not read {name}: {e}"}, 500)
            truncated = len(raw) > MAX_DOC_BYTES
            content = raw[:MAX_DOC_BYTES].decode("utf-8", errors="replace")
            return self._send_json({"name": name, "content": content, "truncated": truncated})

        return self._send_json({"error": "not found", "path": route}, 404)

    def _route_post(self, route, query):
        if route == "/api/check":
            # Secondary guard only; the Origin check above is what stops CSRF.
            if self.client_address[0] not in ("127.0.0.1", "::1"):
                return self._send_json({"error": "forbidden"}, 403)
            if not CHECK_LOCK.acquire(blocking=False):
                return self._send_json(
                    {"ok": False, "error": "a check is already running; wait for it to finish"}, 409
                )
            try:
                payload, status = run_check()
            finally:
                CHECK_LOCK.release()
            return self._send_json(payload, status)

        return self._send_json({"error": "not found", "path": route}, 404)


def main():
    port = DEFAULT_PORT
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            print(f"Ignoring invalid port {sys.argv[1]!r}, using {DEFAULT_PORT}")
    configure_origins(port)
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
