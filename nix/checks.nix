# The build tier and the run tier: everything the eval tier cannot answer.
#
# `nix/tests.nix` explains the rule. In short: a property of the SOURCE files is
# an eval assertion, a property of the SHIPPED artifact is a build check, and
# behaviour -- a script doing something, prose checked against the tree -- is the
# only tier that needs an interpreter.
#
# The artifact is not the source tree. An installer copies a skill directory, so
# a skill that points at a file outside its own directory works here and breaks
# on the machine that loads it. That is the claim `skills-shipped` makes, and it
# is the one this repo could not make before.
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

  # What an installer produces: `SKILL.md` plus the four support directories,
  # and nothing else. Anything a skill needs must live inside its own directory.
  shipped = pkgs.runCommand "hermes-skills-shipped" { } ''
    mkdir -p $out
    for d in ${src}/skills/*/*/; do
      [ -f "$d/SKILL.md" ] || continue
      category=$(basename "$(dirname "$d")")
      name=$(basename "$d")
      mkdir -p "$out/$category/$name"
      cp "$d/SKILL.md" "$out/$category/$name/"
      for sub in references templates assets scripts; do
        if [ -d "$d/$sub" ]; then cp -r "$d/$sub" "$out/$category/$name/"; fi
      done
    done
    chmod -R u+w $out
  '';
in
# The eval tier first: milliseconds, so a tree-shape mistake fails before
# anything is built.
(lib.mapAttrs mkEvalCheck evalGroups)
// {
  # --- build tier -----------------------------------------------------------
  # The shipped tree is self-contained, and it is the whole tree: a copier that
  # silently drops a skill, or a skill that points outside itself, fails here.
  skills-shipped =
    pkgs.runCommand "check-skills-shipped"
      {
        nativeBuildInputs = [
          pkgs.bash
          pkgs.coreutils
          pkgs.findutils
          pkgs.gnugrep
        ];
      }
      ''
        set -eu
        shopt -s nocasematch

        fail() { echo "$1" >&2; exit 1; }

        # A copier that ships nothing must not pass.
        shipped_count=$(find ${shipped} -mindepth 3 -maxdepth 3 -name SKILL.md | wc -l)
        [ "$shipped_count" -gt 0 ] || fail "the shipped tree carries no SKILL.md"

        # ...and it must ship every catalog skill the source has. Catalog entries
        # sit at exactly skills/<category>/<name>/SKILL.md; the rubrics and other
        # support files are deeper, which is what makes this a count of skills.
        source_count=$(find ${srcWritable}/skills -mindepth 3 -maxdepth 3 -name SKILL.md | wc -l)
        [ "$source_count" = "$shipped_count" ] \
          || fail "shipped $shipped_count skills, source has $source_count"

        # No skill may point at a file its own directory does not carry. The
        # write-verb skip is the same heuristic the Python suite uses: a path in a
        # prescriptive sentence names a file to CREATE, and a placeholder is not a
        # path.
        violations=$(mktemp)
        while IFS= read -r md; do
          dir=$(dirname "$md")
          while IFS= read -r line; do
            case "$line" in
              *write*|*create*|*add*|*author*|*generate*|*scaffold*|*produce*) continue ;;
            esac
            # A pointer that climbs out of the skill directory cannot resolve once
            # the directory is shipped on its own -- the copier carries the
            # directory, not the tree around it.
            for esc in $(printf '%s\n' "$line" \
              | grep -oE '`\.\./[^`[:space:]]+`' | tr -d '`'); do
              echo "''${md#${shipped}/} -> $esc (escapes the skill directory)" >> "$violations"
            done
            for rel in $(printf '%s\n' "$line" \
              | grep -oE '`(references|templates|assets|scripts)/[^`[:space:]]+`' \
              | tr -d '`'); do
              case "$rel" in *'<'*|*'>'*) continue ;; esac
              [ -e "$dir/$rel" ] || echo "''${md#${shipped}/} -> $rel" >> "$violations"
            done
          done < "$md"
        done < <(find ${shipped} -mindepth 3 -maxdepth 3 -name SKILL.md)

        if [ -s "$violations" ]; then
          echo "a shipped skill points at a file its own directory does not carry:" >&2
          cat "$violations" >&2
          exit 1
        fi

        # Nothing machine-generated ships, and no skill carries a CRLF.
        if find ${shipped} -name __pycache__ -o -name '*.pyc' | grep -q .; then
          fail "the shipped tree carries bytecode caches"
        fi
        if find ${shipped} -name '*.md' -print0 \
          | xargs -0 -r awk 'index($0, "\r") { print FILENAME; bad = 1 } END { exit bad }'; then
          :
        else
          fail "a shipped file carries CRLF"
        fi

        touch $out
      '';

  # --- run tier -------------------------------------------------------------
  # The retained Python suite: the prose claims, which need a real regex engine,
  # and the reference heuristics. Its Nix-checkable tests moved to nix/tests.nix.
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
  # config would edit it.
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
