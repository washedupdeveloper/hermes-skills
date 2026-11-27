---
name: request-refactor-plan
description: "Use before a refactor: interview, scope, tiny commits."
version: 1.0.0
author: "Matt Pocock (mattpocock/skills, request-refactor-plan), adapted for Hermes"
license: MIT
platforms: [linux, macos, windows]
category: software-development
metadata:
  hermes:
    tags: [refactor, planning, scope, commits, interview]
    source: mattpocock/skills@main
    related_skills: [grill-me, to-spec, to-tickets, codebase-design]
writes: [none]
side_effects: [none]
scope_answers: ["how to scope a refactor before starting"]
scope_triggers: [plan a refactor, scope a refactor first]
scope_out: [judging module shape (codebase-design), the smallest fix instead (surgical-patch)]
---

# Request Refactor Plan

Turn "this needs a refactor" into a plan someone can execute and check. The interview half overlaps
`grill-me` — use this when the *output* must be a plan with a scope boundary and a commit sequence,
not just shared understanding.

## Steps

1. **Ask for the problem, at length.** What hurts, with examples, and any solution ideas already
   held. Do not start from the solution.
2. **Verify the claims in the repository.** Every assertion in step 1 gets checked against the code:
   the function really is 900 lines, the flag really is unused, the module really has no test. An
   unverified premise is how a refactor fixes the wrong thing.
3. **Ask what else was considered** — and put other options on the table yourself. A refactor with
   one candidate is a preference, not a decision.
4. **Interview the implementation.** Exact seams, exact vocabulary (`codebase-design`), exact
   behaviour that must not change.
5. **Hammer out the scope.** Two lists, written down: what changes, and what explicitly does not.
   The second list is the one that gets violated.
6. **Check the tests before promising the plan.** If the area has no coverage, say so and agree what
   the testing plan is *before* the first commit — a refactor with no tests is a rewrite with
   plausible deniability.
7. **Break it into commits a reader can follow.** Each step small enough that the program still works
   at every commit ("make each refactoring step as small as possible, so that you can always see the
   program working" — Fowler). A commit that half-moves a module is a commit that cannot be bisected.

## The plan document

```markdown
# Refactor: <what is being reshaped>

## Problem
<the pain, with file:line evidence, not adjectives>

## What changes
- <module/seam> — why

## What does not change
- <behaviour, artefact, public interface> — why it is out of scope

## Tests
<what exists, what is added first, what proves the refactor changed nothing it should not>

## Commit sequence
1. <smallest step that leaves the program working>
2. ...

## How we will know
<the command(s) that decide it — exit codes, not prose>
```

## When it is a rewrite, not a refactor

A refactor edits in place and the tests are the reference. A **rewrite** replaces a working
implementation and has no reference until you make one: freeze the old outputs first, enumerate the
differences you intend, and compare the two implementations on the same inputs. See
`references/differential-rewrite.md` for the freeze, the thin first slice, the three outcomes, and the
attribution rules a rewrite has to re-derive rather than inherit.

## Rules that outrank style

- **Never mix behaviour changes into a refactor commit.** If a bug is found, note it; fix it
  separately. Mixed commits cannot be reviewed or reverted independently.
- **No step longer than a session.** If a step cannot be finished and left working, split it.
- **The scope list is binding.** Additions need their own plan, not a footnote.
- **Delete before adding.** The cheapest refactor is the code that stops existing.

## Pitfalls

1. Planning the destination instead of the next commit.
2. "While we're here" — the phrase that doubles a diff.
3. Trusting a test suite that has never been seen to fail.
4. Refactoring a module nobody calls, because it is easy to refactor.
5. Writing the plan after the code, then calling it a plan.

## Verification

- [ ] Every problem claim is backed by a file:line
- [ ] Alternatives were considered and one was chosen for a stated reason
- [ ] The "does not change" list exists and is longer than one line
- [ ] Test coverage was checked before the plan was agreed
- [ ] Each commit step leaves the program working