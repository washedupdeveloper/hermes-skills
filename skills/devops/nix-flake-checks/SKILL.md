---
name: nix-flake-checks
description: "Use when writing a flake's checks or eval assertions."
version: 1.3.1
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
category: devops
metadata:
  hermes:
    tags: [nix, flake, checks, assertions, ci, eval]
    related_skills: [nix-flake-packaging, deterministic-quality-gates, cross-platform-test-portability]
writes: [none]
side_effects: [none]
---

# Writing a flake's checks

A flake's `checks` is how a repository makes its own claims true. Two things go wrong with
it: an assertion that passes without measuring, and an assertion that cannot run at all on
the machine that matters.

## When to Use

- Adding or repairing a `checks.<system>` output of a flake.
- Turning a prose claim in a README, spec or ADR into something the build enforces.
- A check passes locally and fails on CI, or the reverse.
- A gate reports green while the thing it guards is visibly broken.

## Two tiers — put a property in exactly one

| Tier | How | Cost | Good for |
|---|---|---|---|
| **eval** | `lib.runTests` over `{expr, expected}` pairs, returned in `checks.<system>` | milliseconds, no build | pure functions of the tree: a field present, a name matching its directory, a pattern absent from every workflow, a forbidden string rejected |
| **run** | `pkgs.runCommand` that runs a suite or a linter | one build | anything needing an interpreter, regex engine, subprocess or network: pytest, ruff, mypy, a container, an end-to-end script |

Do not implement one property in both. If the eval tier catches it in milliseconds, the run
tier must not also assert it — two owners drift, and the slower one is the one that gets
deleted.

Eval assertions must **name the file and both values**: `lib.runTests` prints whatever
`expr` produced against `expected`, so return `"${rel x.path}: ${x.fields.name or "(none)"}"`
rather than a bare `false`. A failure should read `skills/foo/SKILL.md: bar`, not "a test in
the skills group", and not a line number inside a `for` loop.

## Rules that keep a check honest

**Fail closed on a scan that found nothing.** A sweep over a directory that iterates zero
files passes. Assert the input set is non-empty (`assert specs`), and add a negative
control: reintroduce the defect in a scratch copy, confirm the check fails, and read what it
printed. A check never observed to fail is a guess.

**A check must measure the artifact, not a stand-in for it.** A gate pinned to a proxy — a
tokenizer, a similarity score, a corpus you wrote yourself — fails on correct inputs and passes
incorrect ones, and every failure then costs a manual adjudication to prove the gate wrong. Feed
it known-good inputs and compare against the real behaviour before it goes into `checks`; if the
proxy and the artifact disagree where the artifact is right, the proxy is wrong and the check is
a liability. The same logic rejects a threshold with one case of headroom: it is calibrated to the
sample, not to the property.

**A mutation is anchored to source text, so a refactor can silently disarm it.** A mutation gate
applies a literal replacement to a named line; when the guarded expression is refactored, the
anchor no longer matches, the mutation is not applied, and the gate reports `falsifier did not
break it` / `falsifies no claim` — a red gate, not a stale test to ignore. Retarget the mutation
in the same commit as the refactor, and re-run the mutation gate after any change to a line a
mutation names. A mutation that no longer applies is a gate failure even when the suite is green.

**A missing file must fail, not skip.** `builtins.pathExists` guarding a scan turns a
deleted file into a silent pass, because the scan has nothing left to reject. Prefer failing
with the path named; where a guard is genuinely needed (an optional directory), assert the
guard's own condition so its absence is visible too.

**A test that skips in the build sandbox is not a passing test.** `nix flake check` runs in a
sandbox without user namespaces, network or `/usr/bin`, so anything gated on `skipif(not
<feature>)` silently disappears from the gate — pytest still exits 0 and the progress line
carries `s`. Measured: a 198-test suite reported three skips inside the check, and they were
exactly the tests that proved the sandbox's own isolation. Assert `skipped == 0` from a JUnit
report written by the check, or split the host-only tests into their own check and name which
gate ran them; never let the build's green stand for a test it did not run. `nix log
.#checks.<system>.<name>` shows what actually executed, skips included. A test that needs user
namespaces (`bwrap`) is the same shape: the binary can be present while the namespace is
unavailable, so gate on the test having run, not on `shutil.which("bwrap")`.

