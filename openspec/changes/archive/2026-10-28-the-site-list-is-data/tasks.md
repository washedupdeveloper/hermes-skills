# Tasks

## 1. Move the list

- [x] 1.1 `pins.nix` gains `openspecCliSites`.
- [x] 1.2 `nix/tests.nix` derives `adoptedSpecs` from it; the three singletons are removed.
- [x] 1.3 The empty-list assertion, because an empty list passes every rule above it.

## 2. Remove the drift

- [x] 2.1 The three prose counts are deleted, not corrected; each points at the list instead.
- [x] 2.2 Mutant `3.1e` — a site dropped from the list — added; 25 mutants.

## 3. Verify

- [x] 3.1 `nixfmt`, then `nix flake check --keep-going` gated on its exit code.
- [x] 3.2 `pytest`, `claim-audit`, `openspec validate --all --strict`.
