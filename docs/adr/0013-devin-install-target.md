# ADR-0013: Detect Devin as an Install target

## Status

Accepted

## Context

Devin ships a local CLI that consumes Agent Skills in the open `SKILL.md` format, so a Library Capability installs into it without conversion. Its global resource directory is XDG-style: `$XDG_CONFIG_HOME/devin`, defaulting to `~/.config/devin`. There is no `~/.devin` globally, so the XDG directory is the only honest detection signal. Devin also reads `~/.agents/skills`, which the shared agents target already covers, but that target is a convention rather than Devin's own directory and is skipped on machines that do not have it.

Project-local, Devin reads `.agents/skills`, `.devin/skills` and `.windsurf/skills`, so an upstream repository may ship a skill inside `.devin/skills/`. Adoption screens dot-prefixed path segments and would otherwise refuse such a path.

## Decision

Add Devin to the CLI's known Install targets, following the pattern ADR-0012 set for Pi and OpenCode:

- Devin: detect `$XDG_CONFIG_HOME/devin` or `~/.config/devin`; install into its `skills/` child.

Detection remains conservative: Skima only creates the `skills/` child after the Agent's configuration directory already exists, and never creates that configuration directory.

Add `.devin` to the Agent home directories Adoption and Explore may pass through, alongside `.claude`, `.cursor` and `.agents`. The allowlist stays mirrored between `cli/skima` and `web/server.py`; every other dot-prefixed segment stays rejected, and Buckets and Ids keep the stricter rule.

## Consequences

- `skima targets` and `skima install` now report and materialize capabilities for Devin when it is installed.
- Users without Devin see the target as skipped and no new directories are created.
- `$XDG_CONFIG_HOME` makes the target path usable for non-default XDG configurations, and the same variable already steers OpenCode, so both move together.
- A Capability shipped upstream under `.devin/skills/<id>` is adoptable and visible in Explore.