**Regex builtins are stack-bound — never run one over a whole file.**
`lib.hasInfix a b` is `builtins.match ".*<a>.*" b`, and `builtins.match`, `lib.match` and
`builtins.split` recurse per character. On a file around 100 KB the evaluator exhausts its
stack and reports `error: stack overflow (possible infinite recursion)` — a message that
blames the assertion instead of the file, and that can appear **only on a runner with an
8 MB stack while passing where the stack is larger**. Replace containment with a count:

```nix
hasCrlf = text:
  builtins.stringLength text
  != builtins.stringLength (builtins.replaceStrings [ "\r" ] [ "" ] text);
```

`replaceStrings` is a C++ loop with constant stack. A check that genuinely needs a regex over
whole files belongs in the **run** tier, where the interpreter's engine is not the
evaluator's. A file can also cross the size threshold long after the check was written, so a
stack-bound check is a time bomb rather than a style choice.

## Where a suite runs — `checks`, not `doCheck`

The tempting simplification is `doCheck = true` on the package, so an untested artifact
cannot be built at all. Measured on a Python package with `format = "pyproject"`, all three
attempts fail in different directions:

| Attempt | Result |
|---|---|
| `doCheck = true` alone | builds green and **runs no tests** — no `checkPhase` in `nix log` |
| `+ pytestCheckHook` | runs, then dies on `ModuleNotFoundError` for dev-only SDKs the package deliberately does not ship |
| `+ those SDKs` | 914 passed, 5 failed: the build leaves `build/` and `*.egg-info/` in the tree the tests inspect, and `HOME=/homeless-shelter` breaks every test that overlays a real home (bwrap) |

The first row is the dangerous one: it reports success having measured nothing. The separate
check tier is what makes the last row's five pass — a copied tree and `HOME=$TMPDIR` — so keep
the suite in `checks` and link the artifact to it instead:

```nix
default = (app pkgs).overrideAttrs (prev: {
  passthru = (prev.passthru or { }) // { tests = checks.${pkgs.stdenv.hostPlatform.system}; };
});
```

`passthru` is excluded from the derivation, so the output path and its cache entry do not
change, and a consumer can run `.#default.passthru.tests.<check>` to see what proves the
build. A package that names its sibling `checks` makes the flake's output set recursive:
a plain attrset reports `undefined variable 'checks'` pointing at the attribute, not at the
reference, which reads as a typo rather than a missing `rec`.

## Making the gate fast without making it weaker

A gate slow enough to get bypassed is not a gate. Every lever below changes *when* work
happens, never *what* is proven — that line is what keeps a speed-up from becoming a
weaker check.

**Give each check its own input set, or nothing ever hits the cache.** `nix flake check`
already skips a check whose derivation is unchanged, but a check handed the whole tree
hashes the whole tree, so any edit invalidates all of them and the cache never hits.
Scope each check's `src` with `lib.fileset`:

```nix
scope = paths: lib.fileset.toSource {
  root = ./.;
  fileset = lib.fileset.unions (map (p: ./. + "/${p}") paths);
};
```

Measured on a 12-check gate: a history-doc, spec or changelog edit rebuilt 11 of 12
before and 5 after; a README edit 11 -> 6; a source edit still 11, which is correct
because the suite reads `src`. The survivors are honest — `tests`, `claims` and
`differential` all execute the suite, which opens the docs.

**A scope that is too narrow is a check that reads less and passes.** Land the scoping
with a test that parses the `mkCheck` calls and asserts each scope covers what its
command opens. Without it the failure is silent: `mutations` and `differential` were
handed the code scope and went red in the sandbox because the suite also opens `docs`,
`.github` and the spec tree, and `claims` runs the verify script, which runs pytest.
Any check that runs the suite needs the suite's scope, never a narrower one. Assert too
that every `mkCheck` names a scope at all, so the next check cannot silently inherit
the whole tree.

**Carry the tool configuration in every scope.** A scoped copy without `pyproject.toml`,
`pyrightconfig.json` or a linter allowlist checks with *different rules* than the
checkout — measured, pyright reported type errors in the sandbox that it did not report
locally, because its copy had no config. Config travels with the code or the check lies.

**Compute the ceiling before optimising.** A gate's wall-clock floor is total work
÷ available cores. 72 mutants × 31 s of suite = 2,232 core-seconds: 186 s on 12 cores,
558 s on 4. If the measurement is already near that floor, no scheduling change helps and
the only levers left are more cores or less work. Say which one you are buying;
"parallelise more" against a gate at 87% of its ceiling is a non-answer.

