# Adopted Capabilities keep the upstream Id

When a **Capability** is adopted from a **Source**, its **Id** could be anything the user likes — the **Library copy** is ours to edit, so nothing technically stops a rename.

We rejected divergent local Ids. **Provenance** matches a Library copy back to an upstream path so **Change review** can tell what moved; a local rename adds a translation step to every future review, and the mapping only exists in the one file that recorded it. The cost is paid forever, at every sync, for a one-time cosmetic preference. A rename had already happened once here — a capability installed as `socratic-thinking` against upstream `socratic-method` — and correcting it at adoption was straightforwardly the right call.

We chose: adopted Capabilities keep the upstream Id, taken from the upstream *directory* name. Only Library-authored Capabilities get a user-chosen Id.

This is deliberately about the directory, not the capability's frontmatter. Upstream sometimes ships a `name` that differs from its own directory — `sources/vercel-agent-skills/skills/react-best-practices/SKILL.md` declares `vercel-react-best-practices`. Adopting it as `react-best-practices` is correct: the directory is what Provenance points at and what Change review diffs. Editing the frontmatter to match would create a gratuitous local divergence from upstream, and every future review would have to carry it as a permanent phantom diff. So the frontmatter is left exactly as upstream wrote it, and it is treated as display text rather than as the Id.

Consequence: for such a Capability, Skima and the consuming Agent will report different names for the same thing. That inconsistency is upstream's, and inheriting it is cheaper than owning a fork of it.
