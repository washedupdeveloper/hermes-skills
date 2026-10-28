# Tasks

## 1. The conditions

- [x] 1.1 Every `runs-on:` expression names a matrix key.
- [x] 1.2 No workflow uses `include:`.
- [x] 1.3 Controls: `matrix.os` accepted, `inputs.runner` and `fromJSON(...)` refused.

## 2. Measure it

- [x] 2.1 Mutant `1.1e` — a runner from inputs — added; 23 mutants total.
- [x] 2.2 The harness runs green against the tree.

## 3. Verify

- [x] 3.1 `nix flake check --keep-going`, `pytest`, `claim-audit`, `openspec validate --all --strict`.