**A serial loop of subprocesses is startup-bound; pool it.** 263 claims each spawning an
interpreter cost 185 s, almost none of it work: the same registry across one worker per
core took 28 s. Same sound lever as a mutant pool — each item is an independent process,
the runner already continues past a failure, and the report is assembled in input order
(`ThreadPoolExecutor.map` preserves it). Expose the width as a flag (`--jobs`, 0 = one per
core) so it is policy rather than a constant.

**Pooling isolates scheduling, not state — give each item its own temp root.** pytest
numbers and prunes its basetemp under `TMPDIR/pytest-of-<user>/pytest-N`, and
`_pytest/pathlib.py:cleanup_numbered_dir` leaves an unclosed scandir iterator. Two pooled
items sharing a `TMPDIR` therefore delete each other's numbered directories mid-scan, which
surfaces as `ResourceWarning: unclosed scandir iterator` and, under `filterwarnings =
["error"]`, as a failed test that has nothing to do with the code under test. Measured: one
failure in six rounds of four concurrent runs on a shared root, none in ten rounds with
private roots. Give every item its own `TMPDIR`, `TMP` and `TEMP`, plus `-p no:cacheprovider`
for the cache file. A gate that fails once in five is worse than one that fails always — the
failure carries no information. Apply this to **every** pooled subprocess that runs pytest,
not only the one that flaked: a campaign of 72 suites has 72 chances per run, and there the
symptom is worse than a red check — a suite that dies on another item's cleanup reads as a
mutant that SURVIVED, which is a reported defect in the suite.

**Tier the gate so a typo fails in seconds and the expensive check never starts.** Order
by cost, not importance: lint and types answer in milliseconds, the suite in tens of
seconds, a mutation campaign in minutes. A cheap tier the expensive one depends on turns
a twelve-minute discovery into a thirty-five-second one and spends none of the expensive
compute on a tree that cannot pass.

In CI the tier has to be its own **job**, not a step: a step inside the expensive job still
pays that job's checkout, Nix install and namespace setup before it can fail. `fast` runs
alone; every expensive job declares `needs: fast` and they run beside each other. Measured,
that shape took a gate from 990 s to 385 s and a red run from 257 s to 57 s. A GitHub matrix
cannot be shared between jobs, so a duplicated matrix must be held byte-identical by a test
— otherwise the cheap tier gates one system and the expensive tier another, and the gap is
silent. The duplication costs the cheap tier's compute twice on a green run; measure that as
a fraction of the gate (it was ~6%) before deciding it is not worth four minutes on a red one.

**A tier invoked through an app must still print build logs.** An app that wraps `nix build`
without `--print-build-logs` reports a failure as an aggregate — `262/263 claims hold` — with
the item that failed nowhere in the log, and Nix's own "last N log lines" summary shows only
whatever the check printed last. Pass the flag inside the app, not in the caller, or the next
flake is undiagnosable by construction.

**Keep `--keep-going` inside a tier.** Fail fast across *tiers* is right; fail fast
*within* the full gate is not. Independent checks report every verdict in one pass so you
fix them together — stopping at the first makes you fix one, wait, and find the next.

Depth — the measurement recipe, the ranked levers, and the sharding design that keeps the
union exhaustive by construction: `references/gate-performance.md`. Rebuilding the exact
artifact a CI failure came from, and separating a flaky item from shared state:
`references/reproducing-ci-failures.md`.

## Verify

```bash
nix flake check --keep-going          # every group reports, not just the first
```

- **`running 0 flake checks ... all checks passed` means nothing was evaluated** — that is a
  cache hit, not a verdict. Force a real run per check:
  `nix build .#checks.<system>.<name> --no-link --rebuild`.
- **Stage or commit first.** The check hashes the tree Nix sees; untracked files are invisible
  to it, so gating before `git add` succeeds against the old tree and proves nothing about
  what you are about to commit. A new file fails as `ERROR: file or directory not found:
  tests/<new>.py` while it sits on disk — read that as untracked, not missing, and `git add`
  it; only then does the failing check say anything about the change.
