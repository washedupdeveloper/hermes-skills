# Proposal

## Why

`docs/milestone.md` is the document that states what is true about this repository, and it was the one
place with no check behind it. It said the contract held 11 requirements when it held 15, and that the
gate was measured by 22 mutants when it was measured by 25 — while `nix flake check`, `claim-audit`
and the specs all stayed green. A third count, "three changes landed after this document was written",
was wrong by six.

That is the defect this project exists to remove, surviving in its own milestone: a number stated in
prose that nothing measures.

## What Changes

- Every count no check derives leaves the status paragraph, replaced by a pointer to the thing that
  cannot go stale — `openspec/changes/archive/`, the workflow, the check-runs API.
- The two counts that *can* be derived stay, and `tests/unit/test_milestone_doc.py` derives them:
  16 requirements across `gate-integrity` (11) and `skill-library` (5), measured by 25 mutants.
- The comparison is a function with a negative control: a test drifts the number and asserts the
  comparison notices, and another removes the sentence and asserts that fails too. It is a run-tier
  rule, so it lives in pytest rather than in the mutant harness, which drives the eval tier.

## Capabilities

### Modified Capabilities

- `gate-integrity`: adds "A stated count is checked".

## Impact

`docs/milestone.md`, `tests/unit/test_milestone_doc.py`. No workflow or gate change.
