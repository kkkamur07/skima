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
SOURCES_DIR = ROOT / "sources"
STATUS_JSON = ROOT / ".skima" / "status.json"
CLI_BIN = ROOT / "cli" / "skima"

DEFAULT_PORT = 4567
CHECK_TIMEOUT_SECONDS = 120
ADOPT_TIMEOUT_SECONDS = 180
INSTALL_TIMEOUT_SECONDS = 180

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

# Adopt and install both mutate trees on disk, and install reads the whole
# Library while adopt is writing into it. One lock covers both so a double
# click can never interleave them.
WRITE_LOCK = threading.Lock()

# A POST body here is a handful of short strings; anything larger is a mistake
# or an attack, and reading it would only waste memory.
MAX_BODY_BYTES = 64 * 1024

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


def run_cli(args, timeout):
    """Spawn `cli/skima <args>`, wait for it, and return (payload, http_status).

    Never raises — missing CLI, a non-zero exit, or a hung process all turn
    into a JSON error payload so the Web UI can always show something useful.
    A non-zero exit is reported as HTTP 200 with `ok: false`: the request
    succeeded, the command it ran did not, and the Web UI wants the output
    either way.
    """
    label = f"skima {args[0]}" if args else "skima"
    if not CLI_BIN.exists():
        return {"ok": False, "error": f"CLI not found at {CLI_BIN.relative_to(ROOT)}"}, 500

    try:
        proc = subprocess.run(
            [str(CLI_BIN), *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"{label} timed out after {timeout}s"}, 504
    except OSError as e:
        return {"ok": False, "error": f"failed to run {label}: {e}"}, 500

    output = ((proc.stdout or "") + (proc.stderr or "")).strip()[-8000:]
    if proc.returncode != 0:
        return {
            "ok": False,
            "returncode": proc.returncode,
            "error": f"{label} exited with a non-zero status",
            "output": output,
        }, 200
    return {"ok": True, "output": output}, 200


def run_check():
    """`skima check`, plus the refreshed status the Web UI re-renders from."""
    payload, http_status = run_cli(["check"], CHECK_TIMEOUT_SECONDS)
    if not payload.get("ok"):
        # The Sources page reads `stdout` for the failure detail panel.
        payload["stdout"] = payload.pop("output", None)
        return payload, http_status
    status = load_status()
    status["ok"] = True
    return status, http_status


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


# ---------------------------------------------------------------------------
# Exploring Sources
#
# A Source tree is upstream's layout, not Skima's, so there is no record file
# to read: Capabilities have to be recognised by shape. The rule is one line
# long — a directory containing SKILL.md is a Capability, and the OUTERMOST
# match wins. That second half is what stops a nested translation such as
# socratic-method-skill/docs/de/SKILL.md from being offered as a Capability of
# its own; it is part of the Capability above it.
#
# Three shapes are adoptable, one per marker file:
#
#   SKILL.md                    -> Kind skill
#   .claude-plugin/plugin.json  -> Kind plugin  (a repository that is one plugin)
#   hooks/hooks.json            -> Kind hook    (a hook bundle)
#
# Agents and commands are not adoptable on their own — an agent is a single
# `agents/<name>.md` file and a command a single `commands/<name>.toml`, and a
# Capability is a directory. They ship as part of a plugin, so they are counted
# and listed as what that plugin brings rather than offered separately.
# ---------------------------------------------------------------------------

SOURCE_SCAN_MAX_DEPTH = 5
SOURCE_SCAN_MAX_CAPS = 400
FRONTMATTER_MAX_BYTES = 16 * 1024
COMPONENT_LIST_LIMIT = 60
COMMAND_SUFFIXES = {".toml", ".md"}


def read_frontmatter(skill_md):
    """Best-effort `name` / `description` from a SKILL.md frontmatter block.

    Deliberately not a YAML parser. It reads top-level `key: value` pairs and
    folds indented continuation lines into the value, which covers every skill
    in the tracked Sources; anything it cannot understand becomes a missing
    field rather than an error, because a malformed frontmatter upstream must
    not take out the whole Explore page.
    """
    try:
        with skill_md.open("rb") as f:
            raw = f.read(FRONTMATTER_MAX_BYTES)
    except OSError:
        return {}

    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}

    fields = {}
    last_key = None
    for line in lines[1:]:
        stripped = line.strip()
        if stripped == "---":
            break
        if not stripped:
            continue
        if line[:1] in (" ", "\t"):  # continuation, or a nested key we ignore
            if last_key is not None:
                fields[last_key] = f"{fields[last_key]} {stripped}".strip()
            continue
        key, sep, value = stripped.partition(":")
        if not sep or not key or " " in key:
            continue
        last_key = key.strip()
        value = value.strip()
        # A block scalar ("description: |") carries no value of its own — the
        # text is the indented lines under it, which fold in as continuations.
        if value in ("|", ">", "|-", ">-", "|+", ">+"):
            value = ""
        fields[last_key] = value.strip("'\"")

    return {k: v for k, v in fields.items() if k in ("name", "description") and v}


