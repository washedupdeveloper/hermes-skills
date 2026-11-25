# Making a slow gate fast

Ranked levers, cheapest and safest first. Every one changes *when* work happens, never
*what* is proven. Anything that changes what is proven is a different change with its own
proof, and must reproduce the old verdict item for item before it ships.

## Measure before you cut

Time each check on its own, in the devshell — `nix flake check` is one number and hides
the distribution:

```bash
t() { local l="$1"; shift; local s e rc; s=$(date +%s%N); "$@" >/dev/null 2>&1; rc=$?; \
      e=$(date +%s%N); printf '%-12s %7d ms rc=%d\n' "$l" $(( (e-s)/1000000 )) "$rc"; }
t ruff   ruff check .
t mypy   mypy src
t pyright pyright
t pytest python -m pytest -q
t claims env PYTHON=python ./bin/verify
```

The distribution is usually more lopsided than expected: a measured 12-check gate was
77% mutation campaign, 11% test suite, 10% claim registry, under 1% everything else.
Optimising outside the top two is noise.

Run the harness outside the checkout. A measurement that builds in-tree leaves `build/`
and `*.egg-info/`, and any check that scans the tree then fails on your own artifacts —
measured, two claims went red from a wheel left behind by an earlier timing run.

## The ceiling

Wall-clock floor = total work ÷ cores. 72 mutants × 31 s = 2,232 core-seconds: 186 s on
12 cores, 558 s on 4. Compare the measurement against that before proposing anything.

- At or near the floor, scheduling is exhausted; "parallelise more" is a non-answer.
- The remaining levers are **more cores** (wall clock, same compute) or **less work** (the
  only one that reduces compute, and the only one that can weaken the gate).

## Levers, ranked

1. **Scope each check's input.** `lib.fileset` per check plus a test asserting each scope
   covers what its command opens. Best ratio of win to risk: no behaviour changes at all.
2. **Pool serial subprocess loops.** N items × interpreter startup is the whole cost. One
   worker per core, report in input order, expose `--jobs`. Sound because each item is an
   independent process.
3. **Stage the gate.** Cheap checks first, expensive behind them: a failure surfaces in
   seconds and the campaign never starts.
4. **Shard across runners.** Wall clock only; compute unchanged. Split deterministically by
   index so each shard knows which items are its own, and assert exactly those — the union
   is then exhaustive by construction rather than by trust.
5. **Binary cache.** Only worth it once derivations are stable across edits, which is what
   (1) establishes. Doing it first is the trap: it looks green locally and still rebuilds
   everything on a clean runner. Measure substitutability first — stock nixpkgs packages are
   already served, so the gap is only the flake's own derivations.
6. **Per-item derivations.** One derivation per mutant or claim instead of a pool: Nix
   parallelises them, caches each individually, and names the failing item in the build log
   rather than a line of stdout. Composes with (4) and (5).
7. **Coverage-guided selection — last, and only with an oracle.** The only lever that
   reduces actual work. Run only the tests that execute the mutated line, from a full-suite
   coverage map, with a documented full-suite fallback. A coverage map is not a perfect
   over-approximation: module-level constants and import-time effects escape it, so a mutant
   can look killed when it was merely unobserved. Require the new selection to reproduce the
   old verdict item for item before it ships.

## What not to do

- **Fail-fast inside the full gate.** `--keep-going` is why independent checks give every
  verdict in one pass. Stopping at the first makes you fix one, wait, discover the next.
  Fail fast across *tiers*, complete *within* one.
- **Select tests by filename or `-k` pattern.** A test that never executes the mutated
  region cannot distinguish a mutant, and neither can a selector that guesses from a path.
  It narrows what can be noticed while still reporting a full verdict.
- **Cut mutants or tests to save time.** That is not a speed-up, it is a weaker gate with a
  faster clock.
