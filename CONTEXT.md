# Skima

**Skima** (skill management) is a personal control plane for owning, grouping, and installing agent capabilities across coding agents from one git-backed library.

## Language

**Skima**:
The product name for this **Control plane** (CLI + local Web UI + Library + tracked Sources).
_Avoid_: skill manager, skills app, control panel

**Control plane**:
The personal system that owns the canonical library and installs versioned capabilities into coding agents in one shot. In this project, the **Control plane** *is* **Skima**.
_Avoid_: control panel, control pane, marketplace, registry (for v1)

**Library**:
The curated collection of **Library copies** the user maintains as source of truth for what can be installed. Lives at `library/` in the **Monorepo**, grouped by **Bucket**.
_Avoid_: marketplace, catalog (prefer Library for the owned store)

**Monorepo**:
This workspace as a single GitHub repository containing **Skima** (`cli/`, `web/`), the **Library** (`library/`), and **Sources** (`sources/`) as committed trees.
_Avoid_: workspace (too vague), apps/ nesting (rejected for simplicity)

**Source**:
An upstream GitHub repository **Skima** tracks. Its tree is committed under `sources/<name>/` at a pinned **Revision** (no nested `.git`, no submodules).
_Avoid_: remote (too git-generic), marketplace, registry

**Revision**:
The version of a **Capability** or **Source** pin — a git commit SHA (optionally a branch/tag that resolves to one). The **Monorepo** itself is also versioned by its own git history on GitHub.
_Avoid_: semver, release number (not used for v1 versioning)

**Check**:
Comparing a **Source**'s pinned **Revision** to its remote HEAD (via `git ls-remote`, no clone) to see if it's `up-to-date`, `behind`, or `unreachable`; the **CLI**'s `skima check` writes this to local `.skima/status.json`.
_Avoid_: poll, sync (sync refreshes the tree; **Check** only compares shas)

**Agent**:
A coding tool installed on the machine that can consume capabilities from the **Library** (e.g. Cursor, Claude Code, Codex).
_Avoid_: IDE (too narrow), coding agent product (verbose)

**Install target**:
An **Agent** **Skima** has detected on the machine and will attempt to install into.
_Avoid_: destination, sink

**Bucket**:
An evolving, user-defined primary home for a **Capability**, grouped by domain of use (e.g. academic, web, python, thinking, security, review, architecture, quality, planning, ops, learning). On disk: `library/<bucket>/<id>/`. Buckets are added and renamed as the **Library** grows — not a fixed enum.
_Avoid_: category, folder (too generic), tag (tags are cross-cutting, not the primary home)

**Status**:
The lifecycle of a **Capability**: `active` or `deprecated`. Active entries live under `library/<bucket>/`; deprecated entries live under `library/deprecated/<bucket>/`. Location on disk is authoritative: a **Capability record** that disagrees with its directory is a validation error, never an override.
_Avoid_: state, maturity, in-progress (not a Status value for v1)

**Capability**:
A single versioned entry in the **Library** that **Skima** can install into an **Install target**.
_Avoid_: skill (when meaning the umbrella unit), package, module, item

**Kind**:
The shape of a **Capability**: `skill`, `hook`, `plugin`, or `agent`. Install behavior differs by **Kind**; Library management (Bucket, Status, version) does not.
_Avoid_: type, format

**Adoption**:
The deliberate act of placing a **Capability** from a **Source** into the **Library** under a chosen **Bucket** (with provenance and a pinned **Revision**).
_Avoid_: install (install is Library → Agent), import, sync (sync refreshes Sources)

**Change review**:
A UI presentation of what changed in a **Source** (or in an already-adopted **Capability**) since the last pinned **Revision**, so the user can decide what to adopt or update.
_Avoid_: diff viewer (implementation), changelog (may feed the review but is not the concept)

**Library copy**:
The editable files of an adopted **Capability** owned inside the **Library**. **Adoption** creates a **Library copy**; upstream changes never overwrite it without an explicit decision in **Change review**.
_Avoid_: fork (ambiguous with git forks), vendor (implementation slang), pin (pins are for **Revision** provenance only)

