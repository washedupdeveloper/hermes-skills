---
name: nix-flake-checks
description: "Use when writing a flake's checks or eval assertions."
version: 1.2.2
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
category: devops
metadata:
  hermes:
    tags: [nix, flake, checks, assertions, ci, eval]
    related_skills: [nix-flake-packaging, deterministic-quality-gates, cross-platform-test-portability]
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
- An assertion about workflow files must skip comment lines, or a doc mention of a forbidden
  ref fails the gate it documents.
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
