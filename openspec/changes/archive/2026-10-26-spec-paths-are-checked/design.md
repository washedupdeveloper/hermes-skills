# Design

## Context

See `proposal.md` — Why. Two facts about the gate shape this design. It has two tiers, and the
rule is that an assertion belongs in the cheapest tier that can make it: `nix/tests.nix` reads
values (a field, a length, a path) and `nix/checks.nix` runs what needs an interpreter (pytest,
`claim-audit.py`, `setup.sh`). And `openspec validate --strict` checks shape, not truth — ADR 0008
says so as a consequence, which is why the false path survived every gate the repository had.

## Goals / Non-Goals

**Goals.** The `skill-library` spec states only what is true, and each claim it makes is asserted
by something that can fail.

**Non-Goals.** Renaming the capability. Auditing paths in `openspec/changes/` — a change is
transient and its delta names files it is about to create. A new validator script.

## Decisions

**1. Name the gate; do not create `scripts/validate_skills.py`.** The scenario named a script that
never existed. Writing it now would give frontmatter a second owner: `nix/tests.nix` already
asserts the required fields, the 57-character window and the name/directory match, and it does it
for free during evaluation. Rejected: a script called from the gate, which is the same property
checked twice by two implementations that can disagree.

**2. The path check lives in `tests/unit/test_docs.py`.** That file already asserts that a
backticked repository path in `README.md`, `AGENTS.md` and `soul/` exists; a spec is one more
document making the same promise, so one regex and one failure message cover both. Rejected:
`claim-audit.py`, which classifies prose claims as PROVEN/FALSE/UNPROVEN and prints a report — a
path is a binary fact, and this repository's suite is where a fact is asserted. Rejected: a Nix
eval check, because the check needs a regex engine.

**3. Scan `openspec/specs/` only, never `openspec/changes/`.** The spec is the live contract;
archived deltas describe a tree as it was at the time, and a change's own delta names files it
intends to create, so scanning them would make the check fail on the work it is meant to allow.

**4. The category set is read from the README layout tree, not held in code.** This repository has
already paid for the alternative: `claim-audit.py` once carried the expected skill counts as
literals, and adding one skill failed the audit twice over. The layout tree is where a reader looks
for the categories, so it is the declaration; the test compares it with the filesystem in both
directions, so a category that exists but is undeclared fails as loudly as one declared and absent.

## Risks / Trade-offs

- **The README tree is reformatted and the parse silently matches nothing** → the assertion also
  requires the parsed set to be non-empty, so an unreadable tree fails instead of passing empty.
- **A spec legitimately names a path outside this repository** → the pattern only matches
  repo-relative prefixes (`skills/`, `docs/`, `nix/`, `openspec/`, `scripts/`, `tests/`, `soul/`);
  an external path is written with `$HERMES_HOME` or an absolute path and cannot match. The first
  such occurrence is the moment to widen the rule deliberately, not to weaken the check.
- **The check costs one `rglob` per suite run** → negligible against the suite's existing scans.

## Migration Plan

None. The delta merges on archive, and no shipped skill changes.