def source_root_dir(name, entry):
    """Absolute directory for one Source, or None if it is not a real tree.

    The path comes from sources.json, which is committed data rather than user
    input, but it still decides which directory gets read and served — so it is
    screened exactly like a request parameter and must resolve inside
    `sources/`.
    """
    if not _is_safe_segment(name):
        return None
    rel = (entry or {}).get("path") or f"sources/{name}"
    parts = [p for p in str(rel).split("/") if p]
    if len(parts) < 2 or parts[0] != "sources" or not all(_is_safe_segment(p) for p in parts[1:]):
        return None
    candidate = ROOT.joinpath(*parts)
    try:
        real = candidate.resolve()
        sources_root = SOURCES_DIR.resolve()
    except (OSError, ValueError, RuntimeError):
        return None
    if sources_root not in real.parents:
        return None
    return real if real.is_dir() else None


def resolve_source_path(root, rel):
    """Map an upstream path (relative to a Source root, "." for the root)."""
    if rel in ("", "."):
        return root if root.is_dir() else None
    parts = rel.split("/")
    if len(parts) > SOURCE_SCAN_MAX_DEPTH or not all(_is_safe_segment(p) for p in parts):
        return None
    try:
        real = root.joinpath(*parts).resolve()
    except (OSError, ValueError, RuntimeError):
        return None
    if root not in real.parents:
        return None
    return real if real.is_dir() else None


