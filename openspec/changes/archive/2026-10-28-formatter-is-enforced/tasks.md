# Tasks

## 1. Format the tree

- [x] 1.1 `nixfmt` every tracked Nix file except the golden target (4 files had drifted).
- [x] 1.2 Confirm the gate and the Python suite still pass afterwards.

## 2. Enforce it

- [x] 2.1 Add the `formatting` run-tier check: tree-wide, one named exemption, fail-closed below
  ten files.
- [x] 2.2 Remove the touched-file requirement and add the tree-wide one.

## 3. Verify

- [x] 3.1 `nix build .#checks.x86_64-linux.formatting` passes on the committed tree.
- [x] 3.2 Unformat one file: the check fails and names it; restore, and it passes.
- [x] 3.3 `nix flake check --keep-going`, `pytest`, `claim-audit`, and
  `openspec validate --all --strict` all pass.
