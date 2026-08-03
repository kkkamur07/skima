---
name: pr-review-hitl
description: >-
  Full PR review with human-in-the-loop gate. Invokes code-review-and-quality
  (five-axis review) in full, then adds a sixth axis — a tailored human
  verification todo list. Use when reviewing pull requests, posting PR
  comments, preparing stacked PRs for merge, or when the user asks for HITL
  review, human verification checklist, or pr-review-hitl.
---

# PR Review with Human-in-the-Loop (HITL)

## Overview

This skill runs a **complete PR review** in two phases:

1. **Phase 1 — Five-axis review:** Invoke `code-review-and-quality` in full. Follow every step, severity label, checklist item, and output convention in that skill. Do not skip or summarize it.
2. **Phase 2 — Sixth axis (HITL):** Generate a **tailored human verification todo list** for this PR only — things only a human can judge.

**Merge rule:** Autonomous verification green + five-axis blockers resolved + human completes every tailored todo (or N/A with rationale). An agent **must not** mark a PR merge-ready on behalf of the human.

## When to Use

- Reviewing a pull request before merge
- Posting a review comment on GitHub (`gh pr comment`)
- After an agent or author opens a stacked PR (<1000 lines)
- When the user asks for HITL review or a human verification checklist

## Phase 0: PR Context (before review)

Ensure the PR has enough description for reviewers. If missing, ask the author to add or draft it in your review comment.

Required PR context:

| Field | What to include |
|-------|-----------------|
| **Intent** | What this PR is for and which issue/spec it implements |
| **Scope** | What is in / out of this PR (especially for stacked PRs) |
| **Expected behavior** | What should work differently after merge (user-visible and API) |
| **Stack position** | Base branch and what must merge first (if stacked) |
| **Author test plan** | Commands run + any manual steps the author already did |

If the PR description is thin, flag it as a **required** finding before merge.

## Phase 1: Invoke code-review-and-quality

**Read and follow** `code-review-and-quality` (`~/.cursor/skills/code-review-and-quality/SKILL.md`) in full:

1. Understand context (issue, spec, expected behavior change)
2. Review tests first
3. Review implementation on all five axes
4. Categorize findings with severity labels (`Critical:`, required, `Nit:`, `Optional:`, `FYI`)
5. Verify the verification story
6. Use the review checklist and verdict format from that skill

Run autonomous checks yourself where possible (tests, build, diff against base). Record results under **Autonomous verification** — not under human todos.

**Do not modify** `code-review-and-quality`. This skill extends it; it does not replace or patch it.

## Phase 2: Sixth axis — Human verification (HITL)

After Phase 1, generate **3–8 tailored checklist items** for human reviewers. Derive them from:

- Issue acceptance criteria vs what the PR actually changes
- Diff risk map (auth, migrations, pairing/ground truth, canvas, jobs, public API)
- Behaviors changed but not credibly covered by tests, or tests removed/weakened
- Claims in the PR description (e.g. "no UX change" → human visual check)

### What belongs in human verification only

Include an item only if **a human must** do it:

- Product / spec judgment
- Subjective UX (flow clarity, editor/canvas feel, misleading labels)
- Visual / interaction intent
- Domain semantics (research workflow meaning — pairing vs review, GT lifecycle, etc.)
- Scope / stack judgment (unrelated changes in this PR?)
- Risk acceptance (explicit sign-off to ship with a known deferral)
- Targeted intent read of **named high-risk files** (not "read the full diff")

### What must NOT appear in human verification

Do **not** duplicate autonomous work:

- `pytest`, `npm test`, lint, typecheck, `docker compose`, migrations, seed scripts
- "Tests pass", "build succeeds", "OpenAPI regenerated"
- Generic "read the diff" or "verify edge cases" without naming the risky behavior
- Five-axis findings already covered in Phase 1 (link those instead)

Each item must be: **specific action** + **what to look for**. Cap at 8 items.

If nothing human-only applies:

```markdown
### Human verification
**N/A** — No human-only checks identified for this PR. Autonomous verification and five-axis review suffice.
```

## Output format

Post one review comment (e.g. `gh pr comment`) using this structure. Phase 1 sections follow `code-review-and-quality`; Phase 2 is appended.

```markdown
## Review: [PR title] (PR #N)

### PR context
- **Intent:** …
- **Expected behavior:** …
- **Scope / stack:** …
- **Description adequate:** yes | no — [what's missing]

### Context
[Phase 1 — from code-review-and-quality]

### Correctness
[findings with severity labels]

### Readability
[findings]

### Architecture
[findings]

### Security
[findings]

### Performance
[findings]

### Autonomous verification
*(CI / agent — not the human reviewer)*
- [ ] [command or check run or expected in CI]
- [ ] …

### Human verification
*(Tailored — human must check before merge)*
- [ ] [Specific action + what to look for]
- [ ] …

*Or:* **N/A** — [one sentence why]

### Verdict
**Approve** / **Request changes** — [code review rationale only]
**Human verification:** pending | N/A | complete *(human fills "complete" — agent never does)*
```

Human sign-off (posted by human, not agent):

```markdown
## Human verification complete
- Checked: [items]
- Skipped / N/A: [items + why]
- Verdict: approve merge | request changes
```

## Review agent prompt

Use this when launching a PR review:

```
Review PR #[N] on branch [branch] (base: [base]).

1. Read and follow code-review-and-quality in full (~/.cursor/skills/code-review-and-quality/SKILL.md).
   Do not skip any step. Do not modify that skill.

2. Apply pr-review-hitl (~/.cursor/skills/pr-review-hitl/SKILL.md):
   - Ensure PR has intent, scope, expected behavior, stack position.
   - Run five-axis review + autonomous verification.
   - Add sixth axis: Human verification — 3–8 tailored checklist items for this PR ONLY.

Rules for Human verification:
- Include ONLY what a human must judge: product/spec calls, subjective UX,
  visual/interaction intent, domain semantics, scope/stack decisions, risk
  acceptance, or targeted reads of named high-risk files.
- Do NOT include: pytest, npm test, docker compose, migrations, lint,
  "tests pass", or generic "read the diff".
- Each item: specific action + what to look for.
- If none apply, say "N/A" with one sentence why.
- Do NOT mark the PR merge-ready on behalf of the human.

3. Verdict — Approve / Request changes for the CODE review only.
   Add: "Human verification pending" unless N/A.

4. Post the review via gh pr comment [N].
```

## Workflow

```
Checkout PR branch
    │
    ▼
Read PR description + linked issue
    │
    ▼
Phase 1: code-review-and-quality (full)
    │
    ▼
Phase 2: Generate tailored human todos (3–8)
    │
    ▼
Post review comment on PR
    │
    ▼
Author fixes code blockers → human completes HITL todos → merge
```

## Example (frontend extract PR)

```markdown
### Human verification
- [ ] Open page editor on a real document: confirm pairing strip and toolbar expose the same actions as before.
- [ ] Process → auto-segment: click through once; judge whether behavior matches researcher expectation (integration tests were removed).
- [ ] Visually confirm toolbar layout is acceptable — PR claims refactor only; verify no confusing control placement.

### Verdict
**Request changes** — restore auto-segment test coverage.
**Human verification:** pending
```

## See also

- `code-review-and-quality` — five-axis review (Phase 1; invoke in full, do not edit)
- `git-workflow-and-versioning` — stacked PRs, <1000 line sizing
