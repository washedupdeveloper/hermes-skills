# Run tier: what needs an interpreter. The eval tier is `nix/tests.nix`.
#
# Every rule about the skills themselves lives in `scripts/validate.py`, which runs on
# any machine with a Python 3 standard library. This file adds the checks a maintainer
# wants on top of it — the Python suite, the prose claim audit, the formatter — and the
# eval-tier assertions about this repository's own CI. Nothing here is required to use
# the library: `python3 scripts/validate.py` is the gate for that.
{
  lib,
  pkgs,
  src,
}:
let
  # One check per group, so `--keep-going` reports every failing group, not just the first.
  evalGroups = import ./tests.nix { inherit lib src pkgs; };

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

  # Writable copy: the store is read-only, and pytest writes caches. `__pycache__` is
  # stripped so stale bytecode cannot be what makes a test pass.
  srcWritable = pkgs.runCommand "hermes-skills-src" { } ''
    cp -r ${src} $out
    chmod -R u+w $out
    patchShebangs $out
    find $out -name __pycache__ -type d -prune -exec rm -rf {} +
  '';
in
# Eval tier first: milliseconds, so a tree-shape mistake fails before anything is built.
(lib.mapAttrs mkEvalCheck evalGroups)
// {
  # The library's own gate, exactly the command a non-Nix user runs.
  validate =
    pkgs.runCommand "check-validate"
      {
        nativeBuildInputs = [ python ];
      }
      ''
        cd ${srcWritable}
        python3 scripts/validate.py
        touch $out
      '';

  # The routing claim: a prompt that names a task selects exactly one skill.
  # `--strict` fails on a tie, a miss, or a score below library/routing.json's floor.
  routing =
    pkgs.runCommand "check-routing"
      {
        nativeBuildInputs = [ python ];
      }
      ''
        cd ${srcWritable}
        python3 scripts/routing-score.py --strict
        touch $out
      '';

  # The Python suite: shipped code under test, and the negative controls that prove the
  # gate's rules fire.
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
        # `no:cacheprovider`: the tree is a store copy, and pytest's cache would only
        # produce a permission warning.
        #
        # `HERMES_SKILLS_STRICT_SKIPS=1` turns any skip into a failure: a test that
        # cannot run is a failure, not a pass. The host-side check moved out of pytest
        # to `scripts/host_loader_check.py`, where it can be run on a machine that has
        # Hermes installed.
        HERMES_SKILLS_STRICT_SKIPS=1 python -m pytest tests/ -q -p no:cacheprovider
        touch $out
      '';

  # Every mechanical claim in the prose, checked against the tree: exit 1 on a FALSE claim,
  # UNPROVEN (never a pass) on one it cannot establish.
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

  # The formatter, enforced, over every Nix file in the tree.
  formatting =
    pkgs.runCommand "check-formatting"
      {
        nativeBuildInputs = [
          pkgs.nixfmt
          pkgs.findutils
        ];
      }
      ''
        cd ${src}
        mapfile -t files < <(find . -name '*.nix' | sort)
        # Fail closed: a scan over nothing passes, and would look identical to a clean tree.
        if [ "''${#files[@]}" -lt 5 ]; then
          echo "only ''${#files[@]} Nix files found; the scan is not reading the tree" >&2
          exit 1
        fi
        if ! nixfmt --check "''${files[@]}"; then
          echo "the files above are not formatter-clean; run: nixfmt <path>" >&2
          exit 1
        fi
        touch $out
      '';
}
