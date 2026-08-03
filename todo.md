# Todo

## Scaffold complete (2026-08-03)

- [x] `sources/` populated from `repos/` (flat trees, no nested `.git`); `sources.json` records url + pinned Revision per Source
- [x] `library/` seeded from `skills-use/`, grouped into Buckets
- [x] `CONTEXT.md`, `docs/adr/` (0001 monorepo-includes-sources, 0002 install-symlink-first, 0003 check-via-ls-remote) in place
- [x] Old working trees moved into `backups/20260803-144647/`: `repos/` → `repos-workdir/`, `skills-use/` → `skills-use-workdir/`, `skills-use.zip` → same backup dir
- [x] Root `README.md`, `.gitignore`, and `.gitkeep` placeholders for empty Buckets added
- [x] `cli/` and `web/` implemented — eight CLI commands, and a stdlib Web UI with Source list, Change review and Library browsing
- [x] The two stray top-level skill folders adopted into Buckets (see below)

## Audit fixes (2026-08-03)

Findings from a conformance audit against `CONTEXT.md`, and what was done.

- [x] **Repo initialized.** The Monorepo had no `.git` at all — nothing was actually committed or versioned.
- [x] **Nested `.git` removed** from `library/thinking/humanizer` — a live clone git would have committed as a phantom gitlink, leaving the Capability empty in every clone. Archived to `backups/.../nested-git/` first.
- [x] **`.gitignore` negations added** (`!/sources/**`, `!/library/**`). The generic rules match at every depth and were silently stripping 9 `.log` files out of a Source tree that must be committed verbatim at its pinned Revision — Change review would have diffed against a corrupted baseline forever. `backups/` excluded (113M, 6 embedded clones).
- [x] **Provenance backfilled** on 26 adopted Capabilities (was 1 of 31). Without it every adopted Capability was invisible to Change review. Origin re-derived by hashing each Library `SKILL.md` against every Source `SKILL.md`. The 7 Library-authored entries keep an explicit `null`.
- [x] **humanizer adopted properly** — upstream registered as the 8th Source at `523374de`, Kind corrected `skill` → `plugin` (it ships a `.claude-plugin` manifest).
- [x] **Strays adopted.** `deep-research` → `library/academic/`, `atomic-decomposition` → `library/thinking/`. Both sat at the repo root, belonging to zero Buckets, invisible to both Install and the UI.
- [x] **Install target detection made real.** The CLI created `~/.cursor/skills` and `~/.claude/skills` unconditionally — a user without Cursor got a full symlink tree under a directory Skima invented. Detection is now the Agent's own config dir.
- [x] **Install made atomic.** `rm -rf dest && mv tmp dest` destroyed the destination if interrupted between the two. Now stage → rename old aside → move new in → discard, with rollback and a path guard on every mutation inside a target.
- [x] **Web UI security.** The POST guard checked `client_address`, which any cross-site request from the user's own browser satisfies; there was no `Host` validation, so DNS rebinding could read the whole API. Both fixed, plus a single-flight lock and CSP/nosniff headers. A symlinked doc file could also escape containment — the final path is now resolved and re-checked.
- [x] **Change review named correctly** in the UI (was "Updates", invented vocabulary) and its nav route fixed.
- [x] **Directory made authoritative** for Id/Bucket/Status in both surfaces, so a stale record can no longer install a deprecated Capability or produce dead links.
- [x] **Docs corrected.** `README.md` claimed `cli/` and `web/` were "not yet implemented" while both were fully working, told users to run `npm run dev` against a project with no `package.json`, and invoked `skima` as if it were on `PATH`.
- [x] **ADRs 0004–0009** written for decisions `CONTEXT.md` presented as settled but that had no record.
- [x] **`CONTEXT.md` gaps closed** — it required every Capability to have an Id, Kind, Bucket, Status and Provenance without saying where any of them are written down, and left Id and Status encoded twice with no tie-break.
- [x] **`engineering` Bucket split** into architecture, ops, planning, quality, review and security; it had grown into a catch-all holding 17 of 33 Capabilities.
- [x] **Agent directories reconciled.** Running install against the real machine surfaced three entries Skima did not manage. `teach` and `diagnose` were byte-identical to tracked upstream and were adopted into the Library; `socratic-thinking` (an older copy of socratic-method under the wrong Id) and a loose top-level `SKILL.md` were stale duplicates and were removed from `~/.cursor/skills`, archived first at `backups/20260803-144647/unmanaged-cursor-skills/`. All three targets are now 100% Skima-managed: 35 symlinks each, no foreign entries, no broken links.

## Open

- [ ] **Change review is freshness-only.** It shows per-Source pinned-vs-remote Revision from the last check — real data, but not yet "what changed". No file-level diff, no Library-copy drift against the provenance Revision, and no adopt/update actions; those remain CLI work. This is the largest remaining gap against the `CONTEXT.md` definition.
- [ ] **`deep-research` is a divergent, stale ancestor** of the `academic-research-skills` copy (6-phase single skill vs upstream's 13-agent pipeline). Adopted as-is with provenance recorded; decide whether to accept upstream, keep the local version, or merge.
- [ ] **`improve-codebase-architecture` is deliberately divergent** (upstream's HTML-report step stripped). Provenance now records the baseline, so this is a Change review decision rather than an invisible edit.
- [ ] **No Codex Install target.** `CONTEXT.md` names Codex as an example Agent but defines no skills path for it. Not invented; a one-line addition to the CLI's agent table once the path is known.
- [ ] **Copy-fallback entries are never auto-removed** when a Capability is deprecated — indistinguishable from a directory the user created, so they are reported and left alone. Symlinks into this Library are provably Skima-created and *are* cleaned up.
- [ ] `library/web/react-best-practices` inherits upstream's frontmatter `name: vercel-react-best-practices`, so Skima and the consuming Agent report different names for it. Left alone deliberately (ADR-0006); revisit only if it causes real confusion.
- [ ] The CLI's "not managed" report lists only directories, so a loose *file* dropped into a target is reported but easy to miss as a malformed capability rather than an ordinary foreign entry.
- [ ] No git remote configured — the Monorepo has local history only, and `backups/` is gitignored, so both exist on this machine alone.

## Deferred

- [ ] Benchmark agent performance with skills vs without skills (methodology, metrics, fixtures, and how results feed back into the Library)
- [ ] Open-ended search / validate / suggest for unknown external skills (distinct from Source Change review + curated Adoption)
- [ ] Hosted / multi-user Web UI
- [ ] Cross-cutting tags (if still wanted after Buckets prove enough)
- [ ] Selected / profile-based Install sets (v1 = all active only)
- [ ] Optional launchd/cron wrapper that only runs `skima check` (not required for correctness)
- [ ] Full Change review diffs + adopt-from-UI (v1: Change review lists behind Sources; sync stays CLI)
