# Install pushes every active Capability; deprecate to opt out

**Install** needs a rule for which **Capabilities** reach which **Install targets**. The tempting answer is per-target selection: profiles, per-Agent sets, an include list.

We deferred all of it for v1. Selection state is a second source of truth that has to be stored, kept in sync with the Library as things are added and renamed, and reconciled per target — and the whole point of this tool is installing everything in one shot rather than curating per machine. Skima is personal and single-user; the Library *is* the selection, curated at **Adoption** time.

We chose: Install materializes every Capability with **Status** `active` into every detected Install target. Nothing under `library/deprecated/` is ever installed.

**Status** is therefore the opt-out mechanism. Keeping something out of your Agents means deprecating it — moving it to `library/deprecated/<bucket>/<id>/` — which keeps it in the Library, in git, and re-adoptable, rather than deleting it. Per ADR-0004 the directory decides this, so a stale record cannot resurrect a deprecated Capability into a target.

Consequence: every Agent gets an identical set. If per-target sets are ever wanted, they arrive as an explicit profile concept layered on top of this default, not by weakening it.
