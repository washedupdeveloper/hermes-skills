# Tasks

## 1. Put the harness in the repository

- [x] 1.1 Commit `tests/e2e/test_gate_mutants.py`: 22 mutants, the pinned version read from
  `nix/pins.nix`, restore verified byte for byte and mode for mode.
- [x] 1.2 Make the fifth-site rule stop firing on files where the package name is data (`tests/`,
  alongside `docs/`, `openspec/` and `nix/`).

## 2. Enforce it

- [x] 2.1 Add the `gate mutants` CI job, pinned actions, annotated on failure.
- [x] 2.2 Run it locally against the committed tree: 22/22, tree unchanged.

## 3. Verify

- [x] 3.1 `python3 tests/e2e/test_gate_mutants.py` exits 0 and leaves `git status` showing only
  the files this change edits.
- [x] 3.2 `nix flake check --keep-going`, `pytest`, and `claim-audit` all pass with the job and the
  test in the tree.
