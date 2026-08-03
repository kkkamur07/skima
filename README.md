# Skima

## What is this?

Skima (skill management) is a personal control plane for agent capabilities. You keep skills, hooks, plugins, and agents in one git-backed library, then install them into Cursor, Claude Code, and other coding agents from that single place.

Instead of copying files into `~/.cursor/skills` or `~/.claude/skills` by hand, you curate a monorepo and push the active set out with one command.

The repo has four working parts:

```
library/    Curated copies you own. This is what gets installed.
sources/    Upstream repos, committed as flat trees at a pinned revision.
cli/        Check, sync, adopt, and install.
web/        Local browser UI for Sources, Explore, Library, and Change review.
```

Domain vocabulary lives in `CONTEXT.md`. Design decisions live in `docs/adr/`.

## Why is this valuable to me?

If you use more than one agent, or more than one machine, ad hoc skill folders drift. You lose track of what is installed, copies diverge, and upstream updates overwrite local edits without warning.

Skima treats `library/` as the source of truth. Upstream stays pinned under `sources/`. You adopt what you want into a Bucket, edit those Library copies freely, and install only active entries. On a new machine you clone this repo and run install again.

You also get a deliberate update path: `skima check` tells you which Sources moved, Change review shows what is behind, and Adoption never silently rewrites a Library copy.

## How to use it?

You need git and python3. The CLI is bash plus python3. The Web UI is Python stdlib. There is no `pip install` and no build step.

### On a new machine

```bash
git clone git@github.com:kkkamur07/skima.git
cd skima
./cli/skima targets    # see which Agents Skima detected
./cli/skima install    # symlink (or copy) every active Capability into them
```

Install looks for Cursor (`~/.cursor`), Claude Code (`~/.claude`), and the shared `~/.agents/skills` convention. Agents that are not installed are skipped. No directories are invented for missing Agents.

### Day to day

```bash
./cli/skima check              # compare pinned revisions to remote HEADs
./cli/skima status             # print the last check
./cli/skima sync [name...]     # refresh Source trees; leave Library alone
./cli/skima adopt <source> <path> --bucket <bucket>   # copy into Library
./cli/skima install            # push Library into detected Agents
./cli/skima help               # full command reference
```

Local UI:

```bash
python3 web/server.py          # http://127.0.0.1:4567
```

The UI binds loopback only. Use it to browse Sources, Explore adoptable Capabilities, inspect the Library by Bucket, and run a check. Adoption and install from the UI call the same CLI commands.

### Layout notes

Capabilities live at `library/<bucket>/<id>/`, with a `.skima.json` record for Kind and Provenance. Id, Bucket, and Status come from the directory path; if the record disagrees, the directory wins.

Deprecated Capabilities sit under `library/deprecated/` and are never installed.

`sources.json` lists every tracked upstream URL and pinned revision. `.skima/` is local machine state from the last check and is gitignored. `backups/` is a local recovery snapshot and is also gitignored.
