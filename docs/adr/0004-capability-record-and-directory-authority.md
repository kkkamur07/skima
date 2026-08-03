# Capability facts live in `.skima.json`, but the directory is authoritative

Every **Capability** must have exactly one **Id**, **Bucket**, **Status**, and **Kind**, and every adopted one must carry **Provenance**. Nothing in the upstream files carries those facts: a capability's own frontmatter is upstream's, written for the agent that consumes it, and it neither knows nor cares about Skima's Library model.

We considered inferring everything from the directory layout alone (`library/<bucket>/<id>/`). That covers Id, Bucket, and Status, but there is nowhere to put Kind or Provenance — and Provenance is the fact **Change review** depends on. We also considered a single central index file, and rejected it: it turns every adoption into an edit of one contended file, and it goes stale silently the moment anyone moves a directory by hand.

We chose a per-Capability **Capability record** at `library/<bucket>/<id>/.skima.json` holding `id`, `kind`, `bucket`, `status`, and `provenance` (explicitly `null` for Library-authored entries). It travels with the capability, so moving a directory moves its metadata.

That creates a real hazard: Id, Bucket, and Status are now encoded twice, in the path and in the record, and nothing forces them to agree. A stale `"status": "active"` inside `library/deprecated/` would otherwise mean a deprecated capability gets installed — exactly what **Status** exists to prevent. So the tie-break is fixed and applies everywhere: **the directory wins**. A disagreeing record is a validation error to report, never an override to honor. Kind and Provenance have no directory counterpart, so for those the record is the only source.

The record also marks a directory as a Capability. Discovery keys off its presence rather than globbing for `SKILL.md`, which would wrongly count nested files such as `library/thinking/socratic-method/docs/de/SKILL.md` as separate Capabilities.

Consequence: both the CLI and the Web UI must apply the same precedence rule, and both must surface mismatches rather than silently resolving them.
