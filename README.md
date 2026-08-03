# Skima

**Skima** (skill management) is a personal control plane for owning, grouping, and installing agent capabilities — skills, hooks, plugins, agents — across coding agents (Cursor, Claude Code, and others) from one git-backed library.

It replaces ad hoc copying of skills into `~/.cursor/skills` or `~/.claude/skills` with a single **Monorepo** you curate, version, and install from in one shot.

See `CONTEXT.md` for the full domain language (Capability, Bucket, Source, Adoption, Install, etc.) and `docs/adr/` for the decisions behind this layout.

## Layout

```
cli/        Command-line surface: sync Sources, install to detected Agents.
web/        Local-only Web UI: Source list, Change review, browse Buckets/Status.
library/    The curated Library — source of truth for what gets installed.
sources/    Tracked upstream repos, committed as flat trees pinned to a revision.
docs/adr/   Architecture decision records for Skima itself.
CONTEXT.md  Domain language / glossary for this project.
todo.md     Deferred and in-flight work.
```

`cli/` and `web/` are currently scaffolded but not yet implemented — that work happens separately.

### `library/`

Capabilities are grouped by **Bucket** (domain of use), one home per Capability:

```
library/
  academic/
  engineering/
  learning/
  python/
  thinking/
  web/
  deprecated/   # capabilities with Status = deprecated (never installed)
```

Each Capability lives at `library/<bucket>/<id>/` and is an editable **Library copy** — upstream Source changes never overwrite it silently; you accept updates deliberately via Change review.

### `sources/`

One directory per tracked upstream GitHub repo, committed as a flat tree (no nested `.git`, no submodules) at a pinned revision. `sources.json` records the URL and revision for each. This is what Change review diffs against when a Source updates.

## Backups

A pre-reorg snapshot of this workspace lives in `backups/20260803-144647/`, including:

- `repos-workdir/` — the original `repos/` tree (pre-migration source clones)
- `skills-use-workdir/` — the original `skills-use/` tree (pre-migration curated skills)
- `skills-use.zip` — the original zip archive
- `repos.tar.gz`, `skills-use.tar.gz`, `dot-cursor-skills.tar.gz`, `dot-agents-skills.tar.gz` — compressed snapshots
- `source-revisions.txt`, `CONTEXT.md`, `todo.md`, `docs/` — point-in-time copies of the docs above

Nothing in `backups/` is deleted by day-to-day Skima use; it's the recovery point if the migration into `sources/`/`library/` needs to be redone.

## Quickstart

> `cli/` and `web/` are not implemented yet. Once they are, the intended flow is:

**Install** (push the Library into detected Agents):

```bash
cd cli
# install deps, then:
skima install
```

This detects installed Agents (Cursor at `~/.cursor/skills`, Claude Code at `~/.claude/skills`, ...) and materializes every `active` Capability into each, symlinking to the `library/` copy where possible and falling back to a file copy otherwise.

**Web UI** (browse the Library, review Source changes):

```bash
cd web
# install deps, then:
npm run dev
```

Opens a local-only UI for the Source list, Change review, and browsing Buckets/Status. Not hosted — runs on your machine only.

**Sync a Source** (refresh a tracked repo to a newer revision, surfaced in Change review):

```bash
skima sync <source-name>
```
