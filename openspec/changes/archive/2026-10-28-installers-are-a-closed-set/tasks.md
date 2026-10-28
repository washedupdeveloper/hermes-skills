# Tasks

## 1. Close the set

- [x] 1.1 `installerOutsideTheSet`: a line naming the CLI without an adopted installer is a finding.
- [x] 1.2 Five controls: `npm` and `nix … npx` accepted; `pnpm`, `bun`, `curl | sh` refused.

## 2. Measure it

- [x] 2.1 Mutant `1.2i` — the CI template's installer swapped for `pnpm` — added; 24 mutants.
- [x] 2.2 The harness runs green and the mutant fails the gate as required.

## 3. Verify

- [x] 3.1 `nixfmt` the file the change edits, then `nix flake check --keep-going` gated on its exit
  code — not on the tail of its output.
- [x] 3.2 `pytest`, `claim-audit`, `openspec validate --all --strict`.
