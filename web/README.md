# Skima Web UI

The local-only browser surface of **Skima**: the **Source list**, **Change
review**, and browsing the **Library** by **Bucket** and **Status**. Reads
`../sources.json`, `../.skima/status.json`, and scans `../library/` straight
off disk on every request — no database, no build step, no dependency to
install.

It is not purely read-only. `POST /api/check` runs `cli/skima check` as a
subprocess, which reaches the network (`git ls-remote` against every tracked
**Source**) and rewrites `../.skima/status.json`. Everything else — the
**Source list**, the **Library** scan, doc previews — only reads local files.

Adoption, sync, and install stay in the **CLI**. There is no adopt or update
button here.

## Run

Stdlib-only Python 3 server, no `pip install` required.

```bash
# from web/
python3 server.py

# or from the repo root
python3 web/server.py

# optional: pick a different port (default 4567)
python3 server.py 8080
```

Then open http://127.0.0.1:4567 in a browser. Stop with `Ctrl+C`.

The server binds 127.0.0.1 only, and every request must carry a `Host` header
naming that loopback address and the port it is bound to (see Security below),
so it is reachable from this machine and nothing else.

## Pages

- **Sources** (`#/sources`) — every entry in `sources.json`: name, upstream
  URL, pinned **Revision**, path under `sources/`, plus the check state from
  the last `skima check` (Up to date / Behind / Unreachable / Unknown) and the
  remote SHA. A **Run check** button invokes `cli/skima check` and re-renders.
- **Library** (`#/library`) — every **Bucket** on disk, including ones with no
  **Capability** in them yet, each listing its **Capabilities**. The directory
  layout is authoritative: `library/<bucket>/<id>/` is `active`,
  `library/deprecated/<bucket>/<id>/` is `deprecated`. Selecting a Capability
  shows its **Kind**, **Provenance** (source, repository, upstream path,
  last-reviewed **Revision**) or a "Library-authored — no provenance" note,
  and a preview of any documentation file it contains, including files in
  subdirectories such as `references/`.
- **Change review** (`#/review`; the older `#/updates` link still resolves
  here) — which tracked **Sources** have moved past their pinned **Revision**,
  from the last `skima check`. The page states its own scope: it compares
  pinned SHAs to remote HEADs and nothing more. It does not yet show the
  file-level changes behind a Source that is behind, and it does not yet
  compare an adopted **Library copy** against its provenance **Revision**.

## Metadata conflicts

A Capability's **Id**, **Bucket**, and **Status** come from where its directory
sits, never from `.skima.json`. If `.skima.json` disagrees — for example a
stale `"status": "active"` on a Capability that now lives under
`library/deprecated/` — the directory wins and the disagreement is reported as
a warning: a marker beside the Capability in the list, and a warning panel in
its detail view. `kind` and `provenance` are read from `.skima.json`, since
they are not encoded in the layout. The **CLI** applies the same rule.

## HTTP API

- `GET /` `/index.html` `/app.js` `/style.css` — the static page.
- `GET /api/sources` — contents of `sources.json`.
- `GET /api/buckets` — `{"buckets": {"<bucket>": [<capability>, ...]}}`, with
  an entry for every Bucket directory, empty ones included.
- `GET /api/capability?bucket=&id=&status=` — one Capability: `id`, `bucket`,
  `kind`, `status`, `provenance`, `path`, `warnings`, and `docs` (relative
  paths of the previewable files). `status=deprecated` selects the
  `library/deprecated/` copy.
- `GET /api/file?bucket=&id=&status=&name=` — one documentation file's text.
  `name` is a path relative to the Capability directory, as listed in `docs`.
- `GET /api/status` — contents of `.skima/status.json` if present, else
  `{"checked_at": null, "sources": {}, "message": "Run skima check"}`.
- `POST /api/check` — runs `cli/skima check` (cwd = repo root), waits up to
  120s, and returns the refreshed status. One check at a time: a second
  concurrent request gets `409` rather than spawning another subprocess.
  Degrades gracefully (JSON error plus an output snippet) if the CLI is
  missing, exits non-zero, or times out.

Every response carries `X-Content-Type-Options: nosniff`, a `default-src
'none'` **Content-Security-Policy**, `X-Frame-Options: DENY`,
`Referrer-Policy: no-referrer`, and `Cache-Control: no-store`. Any unhandled
error becomes a JSON body with an HTTP status, not a dropped connection.

## Security

The server runs on a developer machine while a browser is open on other sites,
so it defends against those sites:

- **Host allowlist, every request.** `Host` must be `127.0.0.1:<port>`,
  `localhost:<port>`, or `[::1]:<port>`. A domain that rebinds DNS to
  127.0.0.1 still sends its own name in `Host`, so it cannot read any `/api/*`
  response. No CORS headers are ever sent either.
- **Origin check on state-changing requests.** `POST /api/check` requires an
  allowed `Origin`; if `Origin` is absent it accepts `Sec-Fetch-Site:
  same-origin` or `none`; if neither header is present (a non-browser client
  such as `curl`) it requires `X-Skima-Request: 1`, a header no cross-origin
  page can set without a CORS preflight that this server never answers. The
  loopback source-IP test it replaced was not a CSRF defense: a cross-site POST
  from the user's own browser also comes from 127.0.0.1.
- **Single-flight check.** Overlapping `POST /api/check` requests cannot pile
  up `git ls-remote` subprocesses.
- **Path containment for `/api/file`.** Each path segment is screened (no `..`,
  no separators, no control or NUL bytes), the filename must look like
  documentation (`.md`, `.markdown`, `.txt`, `LICENSE`, `NOTICE`,
  `.skima.json`), and the fully resolved path must still be inside the
  Capability directory — so a symlink pointing out of the Library is neither
  listed nor served.

## `.skima/status.json` contract

Written by `cli/skima check` / `cli/skima sync`, read by `GET /api/status`:

```json
{
  "checked_at": "2026-08-03T22:00:45Z",
  "sources": {
    "<source name>": {
      "url": "<upstream url>",
      "pinned": "<sha>",
      "remote": "<sha or null>",
      "status": "up-to-date | behind | unreachable",
      "error": "<short detail or null>"
    }
  }
}
```

A **Source** missing from `"sources"` (e.g. added after the last check) has no
recorded status; the Web UI shows it as "Unknown".

## Files

```
web/
  server.py    # stdlib http.server + JSON API
  index.html   # shell page, hash-routed nav
  app.js       # views for Sources / Library / Change review
  style.css    # dark theme, badges, toolbars
  README.md    # this file
```
