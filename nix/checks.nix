# Run tier: what needs an interpreter. The eval tier is `nix/tests.nix`.
#
# NO BUILD TIER, deliberately: Hermes reads `external_dirs` in place, so the simulated
# "shipped" tree an earlier version built was fiction.
# See docs/adr/0001-reference-not-symlink.md.
# End-to-end is `scripts/verify-live.py` — it needs the real binary, so it cannot be a flake
# check; `.github/workflows/ci.yml` runs it in its own job.
{
  lib,
  pkgs,
  src,
}:
let
  # One check per group, so `--keep-going` reports every failing group, not just the first.
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

  # Writable copy: the store is read-only, and pytest and the audit write caches.
  # `__pycache__` is stripped so stale bytecode cannot be what makes a test pass.
  # `patchShebangs` is load-bearing: no `/usr/bin/env` in the sandbox, so `claim-audit.py`
  # exec'ing `setup.sh` died with a FileNotFoundError naming the script, not the interpreter.
  # The `sed` reaches the heredoc stub `hermes` in `tests/e2e/test_setup.sh` (its shebang is
  # not line 1); patched here only — the repo's test still runs on a real machine.
  srcWritable = pkgs.runCommand "hermes-skills-src" { } ''
    cp -r ${src} $out
    chmod -R u+w $out
    patchShebangs $out
    sed -i -E "s|^#![[:space:]]*/usr/bin/env[[:space:]]+bash\$|#!${pkgs.bash}/bin/bash|" \
      $out/tests/e2e/test_setup.sh
    find $out -name __pycache__ -type d -prune -exec rm -rf {} +
  '';
in
# Eval tier first: milliseconds, so a tree-shape mistake fails before anything is built.
(lib.mapAttrs mkEvalCheck evalGroups)
// {
  # --- run tier -------------------------------------------------------------
  # The Python suite: the prose claims (a real regex engine) and the `../` escape rule,
  # which cannot be eval because it needs the write-verb heuristic to avoid flagging a
  # path a skill tells the reader to CREATE.
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

  # The formatter, enforced rather than requested. Four files had drifted by the time this was
  # added — which is what an unenforced style rule does — and the drift was only visible because a
  # council reviewer ran the tool by hand. One file is exempt and its presence is asserted: the
  # golden target's bytes ARE the fixture a golden diff compares, so reformatting it would change
  # what that test measures.
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
        exempt='./skills/autonomous-ai-agents/council/tests/golden/target/modules/base.nix'
        if [ ! -f "$exempt" ]; then
          echo "the exempt golden fixture is missing: $exempt" >&2
          exit 1
        fi
        mapfile -t files < <(find . -name '*.nix' -not -path "$exempt" | sort)
        # Fail closed: a scan over nothing passes, and would look identical to a clean tree.
        if [ "''${#files[@]}" -lt 10 ]; then
          echo "only ''${#files[@]} Nix files found; the scan is not reading the tree" >&2
          exit 1
        fi
        if ! nixfmt --check "''${files[@]}"; then
          echo "the files above are not formatter-clean; run: nixfmt <path>" >&2
          exit 1
        fi
        touch $out
      '';

  # `setup.sh` against a stubbed `hermes`: the merge path needs a fake current config, and
  # using the real one would edit it. The stub is the SCRIPT's dependency, not the product —
  # `scripts/verify-live.py` is the check that uses the real binary.
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
