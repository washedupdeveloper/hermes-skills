# The run tier, and why this repository has no build tier.
#
# `nix/tests.nix` holds the eval tier: pure properties of the source tree.
# This file holds what needs an interpreter.
#
# THERE IS NO BUILD TIER, and that is a finding rather than an omission. An
# earlier version of this file built a simulated "shipped" tree -- SKILL.md plus
# the four support directories -- and asserted self-containment against it. That
# copier does not exist: Hermes reads `external_dirs` in place (README: "No copy,
# no symlink, no junction"), and AGENTS.md forbids adding a sync script. So the
# artifact under test was fiction, and the properties it asserted were already
# covered by the eval tier and by `test_no_dead_references`. It was deleted
# rather than kept for the sake of having a middle tier.
#
# The end-to-end claim lives in `scripts/verify-live.py`, which asks the REAL
# Hermes binary -- it cannot be a flake check, because the product is not a flake
# input of this repository. `.github/workflows/ci.yml` runs it in its own job.
{ lib, pkgs, src }:
let
  # The eval tier, one check per group so `--keep-going` reports every failing
  # group rather than stopping at the first.
  evalGroups = import ./tests.nix { inherit lib src; };

  mkEvalCheck =
    group: tests:
    let
      failures = lib.runTests tests;
    in
    if failures == [ ] then
      pkgs.runCommand "check-${group}" { } "touch $out"
    else
      lib.debug.throwTestFailures { inherit failures; };

  python = pkgs.python3.withPackages (ps: [ ps.pytest ]);

  # A writable copy: the store is read-only and both pytest and the audit write
  # caches. `__pycache__` is stripped so a stale bytecode file cannot be what
  # makes a test pass.
  #
  # `patchShebangs` is load-bearing: a Nix build sandbox has no `/usr/bin/env`, so
  # a script whose shebang is `#!/usr/bin/env bash` cannot be spawned at all --
  # `claim-audit.py` executes `setup.sh` and died with a FileNotFoundError that
  # named the script rather than its interpreter.
  #
  # The `sed` reaches a shebang `patchShebangs` cannot: `tests/e2e/test_setup.sh`
  # writes a stub `hermes` inside a heredoc, so its `#!/usr/bin/env bash` is not
  # the file's first line. It is patched here, in the check's copy, because the
  # sandbox limitation is the harness's and not the test's -- the repo's test is
  # unchanged and still runs on a real machine.
  srcWritable = pkgs.runCommand "hermes-skills-src" { } ''
    cp -r ${src} $out
    chmod -R u+w $out
    patchShebangs $out
    sed -i -E "s|^#![[:space:]]*/usr/bin/env[[:space:]]+bash\$|#!${pkgs.bash}/bin/bash|" \
      $out/tests/e2e/test_setup.sh
    find $out -name __pycache__ -type d -prune -exec rm -rf {} +
  '';
in
# The eval tier first: milliseconds, so a tree-shape mistake fails before
# anything is built.
(lib.mapAttrs mkEvalCheck evalGroups)
// {
  # --- run tier -------------------------------------------------------------
  # The Python suite: the prose claims, which need a real regex engine, and the
  # pointer heuristics -- including the `../` escape rule, which cannot be an eval
  # assertion because it needs the write-verb heuristic to avoid flagging a path
  # a skill tells the reader to CREATE.
  tests =
    pkgs.runCommand "check-tests"
      {
        nativeBuildInputs = [
          python
          pkgs.git
        ];
      }
      ''
        cd ${srcWritable}
        # `no:cacheprovider`: the tree is a read-only store path, and pytest's
        # cache would only produce a permission warning.
        python -m pytest tests/ -q -p no:cacheprovider
        touch $out
      '';

  # Every mechanical claim in the prose, checked against the tree. Exits 1 on a
  # FALSE claim; a claim it cannot establish reports UNPROVEN rather than passing.
  claim-audit =
    pkgs.runCommand "check-claim-audit"
      {
        nativeBuildInputs = [
          python
          pkgs.bash
          pkgs.coreutils
        ];
      }
      ''
        cd ${srcWritable}
        python scripts/claim-audit.py
        touch $out
      '';

  # `setup.sh` against a stubbed `hermes`: the merge path can only be exercised by
  # lying to the script about the current config, and doing that against the real
  # config would edit it. The stub is the SCRIPT's dependency, not a stand-in for
  # the product -- `scripts/verify-live.py` is the check that uses the real one.
  setup-e2e =
    pkgs.runCommand "check-setup-e2e"
      {
        nativeBuildInputs = [
          pkgs.bash
          pkgs.coreutils
        ];
      }
      ''
        cd ${srcWritable}
        bash tests/e2e/test_setup.sh
        touch $out
      '';
}
