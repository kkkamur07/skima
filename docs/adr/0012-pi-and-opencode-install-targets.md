# ADR-0012: Detect Pi and OpenCode as Install targets

## Status

Accepted

## Context

Skima already installs active Library Capabilities into detected coding agents. Pi and OpenCode both consume Agent Skills, but each has a native global resource directory that is distinct from the shared `~/.agents/skills` convention.

## Decision

Add Pi and OpenCode to the CLI's known Install targets:

- Pi: detect `$PI_CODING_AGENT_DIR` or `~/.pi/agent`; install into its `skills/` child.
- OpenCode: detect `$XDG_CONFIG_HOME/opencode` or `~/.config/opencode`; install into its `skills/` child.

Detection remains conservative: Skima only creates the `skills/` child after the parent Agent directory already exists. The shared `~/.agents/skills` target remains available independently.

## Consequences

- `skima targets` and `skima install` now report and materialize capabilities for Pi and OpenCode when those Agents are installed.
- Existing users without either Agent see both targets as skipped and no new directories are created.
- Environment overrides make the target paths usable for non-default Pi and XDG configurations.