- **Gate on the exit code, never on the tail of the output.** `nix flake check 2>&1 | tail -3`
  returns `tail`'s status, which is 0, so a red gate still reaches the `git commit` after it — that
  is how a tree with an unformatted file gets pushed with a green-looking log. Use
  `nix flake check --keep-going > log 2>&1 || { tail -20 log; exit 1; }`. The same shape swallows
  `nixfmt --check` inside an `if`, and a `grep` after a failing build (which reports the grep's 0).
- **Never use `--no-build` to verify a run-tier check.** It evaluates and stops, so a red
  `tests` or container check reports green — the false negative hides exactly the failure the
  check exists to find.
- **Format with the flake's own formatter, not the channel's.** `nix run nixpkgs#nixfmt` resolves
  the registry's pin while the check builds the flake input's, and the two disagree on layout: the
  file passes your formatter and fails `check-formatting`. Use
  `nix shell --inputs-from . nixpkgs#nixfmt -c nixfmt <files>`. Run it LAST as well — copying a
  staged tree back over the repo reverts the formatting you already applied, and the failure then
  names files you never touched.
- **Read the failure from an annotation when CI cannot be read otherwise.** On a runner the job
  log may require a token; the `github` skill carries the step that publishes the failing tail
  as a check annotation (its CI-troubleshooting reference), which is readable anonymously.

## Pitfalls

- An eval-tier check's derivation hash does not depend on the tree: `mkEvalCheck` returns a
  `runCommand` with no inputs, so `nix build .#checks.<group>` succeeds against a broken tree and
  a wrong tree fails at *evaluation* (`nix eval .#checks.<system>.<group>.drvPath`). Verify eval
  tiers with `nix eval`, never with a green build, and do not read the constant drv hash as
  "nothing changed".
- `nix flake check --rebuild` is not a flag — `--rebuild` belongs to `nix build`.
- `lib.runTests` returns a list of failures, not a boolean. Wrap it
  (`if failures == [ ] then pkgs.runCommand "check-<group>" {} "touch $out" else throwTestFailures`)
  so the group's name, and all of its failures, appear in `--keep-going` output.
- A `runCommand` that writes nothing fails for want of `$out`; the last line must `touch $out`.
- **A ban must measure invocations, not mentions.** The docs a rule lives in quote the form it
  forbids ("`npx` and `npm install -g` are what this replaces"), so a substring match fails the
  gate that documents it — and exempting those files is worse, because the next file to
  reintroduce the form escapes silently. Skip comment lines: a comment cannot run anything, so an
  injection example inside one stays documentation. The converse bites too: anchored to a command
  position only, the rule misses the form hidden behind a wrapper — `<venv>/bin/python -m pip
  install` has no command position to anchor on, so also match the verb itself in a non-comment
  fenced line. Prove both directions with literal fixtures: one line per spelling that must fail,
  plus the prose sentence that must pass.
- A `sed -i`/`patchShebangs` step in a check is a portability surface of its own: the sandbox
  has no `/usr/bin/env`, so shebangs must be patched before scripts run — or invoke the script
  through its interpreter (`bash ./script`), which needs no rewrite of the file being checked.
  A test that executes the script directly fails with `FileNotFoundError` naming the script,
  not `/usr/bin/env`; read that as a missing interpreter, not a missing file. **The rewrite also
  hits files the check only reads**, so a claim asserting a file's interpreter by literal path sees
  the patched form and fails inside the sandbox while passing in a checkout — measured, a claim
  asserting `#!/bin/sh` reported FALSE with `#!/nix/store/…-bash-…/bin/sh` beside it. Assert the
  *property* (the interpreter's basename is `sh`), never the literal line, and scope the patching
  away from files whose bytes are the thing under test.
- **A test that reads the machine's real `/etc` passes on a workstation and fails in the build
  sandbox**, which has no `/etc/resolv.conf`, no network and a different `$HOME`. Inject the
  lookup root as a parameter — `host_files_to_bind(rootfs, host_root=Path("/"))` — and point the
  test at a temporary one, so the decision is exercised without depending on what the builder
  happens to have. Same rule for `$HOME`, ambient credentials and anything under `/tmp`: a check
  that inherits the environment measures the environment.

- **A run-tier check that writes needs a writable copy, because `cp -r` keeps the store's
  0555 mode.** The source in `/nix/store` is read-only, so a suite writing bytecode or a tool
  mutating a copy dies with `PermissionError` inside the sandbox while passing in a checkout.
  Every such check starts `cp -r ${src} work && chmod -R u+w work && cd work`, and a tool that
  mutates its own copy chmods it too instead of assuming the caller did. A script that imports
  the project's package must put `src` on `sys.path` from its own location — the sandbox has no
  devshell and no `PYTHONPATH`, so `ModuleNotFoundError` there means the tool inherited an
  environment it will not have.

- **A flake that lists four systems promises all four build.** `genAttrs [ "x86_64-linux"
  "aarch64-linux" "x86_64-darwin" "aarch64-darwin" ]` is a claim, and one Linux-only dependency
  (`pkgs.bubblewrap`, `pkgs.util-linux`) makes every darwin output fail *evaluation* while
  `nix flake check` on Linux stays green. Probe each advertised system with
  `nix eval .#packages.<system>.default.drvPath`; scope the list to what builds, or move the
  Linux-only piece behind `pkgs.stdenv.isLinux`.

- **Declared, gated and tested are three different things — keep them separate on purpose.**
  `systems` is an evaluation contract: every `perSystem` output must *evaluate* for each entry,
  which a consumer or a machine of that platform needs. It is not a promise that anything builds
  or runs it. So a platform can stay declared while no gate builds it: that is a legitimate state
  as long as it is written down. `nix flake check` builds only the **current** system and says so
  (`warning: The check omitted these incompatible systems: aarch64-linux`); `--all-systems` is
  what builds the rest, and an emulated leg costs real minutes on every run. When scoping a leg
  out, keep the `systems` entry, and record in the flake, the workflow and the docs which entry
  is declared-but-ungated and what turns the gate on (`--all-systems` in one command, or one
  matrix label). Deleting the `systems` entry to save time breaks the build contract; leaving it
  silent makes a green gate read as coverage of a platform nothing touched.
- **A check that reads a workflow file to assert a runner matrix must assert the pointer too.**
  A naive `assert "<runner-label>" in workflow` keeps passing on a file where the comment is the
  only surviving mention, so it stops guarding the leg and starts guarding a string. Assert the
  reduced matrix **and** that the enabling label is still named, or the test cannot tell a
  deliberate scope-down from a silent removal.

- **A check body joined with `&&` can pass while its first half fails.** `set -e` does not fire
  for a non-final command in an AND-OR list, so `cmd1 && cmd2` followed by `touch $out` exits 0
  when `cmd1` fails — measured, a claims check printed `73/74 claims hold` and the derivation
  still succeeded, so the build reported "all checks passed" over a failing claim. Put each
  command on its own line under `set -e`, or wrap the interpolated command in a subshell —
  `( ${command} )` — so the list's status reaches `set -e`. Prove the fix with a canary: set
  one command to `false`, rebuild that check alone (`nix build .#checks.<system>.<name>`), and
  require a non-zero exit before restoring it.

- **A tree-wide text check must exempt the fixtures whose bytes are pinned.** A hygiene
  sweep — every shipped file ends with a newline, no CRLF, no trailing whitespace — will
  rewrite golden fixtures whose sha256 another test recomputes, so the "fix" breaks the
  evidence instead of the defect. Scope the scan to the shipped tree (`src`, `docs`, the
  manifests) and leave `fixtures/` out; when a fixture must genuinely change, re-pin its
  digest in the same commit and read the diff. The convention itself is worth a check:
  files written by an agent or a library often lack a final newline, every diff then says
  `\ No newline at end of file`, and the next append joins the last line — decode each file
  to skip binaries, assert the scanned set is non-empty, and prove the check fails by
  truncating one file.

- **A broken `flake.nix` cannot be repaired from its own devshell.** `nix develop -c python
  fix.py` evaluates the flake first, so the command never runs and the only output is the
  evaluation error — which reads as the fix failing. Reach for a shell that does not depend on
  the tree: `nix shell nixpkgs#python3 -c python fix.py`, or `sed`/`nixfmt`.

- **Do not measure in the checkout.** A timing harness that builds in-tree (`pip wheel`,
  `python -m build`, a tool that writes beside its source) leaves `build/` and
  `*.egg-info/` behind, and every check that scans the tree then fails on your artifacts —
  measured, two claims went red from a wheel a previous measurement had left. Build into a
  temp copy or the sandbox, and clean before believing a red result.

- **A version literal in a check must be compared against the flake's own `pkgs`, not the
  registry channel.** `nix eval nixpkgs#<attr>.version` resolves the registry's `nixpkgs`, which
  need not be the flake input: measured, the registry answered `1.13.1` while the lock's `pkgs`
  gave `1.14.1`, so a pin written from the first was wrong for the tree it guarded. Keep the
  expected version in one contract file and assert `pkgs.<attr>.version == pin` in the eval tier —
  a `nix flake update` that moves the tool then fails the gate instead of silently changing what
  the repository documents.
