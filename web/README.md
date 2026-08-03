# Skima Web UI

The local-only, browse/review surface of **Skima**. Reads `../sources.json`,
`../.skima/status.json`, and scans `../library/` directly off disk on every
request — there's no database, build step, or dependency to install.

For machine actions (check/sync Sources, install to Agents), use the `cli/`
instead; the Web UI can also trigger `cli/skima check` from the **Sources**
page. This UI is otherwise read-only: **Sources**, **Library** browsing
(Buckets + Status), and **Updates** (which Sources are behind).

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

## Pages

- **Sources** (`#/sources`) — every entry in `sources.json` (name, URL, pinned
  revision, path under `sources/`), plus a check-state badge (Up to date /
  Behind / Unreachable / Unknown) and the remote SHA from the last
  `skima check`. A **Check for updates** button runs `cli/skima check` and
  refreshes the page.
- **Library** (`#/library`) — Buckets and Capability ids read from
  `library/<bucket>/<id>/` (and `library/deprecated/<bucket>/<id>/`), with
  total counts in the header. Click a capability to see its `.skima.json`
  metadata, provenance, and preview its Markdown docs (`SKILL.md`,
  `README.md`, etc.).
- **Updates** (`#/updates`, `#/review` redirects here) — lists Sources whose
  last `skima check` found them `behind`, each with a CTA:
  `Run cli/skima sync <name> in the CLI, then review Library copies`. This is
  the v1 of Change review; a full diff/adopt UI lands later. If no check has
  run yet, it prompts to run one.

## How it works

- `server.py` — `http.server`-based server with a small JSON API:
  - `GET /api/sources` — contents of `sources.json`.
  - `GET /api/capabilities`, `GET /api/buckets` — Library scan.
  - `GET /api/capability`, `GET /api/file` — one Capability's metadata / a
    safe-listed doc's contents (path-checked so requests can't escape
    `library/`).
  - `GET /api/status` — contents of `.skima/status.json` if present, else
    `{ "checked_at": null, "sources": {}, "message": "Run skima check" }`.
  - `POST /api/check` — localhost-only; spawns `cli/skima check` (cwd = repo
    root), waits up to 120s, and returns the refreshed status. Degrades
    gracefully (JSON error + stdout/stderr snippet) if the CLI is missing,
    exits non-zero, or times out — it never crashes the server.
  - `GET /api/review` — legacy stub, kept for compatibility.
- `index.html` / `app.js` / `style.css` — a single-page app with hash routing
  (`#/sources`, `#/library`, `#/updates`) and vanilla `fetch()` calls. No
  framework, no bundler.

### `.skima/status.json` contract

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

A Source missing from `"sources"` (e.g. added after the last check) has no
recorded status; the Web UI shows it as "Unknown".

## Files created

```
web/
  server.py    # stdlib http.server + JSON API (incl. /api/status, /api/check)
  index.html   # shell page, hash-routed nav
  app.js       # views for Sources / Library / Updates
  style.css    # dark theme, status badges, toolbars
  README.md    # this file
```