def read_json_file(path, max_bytes=FRONTMATTER_MAX_BYTES):
    """Small JSON file as a dict, or {} — upstream data is never trusted."""
    try:
        with path.open("rb") as f:
            raw = f.read(max_bytes)
        loaded = json.loads(raw.decode("utf-8", errors="replace"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _sorted_files(directory, keep):
    try:
        entries = sorted(directory.iterdir(), key=lambda p: p.name)
    except OSError:
        return []
    return [e for e in entries if e.is_file() and not e.name.startswith(".") and keep(e)]


def hook_events(hooks_json):
    """The event names a hooks.json registers, e.g. PreToolUse, Stop.

    Claude Code's hooks file maps event name -> list of matchers, so the keys
    are exactly "when does this fire" — the one fact that says what a hook
    bundle actually does without opening it.
    """
    data = read_json_file(hooks_json)
    hooks = data.get("hooks")
    if isinstance(hooks, dict):
        data = hooks
    return sorted(k for k, v in data.items() if isinstance(v, list) and k[:1].isupper())


def capability_components(cap_dir, is_skill_root):
    """What this directory brings to the table, as counted parts.

    A plugin is a bundle: it can ship skills, agent definitions, hook bundles
    and slash commands at once, and its plugin.json says none of that. Reading
    the tree is the only way to answer "what do I get if I adopt this".
    """
    components = {}

    skills = []
    if not is_skill_root:
        for sub in (cap_dir / "skills", cap_dir):
            if not sub.is_dir():
                continue
            found = []

            def walk(directory, depth):
                if depth > 3 or len(found) >= COMPONENT_LIST_LIMIT:
                    return
                if (directory / "SKILL.md").is_file():
                    found.append(directory.name)
                    return
                try:
                    entries = sorted(directory.iterdir(), key=lambda p: p.name)
                except OSError:
                    return
                for entry in entries:
                    if entry.is_dir() and not entry.name.startswith(".") and entry.name not in SKIP_DIR_NAMES:
                        walk(entry, depth + 1)

            walk(sub, 1)
            if found:
                skills = found
                break
    if skills:
        components["skills"] = sorted(set(skills))

    agents = [p.stem for p in _sorted_files(cap_dir / "agents", lambda p: p.suffix.lower() == ".md")]
    agents = [a for a in agents if a.upper() not in ("README", "AGENTS")]
    if agents:
        components["agents"] = agents[:COMPONENT_LIST_LIMIT]

    hooks_json = cap_dir / "hooks" / "hooks.json"
    if hooks_json.is_file():
        components["hooks"] = hook_events(hooks_json) or ["hooks.json"]
    elif (cap_dir / "hooks.json").is_file():
        components["hooks"] = hook_events(cap_dir / "hooks.json") or ["hooks.json"]

    commands = [
        p.stem
        for p in _sorted_files(cap_dir / "commands", lambda p: p.suffix.lower() in COMMAND_SUFFIXES)
    ]
    commands = [c for c in commands if c.upper() != "README"]
    if commands:
        components["commands"] = commands[:COMPONENT_LIST_LIMIT]

    return components


def describe_source_capability(root, cap_dir, kind=None):
    """One discovered Capability: Id, Kind, display text, and what it brings."""
    rel = "." if cap_dir == root else str(cap_dir.relative_to(root))
    # A repository that is itself one Capability has no directory below the
    # root to name it, so the Source's own directory name is the Id (the CLI's
    # `adopt` derives the same Id for an upstream path of ".").
    cap_id = root.name if rel == "." else cap_dir.name
    # "hooks" is what upstream calls the directory, not what this bundle is.
    # Every Source would offer a Capability with the same Id, so the Source
    # name carries it — the Web UI sends this Id to `adopt` explicitly.
    if kind == "hook" and cap_id == "hooks":
        cap_id = f"{root.name}-hooks"

    is_skill_root = (cap_dir / "SKILL.md").is_file()
    plugin_json = cap_dir / ".claude-plugin" / "plugin.json"
    if kind is None:
        kind = "plugin" if plugin_json.is_file() else "skill"

    name = None
    description = None
    if is_skill_root:
        front = read_frontmatter(cap_dir / "SKILL.md")
        name = front.get("name")
        description = front.get("description")
    if plugin_json.is_file():
        manifest = read_json_file(plugin_json)
        name = name or (manifest.get("name") if isinstance(manifest.get("name"), str) else None)
        description = description or (
            manifest.get("description") if isinstance(manifest.get("description"), str) else None
        )

    return {
        "id": cap_id,
        "kind": kind,
        "path": rel,
        "name": name,
        "description": description,
        "components": capability_components(cap_dir, is_skill_root),
    }


def find_source_capabilities(root):
    """Every adoptable Capability inside one Source tree.

    Skills are outermost-wins: once a directory is claimed by its SKILL.md,
    its subtree belongs to it. The repository root is also considered on its
    own, because a repo can be one plugin while still shipping the individual
    skills inside it as separate Capabilities.
    """
    found = []
    seen_paths = set()

    def add(cap_dir, kind=None):
        cap = describe_source_capability(root, cap_dir, kind)
        if cap["path"] in seen_paths:
            return
        seen_paths.add(cap["path"])
        found.append(cap)

    if (root / ".claude-plugin" / "plugin.json").is_file():
        add(root, "plugin")

    def walk(directory, depth):
        if depth > SOURCE_SCAN_MAX_DEPTH or len(found) >= SOURCE_SCAN_MAX_CAPS:
            return
        if (directory / "SKILL.md").is_file():
            add(directory)
            return  # its subtree belongs to it, not to a nested Capability
        if directory.name == "hooks" and (directory / "hooks.json").is_file():
            add(directory, "hook")
            return
        try:
            entries = sorted(directory.iterdir(), key=lambda p: p.name)
        except OSError:
            return
        for entry in entries:
            if len(found) >= SOURCE_SCAN_MAX_CAPS:
                return
            if not entry.is_dir() or entry.name.startswith(".") or entry.name in SKIP_DIR_NAMES:
                continue
            if not _resolves_inside(entry, root):
                continue
            walk(entry, depth + 1)

    walk(root, 1)
    found.sort(key=lambda c: (c["path"] != ".", c["kind"] != "plugin", c["id"]))
    return found


def _normalize_upstream_path(value):
    if not value:
        return "."
    cleaned = str(value).strip().strip("/")
    if cleaned.startswith("./"):
        cleaned = cleaned[2:]
    return cleaned or "."


def library_adoption_index():
    """Two lookups from the Library: by (source, upstream path), and by Id.

    Provenance is the real answer to "is this already adopted" — it is the
    recorded link back to the Source. The Id lookup is the fallback that
    catches a Capability adopted before provenance was written down, and a
    genuine Id collision between two Sources, both of which the Explore page
    has to show differently from "not adopted".
    """
    by_provenance = {}
    by_id = {}
    for cap in list_capabilities():
        entry = {
            "id": cap["id"],
            "bucket": cap["bucket"],
            "status": cap["status"],
            "revision": None,
            "source": None,
        }
        prov = cap.get("provenance")
        if isinstance(prov, dict):
            entry["revision"] = prov.get("revision")
            entry["source"] = prov.get("source")
            source_name = prov.get("source")
            if source_name:
                by_provenance[(source_name, _normalize_upstream_path(prov.get("path")))] = entry
        by_id.setdefault(cap["id"], entry)
    return by_provenance, by_id


def annotate_adoption(cap, source_name, pinned_revision, by_provenance, by_id):
    """Attach how (and whether) this Source Capability is already in the Library."""
    key = (source_name, _normalize_upstream_path(cap["path"]))
    entry = by_provenance.get(key)
    match = "provenance" if entry else None
    if entry is None:
        entry = by_id.get(cap["id"])
        match = "id" if entry else None

    cap["adopted"] = None
    cap["adopted_match"] = match
    if entry is None:
        return cap

    cap["adopted"] = {
        "id": entry["id"],
        "bucket": entry["bucket"],
        "status": entry["status"],
        "revision": entry["revision"],
        # The Library copy was taken at a Revision this Source has since moved
        # past. That is a Change review decision, not something Explore acts on.
        "behind_source": bool(
            match == "provenance" and entry["revision"] and pinned_revision
            and entry["revision"] != pinned_revision
        ),
    }
    return cap


def explore_sources():
    """The Explore payload: every Source, its discovered Capabilities, and
    which of them are already Library copies."""
    data = load_sources()
    sources = data.get("sources", {}) or {}
    by_provenance, by_id = library_adoption_index()

    out = []
    for name in sorted(sources):
        entry = sources[name] or {}
        root = source_root_dir(name, entry)
        record = {
            "name": name,
            "url": entry.get("url"),
            "revision": entry.get("revision"),
            "path": entry.get("path") or f"sources/{name}",
            "present": root is not None,
            "capabilities": [],
        }
        if root is not None:
            record["capabilities"] = [
                annotate_adoption(cap, name, entry.get("revision"), by_provenance, by_id)
                for cap in find_source_capabilities(root)
            ]
        out.append(record)

    payload = {"sources": out, "buckets": sorted(list_bucket_names())}
    if data.get("error"):
        payload["error"] = data["error"]
    return payload


def source_capability_detail(name, rel_path):
    """One Source Capability with its previewable docs, or None."""
    data = load_sources()
    sources = data.get("sources", {}) or {}
    if name not in sources:
        return None
    entry = sources[name] or {}
    root = source_root_dir(name, entry)
    if root is None:
        return None
    cap_dir = resolve_source_path(root, rel_path)
    if cap_dir is None:
        return None

    cap = describe_source_capability(root, cap_dir)
    by_provenance, by_id = library_adoption_index()
    annotate_adoption(cap, name, entry.get("revision"), by_provenance, by_id)
    cap["source"] = name
    cap["source_url"] = entry.get("url")
    cap["source_revision"] = entry.get("revision")
    cap["docs"] = list_doc_files(cap_dir)
    cap["repo_path"] = str(cap_dir.relative_to(ROOT))
    return cap


def source_capability_dir(name, rel_path):
    """The on-disk directory behind a Source Capability, for doc serving."""
    entry = (load_sources().get("sources", {}) or {}).get(name)
    if entry is None:
        return None
    root = source_root_dir(name, entry)
    if root is None:
        return None
    return resolve_source_path(root, rel_path)


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

        if route == "/api/explore":
            return self._send_json(explore_sources())

        if route == "/api/source-capability":
            name = self._param(query, "source")
            rel = self._param(query, "path") or "."
            if not name:
                return self._send_json({"error": "source query param is required"}, 400)
            detail = source_capability_detail(name, rel)
            if detail is None:
                return self._send_json({"error": "source capability not found"}, 404)
            return self._send_json(detail)

        if route == "/api/source-file":
            name = self._param(query, "source")
            rel = self._param(query, "path") or "."
            doc = self._param(query, "name")
            if not name or not doc:
                return self._send_json({"error": "source and name query params are required"}, 400)
            cap_dir = source_capability_dir(name, rel)
            if cap_dir is None:
                return self._send_json({"error": "source capability not found"}, 404)
            return self._send_doc(cap_dir, doc)

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
            return self._send_doc(cap_dir, name)

        return self._send_json({"error": "not found", "path": route}, 404)

    def _send_doc(self, cap_dir, name):
        """Serve one documentation file from inside cap_dir, or a JSON error.

        Shared by the Library and the Explore previews so both go through the
        same containment check — a Source tree is upstream's content and gets
        no more trust than a Library copy.
        """
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

    def _read_json_body(self):
        """Parse a JSON request body, or send an error and return None."""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._send_json({"error": "invalid Content-Length"}, 400)
            return None
        if length <= 0:
            self._send_json({"error": "a JSON body is required"}, 400)
            return None
        if length > MAX_BODY_BYTES:
            self._send_json({"error": "request body too large"}, 413)
            return None
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            self._send_json({"error": f"body is not valid JSON: {e}"}, 400)
            return None
        if not isinstance(body, dict):
            self._send_json({"error": "body must be a JSON object"}, 400)
            return None
        return body

    def _route_post(self, route, query):
        # Secondary guard only; the Origin check in _dispatch is what stops
        # CSRF. Every state-changing route below shells out to the CLI.
        if self.client_address[0] not in ("127.0.0.1", "::1"):
            return self._send_json({"error": "forbidden"}, 403)

        if route == "/api/check":
            if not CHECK_LOCK.acquire(blocking=False):
                return self._send_json(
                    {"ok": False, "error": "a check is already running; wait for it to finish"}, 409
                )
            try:
                payload, status = run_check()
            finally:
                CHECK_LOCK.release()
            return self._send_json(payload, status)

        if route == "/api/adopt":
            body = self._read_json_body()
            if body is None:
                return None
            return self._route_adopt(body)

        if route == "/api/install":
            return self._run_locked(["install"], INSTALL_TIMEOUT_SECONDS)

        return self._send_json({"error": "not found", "path": route}, 404)

    def _route_adopt(self, body):
        """Validate an adopt request, then let `cli/skima adopt` do the work.

        The checks here are for a clear error message, not for safety: the CLI
        re-validates every one of them, and it is the CLI's screening that is
        load-bearing, since it is also what a terminal invocation goes through.
        """
        source = str(body.get("source") or "").strip()
        upstream = _normalize_upstream_path(body.get("path"))
        bucket = str(body.get("bucket") or "").strip()
        kind = str(body.get("kind") or "").strip()
        cap_id = str(body.get("id") or "").strip()

        if not source or not bucket:
            return self._send_json({"ok": False, "error": "source and bucket are required"}, 400)
        if not _is_safe_segment(bucket) or bucket == "deprecated":
            return self._send_json({"ok": False, "error": f"'{bucket}' is not a usable Bucket name"}, 400)
        if kind and kind not in VALID_KINDS:
            return self._send_json({"ok": False, "error": f"unknown kind '{kind}'"}, 400)
        if cap_id and not _is_safe_segment(cap_id):
            return self._send_json({"ok": False, "error": f"'{cap_id}' is not a usable Id"}, 400)
        if source_capability_dir(source, upstream) is None:
            return self._send_json(
                {"ok": False, "error": f"'{upstream}' is not a directory inside source '{source}'"}, 404
            )

        args = ["adopt", source, upstream, "--bucket", bucket]
        if kind:
            args += ["--kind", kind]
        if cap_id:
            args += ["--id", cap_id]
        return self._run_locked(args, ADOPT_TIMEOUT_SECONDS)

    def _run_locked(self, args, timeout):
        """Run one CLI command under WRITE_LOCK; 409 if another is in flight."""
        if not WRITE_LOCK.acquire(blocking=False):
            return self._send_json(
                {"ok": False, "error": "another adopt or install is already running"}, 409
            )
        try:
            payload, status = run_cli(args, timeout)
        finally:
            WRITE_LOCK.release()
        return self._send_json(payload, status)


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
