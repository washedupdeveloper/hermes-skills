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
Optimising outside the top two is noise. On a four-core CI runner the same gate was 68%
campaign, 28% registry — fewer cores move the campaign up, and the registry's cost is
fixed startup rather than work.

Run the harness outside the checkout. A measurement that builds in-tree leaves `build/`
and `*.egg-info/`, and any check that scans the tree then fails on your own artifacts —
measured, two claims went red from a wheel left behind by an earlier timing run.

**Derive a per-item cost from one item, not from the aggregate.** Wall time divided by
items is a scheduling figure, not a cost: 258 s × 12 workers ÷ 72 mutants suggested 43 s
per mutant, and the single mutant timed in the tool's own shape took 26.7 s. The gap was
pool efficiency, and optimising against the wrong number aims at the scheduler instead of
the work. Time one item directly, then multiply.

**A timing harness must not corrupt its own measurement.** Two shapes cost a run each:
`run | tail -1` followed by a `grep` for the message searches only the last line, so a
failing gate reads as passing; and `grep -q` under `set -o pipefail` reports the pipeline
as failed (SIGPIPE, 141) exactly when it matched. Capture the output once into a variable
and match with `case`/`[[ … == *msg* ]]` instead of piping into `grep -q`.

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

## Evidence, lever by lever

Numbers worth quoting when someone asks what a lever is worth, and the failure mode each one
has actually produced.

**Scoping (1).** Twelve checks, whole tree as one input: an edit to a history doc, a spec, the
changelog or `README.md` rebuilt 11 of 12 — only the check that already had its own root stayed
cached, so the cache never hit. After `lib.fileset` scoping: doc/spec/changelog edits rebuild 5,
a README edit 6, and a source edit still 11, which is correct because the suite reads `src`.
The survivors are honest: `tests`, `claims` and `differential` all execute the suite, which opens
the docs.

**Scoping has a silent failure mode.** A scope narrower than what the command reads makes the
check pass having read less. It happened three times landing one change: two checks were given
the code scope while their suite also opens `docs` and `.github`, and a third ran the claims
script, which runs pytest. Each went red in the sandbox — which is the good outcome; the same
mistake with a passing check is invisible. Hence the guard test: parse the `mkCheck` calls,
assert each scope covers what its command opens, and assert every call names one.

**Tool config travels with the code.** A scoped copy without `pyproject.toml` or
`pyrightconfig.json` checks by different rules than the checkout — measured, pyright reported
type errors in the sandbox that it did not report locally. The check was not wrong about what it
saw; it was seeing a tree with no config.

**Pooling (2).** 263 items, each spawning an interpreter: 185 s serial, 28 s across one worker
per core. Almost none of the serial cost was work. Keep the report in input order
(`ThreadPoolExecutor.map` does) so a failure still names its item.

**Staging (3) works only as a separate job.** A fast tier as a *step* inside the expensive job
still pays that job's checkout, Nix install and namespace setup before it can fail: measured, a
red run cost 257 s that way and 57 s as its own job. A GitHub matrix cannot be shared between
jobs, so the two matrices must be held byte-identical by a test or the cheap tier gates one
system while the expensive tier gates another. The duplication re-costs the cheap tier's compute
on a green run — measured ~6% of the gate — against four minutes saved on a red one.

**Why the campaign dominates.** It is the only check whose cost is `items × suite` with nothing
startup-bound to hide behind, and it is also the one where a wrong optimisation is worst: a
suite that dies for an unrelated reason reports the mutant as SURVIVED, which reads as a defect
in the suite rather than in the runner.

## Test runners leave state behind

A pooled item is not isolated just because it runs in its own process. pytest builds and prunes
`TMPDIR/pytest-of-<user>/pytest-N` whenever it is given no basetemp, and that path leaks a
scandir handle.

- **Give every invocation its own `--basetemp`.** With a basetemp,
  `TempPathFactory.getbasetemp` returns before `make_numbered_dir_with_cleanup`, so the
defective path never runs. Measured: four workers sharing one `TMPDIR`, basetemp per worker,
ten rounds, zero failures, and no `pytest-of-*` directory created at all.
- **Still give every item its own `TMPDIR`, `TMP` and `TEMP`, plus `-p no:cacheprovider`.**
  Same shared root, no basetemp: one failure in six rounds of four concurrent runs. Private
  roots alone removed that symptom but left the contention — with the scandir handle closed on
  the consumer side, a shared root still failed as `OSError: [Errno 39] Directory not empty`.
2 in 10 rounds, two items deleting each other's `garbage-*` directories.
- **Watch for the second-order failure.** Fixing the first symptom moves the failure rather
  than removing it, so re-run the same experiment after a fix and check that the *shape* is
  gone, not just the message.

## Levers that reduce work without narrowing what is proven

Three levers cut actual work rather than rearranging it. Each is sound for a reason statable
in one sentence, and each has a specific way of going wrong.

**Decide each item by what the registry already declares.** For a mutant, the claims that
name it as falsifier are the only ones its verdict can settle; their tests are 1.11 nodes on
average and decided all 72 mutants in 12 s against 258 s for the whole suite. The asymmetry
is the guarantee: a failure in the subset is a real failure, so a catch needs no inference;
a pass proves nothing, so the full suite runs. Three ways it goes wrong, all observed:
fail-fast over the subset records only the first broken claim, so a mutant named by three
claims reports two as "falsifier did not break it"; a subset that concludes a *miss* is a
weaker gate wearing a faster number; and a guessed subset (import graph, coverage map, `-k`)
is the same mistake with no registry behind it.

**Cache a verdict keyed to everything that can change it.** The campaign's unit is "run the
whole suite under this mutation", so an edit anywhere in `src/` or `tests/` can change any
verdict — the key is the two trees, the registry, the tool and the interpreter, never the
mutated file alone. Measured: an identical tree went 326 s to 1.2 s, and a changed one
re-scored everything, which is the point. A cache that cannot be written (a read-only
sandbox) prints and continues; pass `--no-cache` in the derivation rather than relying on
that guard, because Nix already caches the whole check.

**Split the suite and let Nix schedule it.** The aggregate name, the evaluation-time
coverage assertion and the one-directional failure mode are what make it a speed-up rather
than a quiet reduction in coverage; the skill carries the rule and the two bugs the
assertion caught while it was being landed.

## What not to do

- **Fail-fast inside the full gate.** `--keep-going` is why independent checks give every
  verdict in one pass. Stopping at the first makes you fix one, wait, discover the next.
  Fail fast across *tiers*, complete *within* one.
- **Select tests by filename or `-k` pattern.** A test that never executes the mutated
  region cannot distinguish a mutant, and neither can a selector that guesses from a path.
  It narrows what can be noticed while still reporting a full verdict.
- **Let a subset conclude a miss.** A subset may prove a catch — a real test failed — and
  nothing else. A pass is not evidence about the rest of the suite, so it falls back to the
  full run; the moment a subset decides a survivor, the campaign is measuring the subset and
  reporting a verdict about the suite.
- **Cut mutants or tests to save time.** That is not a speed-up, it is a weaker gate with a
  faster clock.
