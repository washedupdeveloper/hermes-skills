# The council leaves the library until its rewrite can deploy itself

`skills/autonomous-ai-agents/council/` was a generated copy of a **different repository**:
59 files, 9.4k lines, published by `council setup skill` from the legacy `review-council`
checkout. It has been removed, and installed into the two agent profiles instead.

## Why now

The project it came from is being replaced. `agentic-council-v2` is a fresh history
(92 commits, none shared with the legacy repo) with a different layout — `src/` packages
rather than `scripts/` — and **no deployment path**: its verbs are `review, ci, pr,
baseline, init, doctor`, and no `setup skill` exists. Its own skill is an 82-line command
reference with no scripts, no rubrics, no bots and no `protocol/` contracts to ship.

So the choice was between a copy that can only be generated from a repository that is on
its way out, and no copy. A library that claims to be curated cannot carry an artifact
whose source of truth is being retired — and it certainly cannot keep asserting, as the
claim audit did, that the copy matches a source that is about to disappear.

## What that costs

The library no longer ships a runnable council, and `test_the_council_suite_passes_on_the_shipped_code`
went with it — 873 assertions that only made sense while the scripts were here. The
`council` claim in `scripts/claim-audit.py` is deleted rather than left to report
`UNPROVEN`: a claim about an absent thing is noise, not evidence. The README counts follow
the filesystem: 75 `SKILL.md`, 69 catalog skills, 68 on Windows.

## What replaces it

Nothing, in this repository. The skill is installed in `$HERMES_HOME/skills/` on both
profiles, where it keeps working as a local, unmanaged skill.

## When it comes back

When `agentic-council-v2` grows a `setup skill` equivalent, the copy returns under the
same rule as before — generated, never hand-edited — and [ADR-0003](0003-the-council-skill-is-a-generated-copy.md)
is reinstated with a source that exists. Until then the library is silent about a tool it
cannot ship.
