# Skima CLI

The command-line surface of Skima. It tracks Source freshness, refreshes Source trees, and installs every
active Capability from the Library into the Install targets it detects on this machine.

See `../CONTEXT.md` for the domain model (Capability, Bucket, Status, Source, Revision, Install target,
Library copy).

## Commands

```bash
cli/skima check          # compare each Source's pinned Revision to its remote HEAD; write .skima/status.json
cli/skima sync [name...] # refresh Source tree(s) from remote HEAD; update sources.json; merge into status.json
cli/skima status         # pretty-print .skima/status.json
cli/skima install        # install every active Capability into each detected Install target
cli/skima list           # list active Capabilities with their Bucket, plus Library validation warnings
cli/skima targets        # show which Agents were detected and which were skipped
cli/skima root           # print the monorepo root
cli/skima help           # show usage
```

Exit codes: `0` success, `1` operational failure, `2` usage error, `3` a required program
(`git`, `rsync`, `python3`) is not on PATH.

## `check` — is a Source behind?

`check` runs `git ls-remote <url> HEAD` (falling back to `refs/heads/main` / `refs/heads/master`) for every
entry in `sources.json` and compares the result to the pinned `revision`. No clone, no cron needed for
correctness.

```
Check — pinned Revision vs remote HEAD

SOURCE                    PINNED        REMOTE        STATUS
academic-research-skills  49e79a7c9929  49e79a7c9929  up-to-date
agent-skills              d187883b7d76  bdf76c7c6b7b  behind
mattpocock-skills         2bf700519284  2ab958093e83  behind

3 Sources   1 up-to-date   2 behind

Wrote .skima/status.json
```

- Writes `.skima/status.json` — local machine state, not tracked in git. One entry per Source with `url`,
  `pinned`, `remote` (or `null`), `status` (`up-to-date` | `behind` | `unreachable`), and `error` (or
  `null`), alongside a top-level `checked_at` timestamp.
- The `.skima/` directory is created on demand by `check` and `sync`; there is nothing to scaffold.
- Exits `0` even when some Sources are behind. Exits `1` only when every Source is unreachable, and `2`
  when `sources.json` is missing or unparseable.

Cron or launchd is optional. `check` is cheap enough to run on demand. If you want a background nudge, wrap
it in your own scheduled job and read `.skima/status.json`. The Web UI reads that file directly rather than
triggering checks itself.

## `sync` — refresh a Source tree

```bash
cli/skima sync                                # every Source
cli/skima sync agent-skills mattpocock-skills # just these
```

For each named Source (or all, with no arguments), `sync`:

1. Resolves the remote HEAD sha (the same `git ls-remote` call `check` uses).
2. Shallow-clones the Source's `url` at that HEAD into a temp directory.
3. `rsync`s the tree into `sources/<name>/`, excluding `.git` and `.DS_Store`, deleting anything no longer
   present upstream.
4. Updates that Source's `revision` in `sources.json` to the new sha.
5. Re-checks just those Sources and merges the result into `.skima/status.json`.

`sync` only ever touches `sources/<name>/` and `sources.json`. It never writes into `library/`. Adoption —
choosing what from a Source becomes a Library copy — stays a deliberate, separate step.

## `status`

Pretty-prints `.skima/status.json` with a per-Source table, a count per status, and any recorded errors.
If the file does not exist yet it tells you to run `check` first and exits `0`.

## `install`

### What gets installed

A Capability is a directory at exactly `library/<bucket>/<id>/` containing `.skima.json` (preferred) or
`SKILL.md`. Discovery is anchored at that depth, so support material nested inside a Capability — for
example a translated `library/thinking/socratic-method/docs/de/SKILL.md` — belongs to that Capability and
is never counted as one of its own.

Install materializes every Capability with Status `active`. Deprecated Capabilities are never installed.

**The directory is authoritative** for Status, Id and Bucket:

| On disk | Status |
| --- | --- |
| `library/<bucket>/<id>/` | `active` |
| `library/deprecated/<bucket>/<id>/` | `deprecated` |

`.skima.json` records the same three facts, but it never overrides the directory. When the two disagree,
`list` and `install` print a validation warning and proceed from the directory. A stale `"status":
"active"` sitting inside `library/deprecated/` therefore cannot cause an install.

### Install targets

An Install target is an Agent Skima detected on this machine. Detection is keyed off the Agent's own
configuration directory:

| Agent | Detected when | Installs into |
| --- | --- | --- |
| Cursor | `~/.cursor` exists | `~/.cursor/skills` |
| Claude Code | `~/.claude` exists | `~/.claude/skills` |
| Pi | `~/.pi/agent` exists (or `$PI_CODING_AGENT_DIR`) | `<pi-agent-dir>/skills` |
| OpenCode | `~/.config/opencode` exists (or `$XDG_CONFIG_HOME/opencode`) | `<opencode-config>/skills` |
| Devin | `~/.config/devin` exists (or `$XDG_CONFIG_HOME/devin`) | `<devin-config>/skills` |
| Shared agents dir | `~/.agents/skills` exists | `~/.agents/skills` |

