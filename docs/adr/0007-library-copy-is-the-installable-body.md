# The Library copy is the installable body, not a read-only pin

Skima tracks **Sources** at a pinned **Revision**, so the obvious design is to install straight from the pinned upstream tree and keep `library/` as nothing but a list of pointers.

We rejected that. The point of owning a Library is being able to edit what you install — trim a step, adapt wording, drop a section that doesn't apply. A read-only pin makes every local change either impossible or a fork maintained somewhere else, which is the ad hoc situation Skima exists to replace. One capability here is already deliberately divergent: `library/engineering/improve-codebase-architecture` has upstream's HTML-report step removed on purpose.

We chose: **Adoption** creates an editable **Library copy** under `library/<bucket>/<id>/`, and that copy is what **Install** materializes. The pinned Revision is recorded as **Provenance** rather than used as the body.

Upstream therefore never silently overwrites a Library copy. A Source moving ahead of its pin surfaces in **Change review** as something to decide about; accepting it is an explicit act. Between adoption and acceptance the local copy simply wins.

**Revision** stays a git commit SHA throughout, for both Sources and Provenance — not semver. Skima tracks arbitrary upstream repositories, most of which publish no releases at all, and a SHA is the only identifier that always exists and always resolves to exactly one tree.

Consequence: a divergent Library copy without recorded Provenance is unreviewable — Change review has no baseline to diff against. Provenance is what makes local edits safe, so it is required on every adopted Capability rather than best-effort.
