# Proposal

## Why

`gate-integrity` said "a touched Nix file is formatter-clean" — a rule about the file a change
edits, with any debt elsewhere recorded in prose. That is how four tracked files (`nix/checks.nix`,
`nix/lib.nix`, and two shipped templates) drifted without anything noticing: a rule that applies to
the file you are already editing cannot see the ones nobody opens.

The formatter was also only ever run by hand. The council found the debt; nothing would have caught
the next one.

## What Changes

- A `formatting` check: `nixfmt --check` over every tracked Nix file, exempting one — the golden
  target, whose bytes are the fixture a golden diff compares — with the exemption named in the
  check and its presence asserted. The scan must find at least ten files, so an empty scan fails
  rather than passing.
- The four drifted files are formatted.
- `gate-integrity` replaces the touched-file requirement with a tree-wide one. The old requirement
  is removed rather than quietly widened, so the record shows what was promised before.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `gate-integrity`: "A touched Nix file is formatter-clean" → "Every Nix file is formatter-clean",
  with the exemption as a scenario instead of a sentence.

## Impact

`nix/checks.nix` (one check), four formatted files. The check is run-tier: it needs the formatter,
so it cannot live in the eval tier.