Skima creates the `skills/` subdirectory on first install if it is missing, and nothing else. It never
creates an Agent's configuration directory, so an Agent you do not have installed never gets a tree of
symlinks on your machine. `cli/skima targets` shows exactly what was detected and why anything was skipped:

```
Install targets — Agents detected on this machine

AGENT              INSTALLS INTO     DETECTION
Cursor             ~/.cursor/skills           detected (~/.cursor exists)
Claude Code        ~/.claude/skills           detected (~/.claude exists)
Pi                 ~/.pi/agent/skills         detected (~/.pi/agent exists)
OpenCode           ~/.config/opencode/skills  skipped (~/.config/opencode not found — Agent not installed)
Devin              ~/.config/devin/skills     detected (~/.config/devin exists)
Shared agents dir  ~/.agents/skills           skipped (~/.agents/skills not found — Agent not installed)

4 install targets detected   skipped Agents are never written to
```

### Symlink first, copy as fallback

Install creates a symlink from the Install target to the Library copy, so an edit in `library/` is visible
to the Agent without re-installing. Only when the symlink cannot be created does it fall back to a
recursive copy. See `../docs/adr/0002-install-symlink-first-copy-fallback.md`.

Re-running `install` is idempotent: a symlink already pointing at the right Library copy is counted
`up-to-date` and left alone. A symlink pointing somewhere stale is re-pointed.

### How replacement works

Replacing an entry never opens a window where the destination is gone and no replacement exists:

1. The new symlink (or copy) is materialized at a sibling temp path. Nothing at the destination is touched.
2. Any existing entry is moved aside with a single atomic rename.
3. The staged entry is renamed into place.
4. Only then is the entry that was moved aside discarded.

If step 3 fails, the original is renamed back. Nothing is ever removed before its replacement exists, so a
process killed partway leaves the old entry recoverable rather than gone: it is either still at the
destination or sitting beside it under a `.skima-old-<pid>` name. The two leftover shapes are
`<id>.skima-tmp-<pid>` (a staged replacement — never your data, discarded on the next install) and
`<id>.skima-old-<pid>` (a previous destination that may be its only remaining copy — reported, never
deleted, yours to inspect).

Every destructive operation is gated on the path being exactly `<known skills directory>/<one name>`, so an
empty or unexpanded variable cannot widen into a broader path.

### Entries Skima did not install

At each target, `install` reports what it found that does not match an active Capability:

- **A symlink into this monorepo's `library/`** is one Skima created. If the Capability behind it was
  deleted or deprecated, the symlink is removed and the removal is reported. Removing a symlink never
  touches the Library copy it pointed at, and this is what keeps deprecated Capabilities from lingering on
  a target.
- **Anything else** — your own directories, symlinks pointing outside the Library, and copy-fallback
  entries, which are indistinguishable from a directory you made yourself — is listed and left completely
  alone. Skima does not delete what it cannot prove it created. Removing those is a manual decision.

## Output

Color is used when stdout is a TTY and `NO_COLOR` is unset. Every command stays fully readable without it;
piped output, `NO_COLOR=1` and `TERM=dumb` all turn it off automatically.

Tables, section rules and status glyphs come from `cli/render.py`, which uses the `rich` package if it
happens to be importable. It is a presentation layer and nothing more:

- **`rich` is never required.** Skima runs from a fresh clone with nothing installed. If the import fails —
  or the render fails for any other reason — `render.py` exits `97` having written nothing, and `cli/skima`
  prints the plain output it has always printed. Nothing is auto-installed, no import error is shown, and
  no exit code changes.
- **Piped output is plain either way.** `cli/skima` passes its own TTY decision down as `SKIMA_COLOR`, and
  `render.py` pins the Console to no color system, no box drawing and a fixed 100-column width when that
  says "not a terminal" — rich's own detection is never consulted. This is what keeps `web/server.py`'s
  captured stdout readable inside a browser `<pre>`.
- **`python3` stays optional where it already was.** `install`, `list`, `targets`, `root` and `help` all
  fall back to plain output when `python3` is missing, exactly as before.

## Environment

| Variable | Effect |
| --- | --- |
| `NO_COLOR` | Set to any value to disable colored output. |
| `SKIMA_NETWORK_TIMEOUT` | Seconds each network call may take before a Source is treated as unreachable. Default `10`. |

## Requirements

Bash 3.2 or newer (the version macOS ships), plus `git` for `check`/`sync`, `rsync` for `sync`, and
`python3` for JSON handling in `check`/`sync`/`status` and for Library validation warnings. `install` works
without `python3`; it only loses the validation warnings.

The `rich` package is optional and is not declared as a dependency anywhere. Install it into whatever
Python `python3` resolves to if you want the pretty tables; skip it and everything still works.
