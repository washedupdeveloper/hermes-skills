# Tasks

## 1. Make the gate measure (blocking)

- [x] 1.1 Detect a floating runner through every form a workflow uses — `runs-on:` scalar, bracketed
  list, block list, quoted value, and `runs-on: ${{ matrix.os }}` where the `os:` matrix carries the
  label. Verify: with `os: [ubuntu-latest]` in `.github/workflows/ci.yml`,
  `nix build .#checks.x86_64-linux.workflows --no-link` fails naming the `os:` line; with the
  committed tree it succeeds.
- [x] 1.2 Detect every non-exact CLI install — `@latest`, `@^1.15.0`, `@~1.15.0`, `@1.15`, a
  versionless package, a trailing comment after the version, `npm i -g`, `npm install --global`,
  and the `npx -y` form documented in `AGENTS.md`. Verify: a six-mutant corpus, one mutant per run,
  each fails the install-pin assertion; the committed tree passes it.
- [x] 1.3 Make each negative control exercise the rule its assertion calls, so a rejection pattern
  replaced with a never-matching one fails the suite. Verify: replace each pattern in turn with a
  never-matching literal while adding the state it forbids to the tree, and confirm
  `nix flake check --keep-going` reports a failure for every replacement.

## 2. Fail closed

- [x] 2.1 Remove the `builtins.pathExists` fallback and assert that every adopted file is present,
  so a renamed or untracked template fails instead of leaving the scan empty. Verify: move
  `skills/software-development/openspec/templates/ci-job.yml` aside, run
  `nix flake check --keep-going`, confirm it fails naming the missing path, restore the file, and
  confirm it passes.
- [x] 2.2 Assert that the scanned set is non-empty before the assertions run, so an empty input set
  cannot read as a clean result. Verify: the missing-template run above reports the empty-set
  failure rather than passing.

## 3. One source for the pinned version

- [x] 3.1 Give the version one machine-readable source and check every adopted copy against it:
  `AGENTS.md:99`, `.github/workflows/ci.yml:256`,
  `skills/software-development/openspec/templates/ci-job.yml:17`,
  `skills/software-development/openspec/scripts/bootstrap.sh:10`. Verify: set each site to `@1` in
  turn, run `nix flake check --keep-going`, and confirm the failure names that path and line.
- [x] 3.2 Correct the `AGENTS.md` sentence to name the sites the gate actually checks, and the bump
  procedure to list every one of them. Verify:
  `python3 scripts/claim-audit.py` exits 0 and the enumeration test fails when a fifth site is
  added to the tree without updating either.
- [x] 3.3 Fold the second scanner into the first so the comment-skip rule and `file:line` formatting
  have one owner, and feed it the extended file list. Verify:
  `grep -c 'isComment' nix/tests.nix` reports one definition, and the gate's pass/fail output is
  unchanged for the committed tree and for the 3.1 mutants.

## 4. Formatting

- [x] 4.1 Format the touched Nix file per RFC 166 and verify `nixfmt --check nix/tests.nix` exits 0
  — the file fails at `f797ef1`, so this debt is settled rather than inherited.
- [x] 4.2 Record every remaining formatter and linter finding in files the change does not touch,
  one path and line each, with a disposition: `nixfmt` (the probe reports ten files, the reviewer
  names six — reconcile the count), `deadnix` `flake.nix:11`, `nix/overlay.nix:17`,
  `nix/overlay.nix:30`, `hermes-skills.nix:6`, `skills-refresh-timer.nix:25`, and `statix`
  `flake.nix:29`, `nix/overlay.nix:11`. Verify: every reported path appears in the record with a
  line, and the repository-wide check is not described as clean.

## 5. Secret scan and the install step

- [x] 5.1 Add an allowlist entry naming the council test fixtures
  (`skills/autonomous-ai-agents/council/tests/test_probes.py:80,93`) to `_GITLEAKS_CONFIG` in
  `skills/autonomous-ai-agents/council/scripts/probes.py`. Verify: the gitleaks probe over the
  working tree reports zero findings while both `probe_secret_grep` tests still pass.
- [x] 5.2 Close the `adhoc-packages` residual or record it as accepted with its boundary: add
  `--ignore-scripts` and an integrity-checked install, or write down that the version pin closes
  drift but not registry substitution or dependency drift, bounded by the job's `permissions: {}`.
  Verify: `zizmor .github/workflows/ci.yml` reports the finding resolved, or the record names the
  finding, its bound and the reason it stays.

## 6. Cost

- [x] 6.1 Pin an eval-time baseline and record the delta the new assertions add, naming the files
  read at eval time. Verify: the recorded before/after numbers come from the same command on the
  same host, and the report says no Python or shell execution path gained work — naming
  `bootstrap.sh:10` as a message literal if it is mentioned at all.

## 7. Integration verification

- [x] 7.1 Run the full gate, the Python suite and the claim audit together: `nix flake check
  --keep-going`, `python3 -m pytest -q`, `python3 scripts/claim-audit.py`. Verify: all three exit 0
  on the committed tree, and each of the 1.1, 1.2, 1.3, 2.1 and 3.1 mutants makes the gate exit
  non-zero.

## Workflow follow-up

- Archive the change with `openspec archive gate-assertions-are-measured --yes` once the review
  requirements are satisfied.
- Run `python3 scripts/verify-live.py` after archive to confirm the real `hermes` still discovers
  every catalog skill.