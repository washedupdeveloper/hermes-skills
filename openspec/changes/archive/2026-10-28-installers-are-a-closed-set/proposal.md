# Proposal

## Why

`test_every_install_pins_an_exact_version` reads the package spec after `npm` or `npx`. A line that
installs the same CLI another way produces **no spec at all** — not a wrong version, nothing — and
the rule passes because it had nothing to parse:

    pnpm add -g @fission-ai/openspec@latest     # invisible

That is worse than a wrong answer: a gate that says nothing looks the same as a gate that agrees.

## What Changes

- The installers are a closed set: a line naming the CLI must use `npm`, `npx` or `nix`. `pnpm`,
  `bun`, `yarn`, `curl … | sh` and anything else fail, naming file and line.
- Five controls, including the case that motivated it (`pnpm add -g`) and the extreme one
  (`curl … | sh`, which has no package and no version to read).
- Mutant `1.2i`: the CI template's `npm install -g` becomes `pnpm add -g` and the gate must fail.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `gate-integrity`: adds "The installer is one the gate understands".

## Impact

`nix/tests.nix`, `tests/e2e/test_gate_mutants.py` (24 mutants). No install command changes.
