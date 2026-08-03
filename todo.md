# Todo

## Scaffold complete (2026-08-03)

- [x] `sources/` populated from `repos/` (flat trees, no nested `.git`); `sources.json` records url + pinned revision per Source
- [x] `library/` seeded from `skills-use/`, grouped into Buckets (academic, engineering, learning, python, thinking, web, deprecated)
- [x] `CONTEXT.md`, `docs/adr/` (0001 monorepo-includes-sources, 0002 install-symlink-first) in place
- [x] Old working trees moved into `backups/20260803-144647/`: `repos/` → `repos-workdir/`, `skills-use/` → `skills-use-workdir/`, `skills-use.zip` → same backup dir (compressed `.tar.gz` snapshots already lived there)
- [x] Root `README.md`, `.gitignore`, and `.gitkeep` placeholders for empty Buckets (`library/academic`, `library/learning`, `library/deprecated`) and empty app dirs (`cli/`, `web/`) added
- [ ] `cli/` and `web/` are empty scaffolds — implementation is separate, in-flight work (not part of this housekeeping pass)
- [ ] Two untracked top-level skill folders (`atomic-decomposition/`, `deep-research/`) predate this reorg and were not migrated into `sources/`/`library/` — needs a decision on whether to adopt, discard, or fold into an existing Source

## Deferred

- [ ] Benchmark agent performance with skills vs without skills (methodology, metrics, fixtures, and how results feed back into the Library)
- [ ] Open-ended search / validate / suggest for unknown external skills (distinct from Source Change review + curated Adoption)
- [ ] Hosted / multi-user Web UI
- [ ] Cross-cutting tags (if still wanted after Buckets prove enough)
- [ ] Selected / profile-based Install sets (v1 = all active only)
- [ ] Optional launchd/cron wrapper that only runs `skima check` (not required for correctness)
- [ ] Full Change review diffs + adopt-from-UI (v1: Updates page lists behind Sources; sync stays CLI)
