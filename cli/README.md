# Skima CLI

The command-line surface of Skima: tracks Source freshness, refreshes Source trees, and installs active
Library capabilities into detected coding agents.

## Usage

```bash
cli/skima check          # compare each Source's pinned revision to its remote HEAD; write .skima/status.json
cli/skima sync [name...] # refresh Source tree(s) from remote HEAD (shallow clone + rsync); update sources.json
cli/skima status         # pretty-print .skima/status.json (run `check` first if it doesn't exist)
cli/skima install        # discover targets, install all active capabilities (symlink first, copy fallback)
cli/skima list           # list active capabilities with their bucket
cli/skima targets        # show detected install targets
cli/skima root           # print the monorepo root
```

## Checking for Source updates

**How we know a Source is updated:** `skima check` runs `git ls-remote <url> HEAD` (falling back to
`refs/heads/main` / `refs/heads/master`) for every entry in `sources.json` and compares the result to the
pinned `revision` — no clone, no cron required for correctness. This is the primary, on-demand way to see
what changed.

```bash
cli/skima check
```

```
NAME                        PINNED        REMOTE        STATUS
academic-research-skills    49e79a7c9929  49e79a7c9929  up-to-date
agent-skills                d187883b7d76  bdf76c7c6b7b  behind
mattpocock-skills           2bf700519284  2ab958093e83  behind

Wrote .skima/status.json
```

- Writes results to `.skima/status.json` (local machine state, not tracked in git — see below) with one
  entry per Source: `url`, `pinned`, `remote` (or `null`), `status` (`up-to-date` | `behind` |
  `unreachable`), and `error` (or `null`).
- Exit code: `0` even when some Sources are behind; `1` only if every Source is unreachable or
  `sources.json` is missing.
- The `.skima/` directory is created on demand by `check`/`sync` — nothing to scaffold ahead of time.
- `SKIMA_NETWORK_TIMEOUT` (seconds, default `10`) bounds how long each `git ls-remote` call waits before a
  Source is treated as unreachable.

**Cron/launchd is optional, not core.** `skima check` is correct and cheap to run on demand (a handful of
`git ls-remote` calls, no clone). If you want a background nudge, wrap it in your own `cron`/`launchd` job
that runs `skima check` on a schedule and reads `.skima/status.json` — that wrapper is scheduling sugar
on top of the CLI, not a dependency of it. The Web UI is expected to read `.skima/status.json` directly
rather than triggering checks itself.

## Refreshing a Source

```bash
cli/skima sync                          # refresh every Source
cli/skima sync agent-skills mattpocock-skills   # refresh just these
```

For each named Source (or all, with no arguments), `sync`:

1. Resolves the remote HEAD sha (same `git ls-remote` as `check`).
2. Shallow-clones the Source's `url` at that HEAD into a temp directory.
3. `rsync`s the tree into `sources/<name>/`, excluding `.git` and `.DS_Store`, deleting anything no
   longer present upstream.
4. Updates that Source's `revision` in `sources.json` to the new sha.
5. Re-runs `check` for just the synced Source(s) and merges the result into `.skima/status.json`.

`sync` only ever touches `sources/<name>/` and `sources.json` — it never writes into `library/`.
**Adoption** (choosing what from a Source becomes a Library copy) stays a deliberate, separate step; sync
refreshing a Source is not the same as adopting its changes.

## Status

```bash
cli/skima status
```

Pretty-prints `.skima/status.json` if it exists; otherwise tells you to run `cli/skima check` first.

## Installing into Agents

- Reads capabilities from `library/<bucket>/<id>/` (skips `library/deprecated/`). A directory counts as a
  capability only if it has `SKILL.md` or `.skima.json` at its root — nested docs (e.g. `.../<id>/docs/`)
  are not installed separately.
- Install targets: `~/.cursor/skills` and `~/.claude/skills` (created if missing). `~/.agents/skills` is
  also used when it already exists on the machine.
- Install prefers a symlink to the Library copy; if symlinking fails, it falls back to a recursive copy.
- Existing non-symlink entries at a target are replaced with a symlink only after the replacement has been
  staged successfully (safe swap, no data loss on failure).
- Entries at a target that don't match any active capability id are reported but never touched.

## Output

- Color is used when stdout is a TTY and `NO_COLOR` is unset; every command stays fully readable with
  color off (piped output, `NO_COLOR=1`, or `TERM=dumb` all disable it automatically).
- `skima help` lists every command, including `check`/`sync`/`status`.

See `../CONTEXT.md` for the full domain model (Capability, Bucket, Source, Revision, Check, Status, Install
target, etc.) and `../docs/adr/0003-source-check-via-ls-remote-not-cron.md` for why Source freshness is
detected on demand instead of via a required background job.