**Id**:
The stable name of a **Capability** in the **Library** and on **Install targets**. For **Capabilities** adopted from a **Source**, **Id** matches the upstream identity (e.g. `socratic-method`). For Library-authored **Capabilities**, the user chooses the **Id**. The directory name carries the **Id**; the **Capability record** must agree with it. A `name` in the capability's own frontmatter is upstream display text, not the **Id** — where upstream ships a divergent one (e.g. `vercel-react-best-practices` under `react-best-practices/`), **Id** fidelity to the upstream *directory* wins and the frontmatter is left untouched.
_Avoid_: slug, key, folder name (folder layout may follow **Id** but is not the concept)

**Provenance**:
The link from an adopted **Capability** to its **Source** (repo, upstream path, last-reviewed **Revision**). Used by **Change review** to match updates. A Library-authored **Capability** has no **Provenance**; that absence is recorded explicitly (`null`), not left implicit.
_Avoid_: origin, remote metadata

**Capability record**:
The per-**Capability** metadata file at `library/<bucket>/<id>/.skima.json`. It is where **Id**, **Kind**, **Bucket**, **Status**, and **Provenance** are written down — the four facts every **Capability** must have plus its **Source** link. Its presence also marks a directory as a **Capability**, so discovery never has to guess from file globs (which would otherwise mistake a nested translation such as `docs/de/SKILL.md` for a second **Capability**). Where the record and the directory layout disagree about **Id**, **Bucket**, or **Status**, the directory wins and the mismatch is reported.
_Avoid_: manifest (upstream capabilities ship their own), frontmatter (that is upstream's, not Skima's), sidecar

**Source status**:
The recorded result of a **Check** for one **Source** — `up-to-date`, `behind`, or `unreachable` — as of when that **Check** ran. **Check** is the act of comparing; **Source status** is what it wrote down. Lives in `.skima/status.json`, which is derived, per-machine, and never committed, so a **Source status** is always as stale as the last **Check**. It tells **Change review** which **Sources** are worth reviewing; it is not itself the review.
_Avoid_: sync state, health (too broad), drift

**Source list**:
The inventory of **Sources** **Skima** is tracking — visible in the **Web UI** so the user can see exactly which repositories feed **Change review**.
_Avoid_: bookmarks, remotes list

**CLI**:
The command-line surface of **Skima** for machine actions: sync **Sources**, install to **Install targets**, and other automation. Lives at `cli/`.
_Avoid_: terminal app

**Web UI**:
The local-only browser surface of **Skima** for **Source list**, **Change review**, and browsing **Buckets** / **Status**. Lives at `web/`. Not hosted in v1.
_Avoid_: dashboard, app, SaaS

**Install**:
The act of making **Library** **Capabilities** available on an **Install target**. Default materialization is a **symlink** (shortcut) from the Agent path to the **Library copy**; if a symlink cannot be used, fall back to a file **copy**.
_Avoid_: deploy, publish, sync (sync is for Sources)

## Relationships

- **Skima** *is* the **Control plane**
- **Skima** is one **Monorepo**: `cli/`, `web/`, `library/`, `sources/`
- A **Library** is the source of truth **Skima** installs from
- **Skima** discovers zero or more **Agents** and treats each as an **Install target**
- Cursor and Claude Code are expected **Install targets**; other **Agents** are included only when detected
- Cursor global skills path: `~/.cursor/skills`. Claude Code global skills path: `~/.claude/skills` (created on first **Install** if missing)
- Day-1 seed (done, 2026-08-03): the former `repos/` seeded `sources/` and the former `skills-use/` seeded `library/` by **Bucket**; both original trees now live only under `backups/`, and `~/.cursor/skills` is reconciled by **Install** (it was never a second Library)
- Every **Capability** has exactly one **Id**, belongs to exactly one **Bucket**, has exactly one **Status**, and has exactly one **Kind**
- Every **Capability** has exactly one **Capability record**, which is where those four facts and its **Provenance** are written; the directory layout is authoritative wherever the two disagree
- A **Check** compares each **Source**'s pinned **Revision** to its remote head and records a **Source status**; that status is derived, per-machine state, so it is never committed
- **Install target** detection is real: **Skima** writes only to **Agents** it finds on the machine, and never creates a skills directory for an **Agent** that is not installed
- A **Library** contains many **Capabilities** and many evolving **Buckets**
- **Skima** tracks zero or more **Sources** (shown in the **Source list**); sync refreshes committed trees under `sources/` to a newer **Revision**
- A **Capability** may originate from a **Source** (via **Adoption**) or be authored directly in the **Library**
- **Adoption** is curated: new upstream material appears in **Change review**, not automatically in the **Library**
- An adopted **Capability** is always a **Library copy** (editable), keeps upstream **Id**, and carries **Provenance**
- After **Adoption** or an accepted upstream update into the **Library copy**, **Skima** runs **Install** across all **Install targets**
- **Install** prefers symlink to the **Library copy**; copy is fallback only
- **Install** includes every **Capability** with Status `active`; deprecated **Capabilities** are never installed
- **Skima** exposes both a **CLI** and a local **Web UI** over the same **Library** and **Sources**

