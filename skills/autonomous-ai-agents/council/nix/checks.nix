# This repo's own gates: the checks and the devshell. Kept out of
# nix/flake-module.nix so importing that module gives a consumer the packages and
# nothing else — the suite is about THIS tree. Tiers: docs/NIX.md.
{
  config,
  lib,
  inputs,
  ...
}:
let
  builders = import ./builders.nix {
    inherit lib;
    nixpkgs = inputs.nixpkgs or { };
  };

  # The eval tier, as groups of `lib.runTests` assertions: one check per group so
  # `--keep-going` reports every failing group. `pkgs` is a parameter because the
  # flake-level config carries no package set.
  evalGroups =
    pkgs:
    import ./tests.nix {
      inherit lib pkgs;
      inherit (config) flake systems;
    };

  mkEvalCheck =
    pkgs: group: tests:
    let
      failures = lib.runTests tests;
    in
    if failures == [ ] then
      pkgs.runCommand "check-${group}" { } "touch $out"
    else
      lib.debug.throwTestFailures { inherit failures; };

  # The devshell banner names the pin, from this module's own `inputs`.
  nixpkgsRev = inputs.nixpkgs.rev or "unknown";
in
{
  perSystem =
    { pkgs, ... }:
    {
      checks =
        let
          tc = builders.mkToolchain pkgs;
          # Shipped tree and dev tree; checks.commands asserts the difference is
          # EXACTLY the audience split in the CLI's verb table.
          fw = builders.mkFramework pkgs "user";
          fwDev = builders.mkFramework pkgs "dev";
          app = builders.mkDispatcher pkgs "user";
          dev = builders.mkDispatcher pkgs "dev";

          # Copied writable: the store is read-only and pytest writes caches.
          src = pkgs.runCommand "review-council-src" { } ''
            cp -r ${../.} $out
            chmod -R u+w $out
          '';

          # Linters run against this, not `src`: tests/golden is fixture data and
          # its line count is the golden suite's kloc — formatting it would move
          # every pinned score.
          srcLint = pkgs.runCommand "review-council-src-lint" { } ''
            cp -r ${../.} $out
            chmod -R u+w $out
            rm -rf $out/tests/golden
          '';
        in
        # Eval tier first: milliseconds, so a wiring mistake fails before anything
        # is built.
        (lib.mapAttrs (mkEvalCheck pkgs) (evalGroups pkgs))
        // {
          # The declarative path's two artifacts: without them it is exercised only
          # by a user's switch, a late place to find a typo.
          skill-layout = pkgs.runCommand "check-skill-layout" { } ''
            s=${builders.mkSkill pkgs}
            for f in SKILL.md flake.nix flake.lock \
                     scripts/council.py scripts/council_loop.py \
                     assets/rubrics/reviewer-security/SKILL.md \
                     assets/bots/council-orchestrator/profile.yaml \
                     tests/golden/expect.json; do
              test -f "$s/$f" || { echo "missing from .#skill: $f" >&2; exit 1; }
            done
            # Every path the deployed flake.nix IMPORTS must ship with it: the
            # hand-written list above asserts existence, this derives the
            # requirement. Comments are stripped first so a doc reference is not
            # mistaken for an import.
            sed 's/#.*$//' "$s/flake.nix" \
              | grep -oE '\./nix/[A-Za-z0-9_./-]+' | sort -u > refs.txt
            # A check that cannot fail verifies nothing: if the pattern above
            # stops matching, this fails instead of silently passing.
            test -s refs.txt \
              || { echo "found no nix/ imports in the deployed flake.nix -- the extraction broke" >&2; exit 1; }
            while IFS= read -r rel; do
              test -f "$s/''${rel#./}" \
                || { echo "the deployed flake imports $rel, which is not shipped" >&2; exit 1; }
            done < refs.txt

            # The copier never ships: shipping it once made the deployed suite
            # import a missing file and run zero tests.
            test ! -e "$s/scripts/sync_to_skill.py" \
              || { echo "the copier shipped in .#skill" >&2; exit 1; }
            touch $out
          '';

          # §1: formatting is a binary gate, over every Nix file.
          nixfmt = pkgs.runCommand "check-nixfmt" { nativeBuildInputs = [ tc ]; } ''
            cd ${srcLint}
            find . -name '*.nix' -not -path '../.review-council/*' -print0 \
              | xargs -0 -r nixfmt --check
            touch $out
          '';

          # §1: statix lints. A non-zero exit must fail the check.
          statix = pkgs.runCommand "check-statix" { nativeBuildInputs = [ tc ]; } ''
            cd ${srcLint}
            statix check .
            touch $out
          '';

          # Dead Nix code — the class the framework's own probes report on.
          deadnix = pkgs.runCommand "check-deadnix" { nativeBuildInputs = [ tc ]; } ''
            cd ${srcLint}
            deadnix --fail .
            touch $out
          '';

          # The suite is a gate, not a CI nicety. `pkgs.git` is a real dependency:
          # baseline.py's changed_files shells out to `git diff` and `git ls-files`.
          tests =
            pkgs.runCommand "check-tests"
              {
                nativeBuildInputs = [
                  tc
                  pkgs.git
                ];
              }
              ''
                cd ${src}
                python3 -m pytest tests/ -q
                touch $out
              '';

          # Run the way CI runs it, so a moved score fails with the number rather
          # than a pytest traceback. Through the DEV dispatcher: the fixtures live
          # in tests/, which only the dev tree carries.
          golden = pkgs.runCommand "check-golden" { nativeBuildInputs = [ tc ]; } ''
            ${dev}/bin/council golden --check
            touch $out
          '';

          # The version policy as a gate (docs/VERSIONING.md): pyproject and the
          # newest CHANGELOG release must agree, releases descend, `[Unreleased]`
          # first. No git in the sandbox, so the tag half is CI's (`--tag`).
          version = pkgs.runCommand "check-version" { nativeBuildInputs = [ tc ]; } ''
            REVIEW_COUNCIL_DISPATCHED=1 python3 ${src}/scripts/version.py check
            touch $out
          '';

          # The toolchain must WORK, not merely exist: a bare symlinkJoin has no
          # importable pytest runtime deps.
          toolchain-built = pkgs.runCommand "check-toolchain" { } ''
            # Every tool the gate scores must RUN, not merely exist: a broken
            # gitleaks or shellcheck here fails instead of silently capping beta.
            for b in statix deadnix nixfmt python3 pytest gitleaks shellcheck; do
              test -x ${tc}/bin/$b
            done
            # No nativeBuildInputs here, so nothing is on PATH -- hence the
            # ${tc}/bin prefix on every line below.
            ${tc}/bin/gitleaks version >/dev/null
            ${tc}/bin/shellcheck --version >/dev/null
            ${tc}/bin/python3 -c 'import pytest, pluggy'
            touch $out
          '';

          # THE ANALYZER MATRIX. `toolchain-built` asserts binaries exist; this
          # asserts the analyzers execute and parse — what `council probes` feeds
          # into beta. A tool present but broken (wrong version, missing dep,
          # unparsable output) otherwise lowers beta silently, leaving the score to
          # the LLM's judgement. Runs on every system in `systems`, so darwin is
          # covered by the same claim.
          probes =
            pkgs.runCommand "check-probes"
              {
                nativeBuildInputs = [ tc ];
              }
              ''
                mkdir -p fixture
                printf 'def add(a, b):\n    return a + b\n' > fixture/main.py
                printf '{ }\n' > fixture/flake.nix
                # shellcheck reports "no shell files in the tree" without one, so
                # the fixture needs a .sh file for that probe to reach the tool.
                printf '#!/bin/sh\necho hi\n' > fixture/run.sh

                ${app}/bin/council probes --all --repo "$PWD/fixture" > probes.json

                ${tc}/bin/python3 - <<'PY'
                import json
                import sys

                doc = json.load(open("probes.json"))
                rows = doc["results"] if isinstance(doc, dict) and "results" in doc else doc
                ran = {r["tool"] for r in rows if r.get("ran")}

                # Every probe needing no fixture content must have RUN. `ran`, not
                # `parsed` and not success: `flake-check` runs and reports FAILED on
                # a fixture with no outputs, `osv-scanner` runs and finds nothing to
                # scan. Requiring a clean signal would assert something untrue
                # about a synthetic fixture.
                required = {
                    "bandit", "bash-n", "complexity", "deadnix", "declared-rules",
                    "dep-graph", "flake-check", "gitleaks", "mypy", "nix-eval",
                    "nixfmt", "osv-scanner", "py-compile", "ruff", "secret-grep",
                    "shellcheck", "statix",
                }
                missing = sorted(required - ran)
                if missing:
                    print(f"probes that did NOT run: {missing}", file=sys.stderr)
                    print(f"ran: {sorted(ran)}", file=sys.stderr)
                    sys.exit(1)
                print(f"{len(ran)}/{len(rows)} probes ran")
                PY
                touch $out
              '';

          # One language: a .sh file in the tree means a second way to do things,
          # which is what this layout exists to prevent — every verb is a Python
          # module reached through `council`.
          no-shell-scripts = pkgs.runCommand "check-no-shell" { nativeBuildInputs = [ pkgs.findutils ]; } ''
            found=$(find ${src} -name '*.sh' -not -path '*/.git/*' | head -5)
            if [ -n "$found" ]; then
              echo "shell scripts in the tree:" >&2
              echo "$found" >&2
              exit 1
            fi
            touch $out
          '';

          # The onboarding path, and the thing most likely to rot unnoticed: they
          # reference a URL rather than this tree, so nothing else in the gate sees
          # them drift. A rotted template fails in someone else's repository.
          templates =
            pkgs.runCommand "check-templates"
              {
                nativeBuildInputs = [
                  pkgs.gnugrep
                  pkgs.diffutils
                ];
              }
              ''
                t=${../templates}

                for d in flake-parts home-manager; do
                  test -d "$t/$d" || { echo "missing template: $d" >&2; exit 1; }
                  test -n "$(ls -A "$t/$d")" || { echo "empty template: $d" >&2; exit 1; }
                done

                # 1. The flake template must point at the PUBLISHED repository: a
                #    local path works on the author's machine, nowhere else.
                f="$t/flake-parts/flake.nix"
                grep -q 'review-council.url = "github:washedupdeveloper/agentic-council"' "$f" \
                  || { echo "the flake template does not reference the published flake" >&2; exit 1; }
                if grep -qE 'review-council.url = "(path:|file:|/|\./)' "$f"; then
                  echo "the flake template references a local path, not the published flake" >&2
                  exit 1
                fi

                # 2. It must import the consumer-facing module, or it evaluates to
                #    an empty flake and the user gets nothing.
                grep -q 'review-council.flakeModules.default' "$f" \
                  || { echo "the flake template does not import flakeModules.default" >&2; exit 1; }

                # 3. Its systems must match THIS flake's, derived from flake.nix so
                #    adding a system without the template cannot slip through.
                sed -n '/systems = \[/,/\];/p' ${src}/flake.nix \
                  | grep -oE '"[a-z0-9_]+-[a-z0-9]+"' | tr -d '"' | sort > declared.txt
                sed -n '/systems = \[/,/\];/p' "$f" \
                  | grep -oE '"[a-z0-9_]+-[a-z0-9]+"' | tr -d '"' | sort > offered.txt
                # A check that cannot fail verifies nothing: if the pattern stops
                # matching, this fails instead of comparing two empty lists.
                test -s declared.txt \
                  || { echo "could not read a systems list from flake.nix" >&2; exit 1; }
                if ! diff -u declared.txt offered.txt; then
                  echo "the template's systems differ from the flake's" >&2
                  exit 1
                fi

                # 4. The home-manager template must import the module and enable it.
                h="$t/home-manager/council.nix"
                grep -q 'homeManagerModules.default' "$h" \
                  || { echo "the home-manager template does not import homeManagerModules.default" >&2; exit 1; }
                grep -q 'programs.council' "$h" \
                  || { echo "the home-manager template does not configure programs.council" >&2; exit 1; }

                touch $out
              '';

          # The command surface, driven by the app's own verb table: a renamed
          # module, a data file missing from the tree, or a dev verb leaking into
          # the shipped app is otherwise silent.
          commands =
            pkgs.runCommand "check-commands"
              {
                nativeBuildInputs = [
                  tc
                  pkgs.jq
                ];
              }
              ''
                    ${app}/bin/council --verbs-json > verbs.json

                    # 1. every USER verb's module ships, no DEV verb's does. This
                    #    asserts the shipping manifest against the CLI's own verb
                    #    table, so an unlisted module or a leaked dev module fails.
                    jq -r '.[] | select(.audience=="user") | .script' verbs.json | sort -u > user-scripts.txt
                    while IFS= read -r s; do
                      test -f ${fw}/scripts/$s || { echo "shipped tree is missing scripts/$s" >&2; exit 1; }
                    done < user-scripts.txt

                    jq -r '.[] | select(.audience=="dev") | .script' verbs.json | sort -u > dev-scripts.txt
                    while IFS= read -r s; do
                      test -f ${fwDev}/scripts/$s || { echo "dev tree is missing scripts/$s" >&2; exit 1; }
                      if test -e ${fw}/scripts/$s; then
                        echo "scripts/$s belongs to a dev verb but ships in the image" >&2
                        exit 1
                      fi
                    done < dev-scripts.txt

                    # 2. the data files the modules resolve relative to themselves
                    for f in calibration.json eval-baseline.json score_reviews.py probes.py toolchain.py hermes_home.py hermes.py; do
                      test -f ${fw}/scripts/$f || { echo "shipped tree is missing scripts/$f" >&2; exit 1; }
                    done

                    # 3. the layout the modules derive their root from
                    test -d ${fw}/bots || { echo "shipped tree is missing bots/" >&2; exit 1; }
                    test -d ${fw}/skills || { echo "shipped tree is missing skills/" >&2; exit 1; }

                    # 3b. and the shipped tree carries nothing a review does not run
                    for f in tests pyproject.toml README.md flake.nix flake.lock; do
                      if test -e ${fw}/$f; then
                        echo "$f ships but nothing at review time reads it" >&2
                        exit 1
                      fi
                    done

                    # 4. the bare command is informative and succeeds
                    ${app}/bin/council > /dev/null || { echo "council with no args failed" >&2; exit 1; }
                    ${app}/bin/council --help > /dev/null || { echo "council --help failed" >&2; exit 1; }

                    # 5. every user verb starts. --help is safe on all: argument
                    #    parsers answer it, acting verbs get it from the dispatcher.
                    jq -r '.[] | select(.audience=="user") | .verb' verbs.json > user-verbs.txt
                    while IFS= read -r v; do
                      ${app}/bin/council $v --help > /dev/null || { echo "council $v --help failed" >&2; exit 1; }
                    done < user-verbs.txt

                    # 6. the audience split is real: a dev verb must NOT be in the shipped
                    #    app, and MUST be in the devshell's.
                    jq -r '.[] | select(.audience=="dev") | .verb' verbs.json > dev-verbs.txt
                    while IFS= read -r v; do
                      if ${app}/bin/council $v --help > /dev/null 2>&1; then
                        echo "council $v is dev-only but the shipped app accepts it" >&2
                        exit 1
                      fi
                      ${dev}/bin/council $v --help > /dev/null || { echo "council $v --help failed in the devshell" >&2; exit 1; }
                    done < dev-verbs.txt

                    # 7. setup dispatches, and rejects a bad sub-verb rather than doing
                    #    something surprising
                    if ${app}/bin/council setup nonsense > /dev/null 2>&1; then
                      echo "council setup accepted an unknown sub-verb" >&2
                      exit 1
                    fi

                    # 8. an unknown verb is refused, not silently treated as a repo path
                    if ${app}/bin/council definitely-not-a-verb > /dev/null 2>&1; then
                      echo "council accepted an unknown verb" >&2
                      exit 1
                    fi

                    # 9. the modules are not programs: a direct invocation must be
                    #    REFUSED and the same verb through the CLI must WORK, so this
                    #    fails both when the guard is dropped and when it is too
                    #    eager.
                    if python3 ${fw}/scripts/probes.py --list > /dev/null 2>&1; then
                      echo "scripts/probes.py ran without going through council" >&2
                      exit 1
                    fi
                    ${app}/bin/council probes --list > /dev/null || { echo "council probes --list failed" >&2; exit 1; }
                touch $out
              '';
        }
        # Same darwin guard as `container` (dockerTools cannot build a Linux
        # userspace from darwin). Building it IS the proof: a pure derivation over
        # the runtime tree's attrs, output is a tarball, no docker daemon involved —
        # so this can be a check where the VM test (KVM) cannot, and the image needs
        # no separate CI job.
        // lib.optionalAttrs pkgs.stdenv.hostPlatform.isLinux {
          container = pkgs.runCommand "check-container" { } ''
            test -s ${builders.mkContainer pkgs}
            touch $out
          '';
        };

      devShells = {
        default = pkgs.mkShell {
          name = "review-council";
          packages = [
            # The QA toolchain — the same set that ships in the container, so the
            # devshell cannot pass where the product fails.
            (builders.mkToolchain pkgs)
            # Contributor DX: LSPs, closure browsers, density meters. Devshell-only
            # by design — the product carries only what a review runs.
            (builders.mkDevTools pkgs)
            (builders.mkActivate pkgs)
            # The FULL verb set, dev verbs included: the only surface with
            # `council ablate` / `calibrate` / `corpus`.
            (builders.mkDispatcher pkgs "dev")
          ];
          shellHook = ''
            echo "review-council devshell — pinned toolchain on PATH"
            echo "  nixpkgs: ${nixpkgsRev}"
            echo "  qa:      $(command -v statix >/dev/null && echo statix) $(command -v deadnix >/dev/null && echo deadnix) $(command -v nixfmt >/dev/null && echo nixfmt) $(command -v ruff >/dev/null && echo ruff) $(command -v gitleaks >/dev/null && echo gitleaks) $(command -v shellcheck >/dev/null && echo shellcheck)"
            echo "  dx:      $(command -v nixd >/dev/null && echo nixd) $(command -v nil >/dev/null && echo nil) $(command -v nix-tree >/dev/null && echo nix-tree) $(command -v tokei >/dev/null && echo tokei) $(command -v jq >/dev/null && echo jq)"
            echo "  run:     council --help   (every verb; the shipped app has the user ones)"
          '';
        };
      };
    };
}
