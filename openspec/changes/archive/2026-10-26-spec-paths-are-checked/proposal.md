# Proposal

## Why

`openspec/specs/skill-library/spec.md` names `scripts/validate_skills.py` in a scenario, and no
such file exists anywhere in the tree: frontmatter is gated by the eval tier in `nix/tests.nix`.
`openspec validate --strict` passes, because it checks shape and not truth, and
`scripts/claim-audit.py` never reads the specs — so the library's own source of truth carries a
false statement that no gate can see. The same requirement's "known category" clause has no
referent at all: nothing declares the category set, and the README layout tree, which readers take
as that declaration, omits `note-taking/`.

## What Changes

- The "Every skill validates" requirement stops naming a script and names the gate that actually
  runs.
- Its category clause gains a referent: the categories are the ones the README layout tree
  declares, and the suite asserts the tree and the filesystem agree in both directions.
- A new requirement: every repository path a spec names exists, asserted by
  `tests/unit/test_docs.py`, so a later spec cannot name a file that is not there.
- `tests/unit/test_docs.py` extends its existing path check to `openspec/specs/**`.
- `README.md`'s layout tree gains `note-taking/`, which exists on disk and was missing.

## Capabilities

### New Capabilities

None. Every behavior here belongs to the existing `skill-library` capability: what the library
promises about its own skills, and now about its own specs.

### Modified Capabilities

- `skill-library`: the validation requirement names the real gate and gives "known category" a
  referent; a new requirement makes the paths a spec names checkable.

## Impact

`openspec/specs/skill-library/spec.md` (through this delta), `tests/unit/test_docs.py`,
`README.md`. No skill's instructions change and nothing is added to the shipped library. The gate
gains coverage; the shipped tree does not move.
