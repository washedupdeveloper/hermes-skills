# Proposal

## Why

The change that landed gate-integrity asserts that 22 mutants each make the gate fail. That
measurement lived in a scratch file outside this repository, so nothing could re-run it and
nothing noticed when it went stale — and its first run *was* wrong: restoring a mutated file with
`write_text` silently dropped `bootstrap.sh`'s executable bit, leaving a tree that differed from
the one it was given while reporting success.

A rule that has never been observed to fail is a guess. A mutant harness nobody runs is a guess
with a table around it.

## What Changes

- `tests/e2e/test_gate_mutants.py` is committed: 22 mutants, one per forbidden state plus four
  neutered rules, each required to make `checks.workflows` fail. It reads the pinned version from
  `nix/pins.nix`, restores the tree byte for byte and mode for mode, and reports a mutant the gate
  accepts as a broken rule rather than a result.
- A `gate mutants` CI job runs it on every push, so the rules are measured by the same pipeline
  that measures the tree.
- `gate-integrity` gains the requirement that a rule is exercised by a mutant, and that the
  harness restores what it changed.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `gate-integrity`: adds "A rule is measured against the states it forbids".

## Impact

`tests/e2e/test_gate_mutants.py` (new), `.github/workflows/ci.yml` (one job), `nix/tests.nix`
(the fifth-site rule stops firing on files where the package name is data — `tests/` joins
`nix/` — because the harness constructs the forbidden spellings as fixtures).
