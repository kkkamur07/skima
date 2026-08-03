# Skima

**Skima** (skill management) is a personal control plane for owning, grouping, and installing agent capabilities — skills, hooks, plugins, agents — across coding agents (Cursor, Claude Code, and others) from one git-backed library.

It replaces ad hoc copying of skills into `~/.cursor/skills` or `~/.claude/skills` with a single **Monorepo** you curate, version, and install from in one shot.

See `CONTEXT.md` for the full domain language (Capability, Bucket, Source, Adoption, Install, etc.) and `docs/adr/` for the decisions behind this layout.

## Layout

```
cli/        Command-line surface: check/sync Sources, install to detected Agents.
web/        Local-only Web UI: Source list, Change review, browse Buckets/Status.
library/    The curated Library — source of truth for what gets installed.
sources/    Tracked upstream repos, committed as flat trees pinned to a Revision.
docs/adr/   Architecture decision records for Skima itself.
backups/    Pre-reorg recovery snapshot. Gitignored — local only.
CONTEXT.md  Domain language / glossary for this project.
sources.json  The Source list: url + pinned Revision per tracked repo.
todo.md     Deferred and in-flight work.
.skima/     Derived Source status from the last check. Gitignored, per-machine.
```

### `library/`

Capabilities are grouped by **Bucket** (domain of use), one home per Capability. Buckets are user-defined and evolving — added, split, and renamed as the Library grows, so this list is a snapshot rather than a fixed enum:

```
library/
  academic/ architecture/ learning/ ops/ planning/
  python/ quality/ review/ security/ thinking/ web/
  deprecated/   # Status = deprecated, nested by bucket; never installed
```

Each Capability lives at `library/<bucket>/<id>/` and is an editable **Library copy** — upstream Source changes never overwrite it silently; you accept updates deliberately via Change review.

Alongside each Capability's own files sits a **Capability record**, `.skima.json`, holding its Id, Kind, Bucket, Status, and Provenance. Kind and Provenance live only there; Id, Bucket, and Status are also encoded in the path, and **the directory wins** if the two ever disagree — a mismatched record is a validation warning, never an override. See `docs/adr/0004-capability-record-and-directory-authority.md`.

### `sources/`

One directory per tracked upstream GitHub repo, committed as a flat tree (no nested `.git`, no submodules) at a pinned Revision. `sources.json` records the URL and Revision for each. This is what Change review compares against when a Source moves ahead of its pin.

## Quickstart

Nothing to install — the CLI is bash + `python3`, and the Web UI is Python stdlib with no build step. Run both from a fresh clone.

**Install** (push the Library into detected Agents):

```bash
./cli/skima install
```

This detects installed Agents by their config directory (Cursor via `~/.cursor`, Claude Code via `~/.claude`, plus the shared `~/.agents/skills` convention) and materializes every `active` Capability into each, symlinking to the `library/` copy where possible and falling back to a file copy otherwise. **Agents that are not installed are skipped, and no directory is created for them.** Run `./cli/skima targets` first to see what would be written to.

**Check Source freshness** (compare each pinned Revision to its remote head):

```bash
./cli/skima check     # git ls-remote, no clone; writes .skima/status.json
./cli/skima status    # pretty-print the last check
```

**Sync a Source** (refresh a tracked tree to a newer Revision):

```bash
./cli/skima sync [name...]    # all Sources when given no names
```

Sync refreshes `sources/<name>/` and updates the pin in `sources.json`. It never touches `library/` — bringing an upstream change into a Library copy is **Adoption**, a deliberate step.

`./cli/skima help` documents all eight commands, the `NO_COLOR` and `SKIMA_NETWORK_TIMEOUT` environment variables, and the exit codes. See `cli/README.md` for the full reference.

**Web UI** (browse the Library, review Source freshness):

```bash
python3 web/server.py        # http://127.0.0.1:4567
```

Binds loopback only and is not hosted. It reads the Library and Sources, and its one write action — the "Run check" button — shells out to `skima check`, which makes network calls and rewrites `.skima/status.json`. See `web/README.md`.

## Backups

A pre-reorg snapshot of this workspace lives in `backups/20260803-144647/`. It is **gitignored** — 113M of archives plus six embedded upstream clones that git would otherwise turn into empty phantom submodules. It is a local recovery point, not tracked history:

- `repos-workdir/` — the original `repos/` tree (pre-migration source clones)
- `skills-use-workdir/` — the original `skills-use/` tree (pre-migration curated skills)
- `skills-use.zip` — the original zip archive
- `repos.tar.gz`, `skills-use.tar.gz`, `dot-cursor-skills.tar.gz`, `dot-agents-skills.tar.gz` — compressed snapshots
- `dot-claude-skills.MISSING.txt` — records that `~/.claude/skills` did not exist at snapshot time
- `nested-git/humanizer-dot-git.tar.gz` — the `.git` removed from the humanizer Library copy
- `source-revisions.txt` — the Source Revisions pinned at snapshot time
- `CONTEXT.md`, `todo.md`, `docs/` — point-in-time copies

Nothing in `backups/` is touched by day-to-day Skima use; it's the recovery point if the migration into `sources/`/`library/` needs to be redone. Because it is gitignored, it lives on this machine only — treat it as such.
