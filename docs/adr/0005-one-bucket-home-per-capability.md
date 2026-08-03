# One Bucket home per Capability, not multi-membership

A **Capability** is grouped by domain of use, and some genuinely sit across two — a Postgres performance ruleset is both `python` and `web` depending on why you reached for it.

We considered letting a Capability belong to several **Buckets**, and rejected it for v1. Multi-membership means the Library has no single canonical path for a Capability, which breaks the thing the layout is for: `library/<bucket>/<id>/` being a stable, predictable location that Install, Change review, and a human browsing the tree all agree on. It also forces an index to answer "where does this live", which ADR-0004 rejected for separate reasons.

We chose exactly one Bucket per Capability, expressed as its parent directory. Buckets stay user-defined and evolving — added and renamed freely as the Library grows — so the cost of picking the wrong home is a `mv`, not a migration.

Cross-cutting labels are a different concept and remain deferred. If tags arrive later they will be additive metadata on the **Capability record**, never a second home; the Bucket stays the primary.

Consequence: some placements will read as arbitrary — `supabase-postgres-best-practices` under `python` while `supabase` sits under `web`, both from the same **Source**. That is accepted. "Domain of use" is a judgment call, and being able to re-file with a directory move is what keeps the wrong call cheap.
