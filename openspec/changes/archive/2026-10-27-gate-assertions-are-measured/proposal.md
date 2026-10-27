# Proposal

## Why

Round 1 passed the gate with no open high/critical, but the change's central claim — that
`nix flake check` rejects a floating runner and a range pin — holds only for the exact spellings
the new patterns were written around. The review reproduced four surviving states: a matrix
`os: [ubuntu-latest]` list, a trailing comment after `@1`, a range such as `@^1.15.0`, and a
template that disappears because the scan uses `builtins.pathExists`. The same review found the
version pin living at four sites while `AGENTS.md` calls it three and the gate reads two.

The assertions were added to enforce ADR 0005. An assertion that cannot fail on the state it
forbids turns a green gate into a restatement of the tree, which is worse than no assertion —
it is a measurement claim that is false. That is why this is blocking now and not later.

## What Changes

- Every gate assertion gains a mutation case it must reject, and the assertions are rewritten so
  the predicate the gate calls is the predicate the negative control exercises.
- The scanned set fails closed: a missing or renamed adopted file fails the gate instead of
  shrinking the scan.
- Enforcement prose in `AGENTS.md` names exactly what the gate checks; files the repository tells
  other repositories to adopt join the scan rather than the sentence.
- The pinned CLI version gets one machine-readable source, and every adopted copy is checked
  against it — `AGENTS.md`, the CI job, the shipped template and `bootstrap.sh` stop being four
  hand-maintained literals.
- `scanPinned` is folded into `scan` so the comment-skip rule and `file:line` formatting have one
  owner.
- A change leaves every Nix file it touches clean under `nixfmt --check`; the pre-existing
  repo-wide debt is recorded per file rather than charged to this change or left as a count.
- Secret-scan hits are dispositioned in a place a machine reads: the probe allowlist gains the
  council test fixtures, and the `npm install -g` residual is either closed (`--ignore-scripts`,
  integrity-checked tarball) or recorded as an accepted risk with its bound.
- Eval-tier cost is measured against a pinned baseline instead of being reported as `0.0s`.

## Capabilities

### New Capabilities

- `gate-integrity`: the repository's own gate rejects the states it names, in every spelling it
  claims, fails closed when a scanned file is missing, and states no more than it checks.

### Modified Capabilities

- `skill-library`: the "One home per fact" requirement is extended from skill prose to the
  pinned CLI version, so a version that must move in lockstep lives in one source and each
  adopted copy is checked rather than restated.

## Impact

- `nix/tests.nix` — the four new assertions and the `scan`/`scanPinned` helpers.
- `AGENTS.md:99-105` — the pin procedure and the enforcement sentence.
- `.github/workflows/ci.yml:249-258` — the openspec job.
- `skills/software-development/openspec/templates/ci-job.yml:17` and
  `skills/software-development/openspec/scripts/bootstrap.sh:10` — the adopted copies.
- `skills/autonomous-ai-agents/council/scripts/probes.py:1055-1081` — the gitleaks allowlist.
- `docs/milestone.md` — the milestone claim that the gate now measures.
- No runtime path: all new checks execute at eval time, and the shell edit is an install hint.