## Out of scope (v1)

- Open-ended search, validate, and suggest of *unknown* external skills — deferred
- Per-Capability semver — deferred; **Revision** is git-based
- Read-only pins as the installable body — rejected; **Library copy** is the body
- Divergent local **Ids** for adopted **Capabilities** — rejected; align to upstream **Id**
- Hosted / multi-user **Web UI** — deferred; local-only
- Split repos or local-only Source cache — rejected; one **Monorepo**
- Git submodules or nested `.git` under `sources/` — rejected
- Nested `apps/` package layout — rejected for simplicity
- Copy-first **Install** — rejected; symlink-first with copy fallback
- Selected / profile-based **Install** sets — deferred; v1 is all **active**

## Flagged ambiguities

_(none)_


## Example dialogue

> **Dev:** "If I add a Cursor hook, is that a Skill?"
> **Domain expert:** "No — it's a **Capability** of **Kind** `hook`. Same **Bucket** and **Status** rules as a skill; only the install path changes."

> **Dev:** "Can a Capability sit in both academic and python?"
> **Domain expert:** "No — one **Bucket** home. Cross-cutting labels are tags if we add them; they are not a second home."

> **Dev:** "When Matt ships a new skill, does my Library update automatically?"
> **Domain expert:** "No. The **Source** sync feeds **Change review**. You **Adopt** (or update) deliberately; then install propagates to every **Install target**."

> **Dev:** "If I edit grill-with-docs locally and Matt changes it upstream, what wins?"
> **Domain expert:** "Your **Library copy** wins until you accept changes in **Change review**. Upstream never silently overwrites."

> **Dev:** "I installed socratic-thinking but upstream is socratic-method — which Id do we keep?"
> **Domain expert:** "Upstream **Id** `socratic-method`. The local rename was a mistake to correct at **Adoption**."

> **Dev:** "This skill's frontmatter says `vercel-react-best-practices` but the folder is `react-best-practices`. Which is the Id?"
> **Domain expert:** "The folder. That frontmatter is upstream's display text and upstream's own inconsistency — we inherit it rather than editing it, because a local edit would show up as a phantom diff in every future **Change review**."

> **Dev:** "Where is a Capability's Kind actually written down?"
> **Domain expert:** "Its **Capability record**, `.skima.json`. **Kind** and **Provenance** live only there. **Id**, **Bucket** and **Status** are in there too, but the directory wins if they ever disagree."

> **Dev:** "I moved something into library/deprecated/ but its record still says active. Does it get installed?"
> **Domain expert:** "No. The directory is authoritative, so it's deprecated and **Install** skips it. The stale record is a validation warning to fix, not a vote."

> **Dev:** "`skima check` says a Source is behind. Is that the Change review?"
> **Domain expert:** "No — that's a **Source status**, the result of a **Check**. It tells you a **Source** moved past its pin, which is what makes it worth reviewing. The review itself is where you see what changed and decide."

> **Dev:** "Where do I see what repos I'm tracking?"
> **Domain expert:** "The **Source list** — every **Source** under `sources/` that feeds **Change review**."

> **Dev:** "Do I manage this in the browser or the terminal?"
> **Domain expert:** "Both, locally: **CLI** for sync/install; **Web UI** for **Source list**, **Change review**, and browsing."

> **Dev:** "Is the Library a separate GitHub repo from the app?"
> **Domain expert:** "No — one **Monorepo**: `cli/`, `web/`, `library/`, `sources/`."

> **Dev:** "When I install, do Agents get a second copy of every skill?"
> **Domain expert:** "No — **Install** symlinks to the **Library copy** when it can; copy is only the fallback."

> **Dev:** "Do I pick which skills get installed?"
> **Domain expert:** "Not in v1. **Install** pushes every **active** **Capability**; deprecate to keep something out."
