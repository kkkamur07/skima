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

If you use more than one agent, or more than one machine, ad hoc skill folders drift. You lose track of what is installed, copies diverge quietly, and an upstream update can overwrite a local edit before you notice.

Skima treats `library/` as the source of truth, and upstream stays pinned under `sources/`. You adopt what you want into a Bucket, edit those Library copies freely, and install only the active ones. Clone the repo onto a new machine, run install again, and you are back to the same set.

Updates stay deliberate rather than automatic. `skima check` tells you which Sources have moved, Change review shows what is behind, and adopting something never overwrites a Library copy you already have.

## How to use it?

You need git and python3. The CLI is bash calling python3, and the Web UI runs on the Python standard library, so there is no `pip install` and no build step.

### On a new machine

```bash
git clone git@github.com:kkkamur07/skima.git
cd skima
./cli/skima targets    # see which Agents Skima detected
./cli/skima install    # symlink (or copy) every active Capability into them
```

Install looks for Cursor (`~/.cursor`), Claude Code (`~/.claude`), Pi (`~/.pi/agent`), OpenCode (`~/.config/opencode`, or `$XDG_CONFIG_HOME/opencode`), and the shared `~/.agents/skills` convention. If an Agent is not installed, Skima skips it and never creates a directory for it.

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

The server binds to loopback only. From there you can browse Sources, explore adoptable Capabilities, inspect the Library by Bucket, and run a check. Adopting or installing from the UI runs the same CLI commands.

### Layout notes

Capabilities live at `library/<bucket>/<id>/`, with a `.skima.json` record for Kind and Provenance. Id, Bucket, and Status come from the directory path; if the record disagrees, the directory wins.

Deprecated Capabilities sit under `library/deprecated/` and are never installed.

`sources.json` lists every tracked upstream URL and its pinned revision. Two directories are local to the machine and gitignored: `.skima/`, which holds the result of the last check, and `backups/`, a local recovery snapshot.
