{
  description = "review-council — pinned, declarative deterministic review toolchain";

  # Determinism contract (research/nix-tooling.md §0): every category score must
  # be reproducible from a pinned tool set on a pinned nixpkgs revision. Every
  # tool comes from this one input, pinned in flake.lock, so the set moves
  # atomically and `nix build .#toolchain` yields the same store path everywhere.
  #
  # ONE COMMAND. The modules under scripts/ stay separate programs; the INTERFACE
  # is unified. There is exactly one app, `council`, and the modules are its
  # verbs:
  #
  #     nix run .#council -- review <repo>
  #     nix run .#council -- setup bots
  #
  # With no arguments it prints that list. Nothing in this repo is run by hand.
  #
  # `audience` is load-bearing, not documentation: the shipped app exposes `user`
  # verbs, the devshell also exposes `dev` ones, and checks.commands asserts the
  # split so it cannot decay into a comment.
  #
  # The toolchain, the framework tree, the command surface, the gates and the
  # formatter are declarative and pinned. The council LOOP cannot be: it spawns
  # non-deterministic LLM agents over the network, an effect rather than a build,
  # so it is exposed as a pinned interface — see docs/NIX.md.

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs =
    { self, nixpkgs }:
    let
      inherit (nixpkgs) lib;

      # No x86_64-darwin: nixpkgs 26.11 dropped it, so advertising it makes
      # `nix flake show` error instead of listing anything.
      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "aarch64-darwin"
      ];
      forAllSystems = f: lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});

      # Every tool the framework's rubrics and research reports name, grouped by
      # the reason it is here. Order is documentation; membership is the contract.
      #
      # Scope rule: this list is research/nix-tooling.md §0 plus the Python
      # toolchain DECISIONS #3 requires ("language-agnostic framework, Python
      # first-class") and the general analyzers the rubrics name. Anything NOT in
      # the §0 inventory needs a reason to be here.
      toolNames = [
        # --- Nix / NixOS / Clan — the framework's primary scope ---
        "nix" # the CLI itself: `nix flake check`, `nix eval`
        "nixfmt" # RFC 166 formatter. nixpkgs-fmt is DEPRECATED (RFC 101).
        "nixfmt-tree" # treefmt preconfigured for nixfmt; the repo `formatter`
        "treefmt" # `treefmt --ci` — aggregate formatter gate
        "statix" # nix lints; `statix check . -o json`
        "deadnix" # dead nix code; `deadnix --output-format json --fail .`
        "nixd" # LSP, option-system aware
        "nil" # LSP + `nil diagnostics`
        "nix-tree" # closure browser (--dot, --diff)
        "nix-diff" # derivation-level diff
        "nix-fast-build" # parallel eval+build of `checks`
        "nix-du" # GC-root disk attribution
        "vulnix" # store / CVE scanner

        # --- secret + supply chain ---
        "gitleaks" # secret scanning (wired as a pre-commit hook upstream)
        # Dependency CVEs for every ecosystem the framework covers: PyPI, npm,
        # cargo, Go, Ruby, Composer. It replaces pip-audit, npm-audit and
        # cargo-audit with ONE binary, and unlike them it has no runtime
        # dependency of its own -- see the note where pip-audit used to be.
        "osv-scanner"

        # --- density denominators (findings per KLOC) ---
        "tokei" # `tokei -t Nix --output json`
        "cloc" # `cloc --json --include-lang Nix`

        # --- JSON glue ---
        "jq"

        # --- Python (DECISIONS #3: Python first-class) ---
        "ruff" # lint + format
        "mypy" # static types
        "pytest" # test runner
        "bandit" # security lint

        # pip-audit is DELIBERATELY NOT here, and this is not a preference.
        # Its nixpkgs wrapper execs `sys.executable -m pip --version` before it
        # will audit anything, and the interpreter it runs under ships no pip --
        # so the scanner was on PATH and could not execute at all. Measured, not
        # assumed: `pip-audit -r requirements.txt` fails with
        #   CalledProcessError: ['.../python3.14', '-m', 'pip', '--version']
        # Adding pip to the toolchain's python env does not help, because the
        # wrapper runs under a different interpreter. osv-scanner above does the
        # same job for every ecosystem with no runtime dependency to get wrong.

        # --- general ---
        "shellcheck" # shell lint
        "yamllint" # yaml lint

        # DELIBERATELY EXCLUDED — semgrep.
        #   (a) It is not in research/nix-tooling.md §0. The regulations put Nix
        #       security on statix + gitleaks, and Python security on bandit +
        #       a dependency scanner. semgrep was an addition of mine, not a
        #       requirement.
        #   (b) It does not build on this nixpkgs revision: its
        #       pythonRuntimeDepsCheck fails with
        #       "pyjwt~=2.13.0 not satisfied by version 2.14.0".
        # A tool that cannot build is worse than an absent one: it fails the whole
        # toolchain, so the framework loses every other analyzer with it.
      ];

      # ── What ships, and what does not ────────────────────────────────────────
      # Every module under scripts/, split by whether a REVIEW needs it. This is
      # the shipping manifest: `runtimeModules` is copied into the framework tree,
      # so it is what the app, the devshell and the image carry; `devModules` are
      # development verbs, present in the repo and the devshell only.
      #
      # The split is not cosmetic. Several of these files act rather than report
      # — `corpus` plants defects in a repository, `setup skill` prunes a skill
      # deployment, `calibrate` and `ablate` spend real agent turns — and a file
      # that is not in the image cannot be run inside it. checks.commands asserts
      # this list against the CLI's own verb table, so a new verb cannot ship
      # without its module and a dev verb cannot leak into the shipped tree.
      runtimeModules = [
        "council.py" # the dispatcher: the one entry point
        "council_loop.py" # review
        "score_reviews.py" # gate
        "doctor.py" # doctor
        "probes.py" # probes
        "swarm.py" # swarm
        "sample.py" # sample
        "merge.py" # merge
        "baseline.py" # baseline
        "toolchain.py" # setup toolchain
        "install_bots.py" # setup bots
        "install_dispatcher.py" # setup dispatcher
        "init.py" # setup init — the guided first-run path
        # setup skill — ships because it is how a user WITHOUT nix or docker gets
        # the rest of the tree. It was dev-only until the user-facing verb existed,
        # and a module reachable from the shipped surface has to be in it.
        "sync_to_skill.py"
        "goal.py" # goal — the /goal contract and quality-gate emitter
        "council_config.py" # shared: the one place configuration lives
        "entrypoint.py" # the container ENTRYPOINT
        "hermes_home.py" # shared: where HERMES_HOME is
        "hermes.py" # shared: locate the launcher, report what can be known
        "calibration.json" # the threshold + curves
        "eval-baseline.json" # the nix-eval-time baseline
      ];

      devModules = [
        "ablate.py" # dev/ablate
        "calibrate.py" # dev/calibrate
        "golden.py" # dev/golden
        "inject_defects.py" # dev/corpus
      ];

      # Resolve a tool name to a package. Top-level attrs first; then the Python
      # package set, because several tools (pytest, …) only exist as
      # python3Packages.<name> and are not re-exported at the top level.
      # `or` rather than if/else, per statix's suggestion.
      resolveTool = pkgs: name: pkgs.${name} or (pkgs.python3Packages.${name} or null);

      # Build the toolchain as ONE store path with a merged bin/ AND the pinned
      # inventory JSON alongside it. symlinkJoin (not buildEnv) because buildEnv
      # only links the pathsToLink subtrees, which would hide the inventory.
      # Missing attrs are skipped rather than failing eval — the set is still
      # deterministic for a given nixpkgs revision, and the inventory reports the
      # omissions honestly instead of silently shipping a thinner toolchain.
      mkToolchain =
        pkgs:
        let
          resolved = builtins.listToAttrs (
            map (n: {
              name = n;
              value = resolveTool pkgs n;
            }) toolNames
          );
          present = builtins.filter (n: resolved.${n} != null) toolNames;
          absent = builtins.filter (n: resolved.${n} == null) toolNames;

          # The test runner needs its TRANSITIVE deps, which a symlinkJoin cannot
          # supply: each python3Packages derivation keeps its runtime deps in its
          # OWN store path, reachable only through that derivation's bin/ wrapper.
          # Joining the outputs therefore yields site-packages/pytest with no
          # pluggy / iniconfig / packaging, and `python3 -m pytest` dies with
          # "No module named 'pluggy'" even though the `pytest` wrapper works.
          # A withPackages env carries the whole closure, so build one and join
          # it: that is what puts a usable `python3` — with the test runner
          # importable — on the toolchain.
          pythonEnv = pkgs.python3.withPackages (ps: [ ps.pytest ]);

          inventory = pkgs.writeText "review-council-toolchain.json" (
            builtins.toJSON {
              nixpkgs = nixpkgs.rev or "unknown";
              system = pkgs.stdenv.hostPlatform.system;
              tools = builtins.listToAttrs (
                map (n: {
                  name = n;
                  value = resolved.${n}.version or "unknown";
                }) present
              );
              inherit absent;
            }
          );
          joined = pkgs.symlinkJoin {
            name = "review-council-toolchain";
            paths = map (n: resolved.${n}) present ++ [ pythonEnv ];
            postBuild = ''
              cp ${inventory} $out/review-council-toolchain.json
            '';
          };
        in
        joined // { inherit absent inventory; };

      # Puts the toolchain on PATH. Same store path the flake builds.
      mkActivate =
        pkgs:
        pkgs.writeShellScriptBin "review-council-toolchain-activate" ''
          set -eu
          toolchain="${mkToolchain pkgs}"
          export REVIEW_COUNCIL_TOOLCHAIN="$toolchain"
          export PATH="$toolchain/bin:$PATH"
          echo "review-council toolchain: $toolchain"
        '';

      # The tree the modules run from. They resolve their own root as
      # `dirname(__file__)/..`, so a store copy mirrors the repo layout. Paths
      # concerning the repo UNDER REVIEW never appear here — they arrive as
      # `--repo` or a run directory, which is what lets this live read-only.
      #
      # `audience` picks the contents, exactly as it picks the verb surface: the
      # shipped tree carries `runtimeModules` and the devshell carries those plus
      # `devModules` and the suite `council setup skill` mirrors. The shipped tree also
      # drops README/pyproject/flake.nix, which nothing at REVIEW time reads — the
      # toolchain arrives as an environment variable instead, so no runtime path
      # has to `nix build` a flake.
      #
      # `setup skill` is not a review, and it DOES need the flake: it installs it
      # into the deployment so the installed skill can build its own toolchain.
      # `flakeFiles` below is how it gets there from a tree that has none.
      mkFramework =
        pkgs: audience:
        let
          dev = audience == "dev";
          modules = runtimeModules ++ (if dev then devModules else [ ]);
        in
        pkgs.runCommand "review-council-framework" { } ''
          mkdir -p $out/scripts
          ${lib.concatMapStringsSep "\n" (n: "cp ${./scripts}/${n} $out/scripts/${n}") modules}
          cp -r ${./skills} $out/skills
          cp -r ${./bots} $out/bots
          ${lib.optionalString dev "cp -r ${./tests} $out/tests"}
          chmod -R u+w $out
          rm -rf $out/scripts/__pycache__ $out/tests/__pycache__
        '';

      # The deployable skill, laid out exactly as `council setup skill` writes it
      # into the library — but as a store path rather than a copy. That is the
      # whole point: a store path is read-only, so the deployment cannot be edited
      # in place and cannot drift from source, and the copier is not needed on this
      # path at all. Update is `nix flake update` + switch, pinned by flake.lock
      # like every other input. Design: docs/bootstrap.md. Decision: docs/adr/0004.
      #
      # `sync_to_skill.py` is excluded because the copier never ships itself. The
      # rubrics are the reviewer set plus the orchestrator, matching the live
      # deployment's assets/rubrics/.
      #
      # EVERY script ships, not the `user` audience set — verified against the live
      # deployment, which is the oracle here. The deployed suite exercises the dev
      # modules (ablate, calibrate, golden, inject_defects), so shipping the runtime
      # subset alone leaves four tests importing files that are not there: the same
      # failure the copier's self-exclusion caused. A mismatch is caught by
      # checks.skill-layout, which is why that check exists.
      mkSkill =
        pkgs:
        pkgs.runCommand "council-skill" { } ''
          mkdir -p $out/scripts $out/tests $out/assets/bots $out/assets/rubrics
          cp ${./skills}/council/SKILL.md $out/SKILL.md
          for s in ${./scripts}/*.py; do
            [ "$(basename "$s")" = sync_to_skill.py ] && continue
            cp "$s" $out/scripts/
          done
          # The gate's data files. The copier names these two explicitly too:
          # without them score_reviews falls back to the uncalibrated count-based
          # curve, so the deployment would score differently from the checkout.
          cp ${./scripts}/calibration.json $out/scripts/calibration.json
          cp ${./scripts}/eval-baseline.json $out/scripts/eval-baseline.json
          cp ${./tests}/*.py $out/tests/
          cp -r ${./tests}/golden $out/tests/golden
          cp -r ${./bots}/. $out/assets/bots/
          for r in ${./skills}/reviewer-* ${./skills}/review-council-orchestrator; do
            cp -r "$r" "$out/assets/rubrics/$(basename "$r")"
          done
          cp ${./flake.nix} $out/flake.nix
          cp ${./flake.lock} $out/flake.lock
          chmod -R u+w $out
          rm -rf $out/scripts/__pycache__ $out/tests/__pycache__
        '';

      # The two files that make the framework's toolchain buildable, as a small
      # store path: `setup skill` installs them into the deployment so a machine
      # with ONLY the skill can `nix build <skill>#toolchain` — the fallback
      # toolchain.py takes when nothing bakes the path.
      #
      # They are deliberately NOT in the framework tree (the shipped tree carries
      # what a review runs, and the toolchain arrives baked). But that made a sync
      # run from a nix tree find no flake to install and SKIP IT SILENTLY, leaving
      # a deployment whose flake.nix went stale forever with nothing to say so.
      # This is how the source reaches the sync from every entry point.
      flakeFiles =
        pkgs:
        pkgs.runCommand "review-council-flake-files" { } ''
          mkdir -p $out
          cp ${./flake.nix} $out/flake.nix
          cp ${./flake.lock} $out/flake.lock
        '';

      # The verb table lives in scripts/council.py, and checks.commands asks the
      # BUILT APP for it (`council --verbs-json`). It used to be duplicated here,
      # and the copy drifted: a verb existed in the CLI and not in the flake, so
      # nothing checked that its module shipped or that its --help worked. A table
      # that exists once cannot drift.
      # For the generated launchers and the container: a pure nix shell has no
      # coreutils, and dirname/cp/tar are load-bearing.
      shellDeps = pkgs: [
        pkgs.bash
        pkgs.coreutils
        pkgs.gnused
        pkgs.gnugrep
        pkgs.findutils
        pkgs.gnutar
        pkgs.gzip
      ];

      # ── The dispatcher ──────────────────────────────────────────────────────
      # ONE generated launcher. Its whole job is to put the pinned toolchain on
      # PATH and hand off to scripts/council.py, which owns the verb table, the
      # usage text and the dispatch — so the shipped app and the devshell run the
      # same code, with two env vars between them.
      #
      # The toolchain is BAKED, not discovered. `toolchain.py` falls back to
      # `nix build <tree>#toolchain` when nothing tells it the path, and the
      # shipped tree deliberately has no flake.nix for that to build. Baking it is
      # also the honest answer: this launcher was built against one store path, and
      # that path is what the build already fixed.
      #
      # REVIEW_COUNCIL_DISPATCHED is what makes this the only way in: every module
      # refuses a direct invocation without it. See scripts/council.py.
      mkDispatcher =
        pkgs: audience:
        let
          tc = mkToolchain pkgs;
          fw = mkFramework pkgs audience;
        in
        pkgs.writeShellApplication {
          name = "council";
          runtimeInputs = [ tc ];
          meta.description = "the review-council (no arguments lists its verbs)";
          text = ''
            export REVIEW_COUNCIL_AUDIENCE=${lib.escapeShellArg audience}
            export REVIEW_COUNCIL_TOOLCHAIN=${lib.escapeShellArg (toString tc)}
            export REVIEW_COUNCIL_FLAKE_DIR=${lib.escapeShellArg (toString (flakeFiles pkgs))}
            export REVIEW_COUNCIL_DISPATCHED=1
            exec python3 ${fw}/scripts/council.py "$@"
          '';
        };

      # ── The container image, defined once ───────────────────────────────────
      # `nix build .#container` (dockerTools) and the Dockerfile both build the
      # SAME runtime tree from these definitions. A second copy of any of it is
      # how "the image works but the Dockerfile does not" happens, which is the
      # one failure a reader cannot debug.

      # The runtime rootfs preparation. Both consumers run it with the image root
      # as the working directory, so every path here is relative.
      #
      # Unprivileged, so anything written into a mounted repo belongs to the
      # caller rather than root. A passwd entry is still required: nix resolves
      # $HOME through getpwuid() and fails without one.
      #
      # The home and the working directory are world-writable because the image
      # runs as uid 1000 and a CALLER IS NOT NECESSARILY 1000. `--user
      # "$(id -u):$(id -g)"` is how someone makes the mounted repo writable, and
      # it only helps if the in-image paths are writable by that uid too --
      # otherwise the run directory lands in the repo while the profile home
      # stays read-only, and the failure is a traceback rather than a message.
      imagePrep = ''
        mkdir -p etc home/council/.hermes repo tmp
        # dockerTools ships `etc` as a read-only symlink into the store; a plain
        # rootfs has no `etc` at all. mkdir covers the second, chmod the first.
        chmod u+w etc 2>/dev/null || true
        # The files may ALREADY exist and be read-only — a store path's copy, or a
        # second run of this script. `>` truncates an existing file and needs write
        # permission ON THE FILE, so without this the write fails and the content
        # silently stays whatever it was, which is the worst kind of wrong.
        chmod u+w etc/passwd etc/group 2>/dev/null || true
        echo 'root:x:0:0:root:/root:/bin/sh' > etc/passwd
        echo 'council:x:1000:1000:council:/home/council:/bin/sh' >> etc/passwd
        echo 'root:x:0:' > etc/group
        echo 'council:x:1000:' >> etc/group
        chmod 0777 home/council repo
        chmod -R 0777 home/council/.hermes
        # /tmp must exist and be writable by ANY uid, because the probes put
        # their scratch there. Without it `tempfile.mkdtemp()` falls back to the
        # working directory -- which is /repo, the repository under review -- so
        # a review left `tmpXXXX` directories in someone else's tree, and on a
        # read-only mount every probe that needs scratch would fail instead.
        chmod 1777 tmp
        # The entrypoint appends a passwd entry for the runtime uid when the
        # caller ran the container as themselves. `nix` resolves $HOME through
        # getpwuid and fails without one -- "cannot determine user's home
        # directory" -- which silently degrades every nix probe. It is a
        # disposable container, so the entry dies with it.
        chmod 0666 etc/passwd etc/group
        # Insurance rather than a fix for an observed failure. With no nix
        # database there is no lock file to open, but nix still wants to own
        # its per-user profile directory -- and the uid below is not root.
        # mkdir BEFORE the chmod, or the directory is created afterwards and
        # left mode 755.
        mkdir -p nix/var/nix/profiles/per-user/council
        chmod -R a+w nix/var/nix 2>/dev/null || true
      '';

      # The image's ENTRYPOINT. A generated launcher because the entrypoint needs
      # the pinned tools on PATH; the logic is scripts/entrypoint.py, which
      # refuses to run unless this variable is set.
      mkContainerEntrypoint =
        pkgs:
        let
          tc = mkToolchain pkgs;
          fw = mkFramework pkgs "user";
          deps = shellDeps pkgs;
        in
        pkgs.writeShellApplication {
          name = "council-entrypoint";
          runtimeInputs = [
            tc
            pkgs.bashInteractive
          ]
          ++ deps;
          text = ''
            export REVIEW_COUNCIL_FLAKE_DIR=${lib.escapeShellArg (toString (flakeFiles pkgs))}
            export REVIEW_COUNCIL_DISPATCHED=1
            exec python3 ${fw}/scripts/entrypoint.py "$@"
          '';
        };

      # The pinned `nix` CLI needs a configuration file, and a minimal image has
      # none: /etc/nix/nix.conf does not exist, so the experimental features are
      # OFF and `nix eval` / `nix flake check` -- what the nix probes actually run
      # -- fail with "experimental feature 'nix-command' is disabled". The probe
      # then reports ran=False and beta drops with nothing to explain it.
      #
      # `build-users-group` is cleared because a minimal image has no `nixbld`
      # group, and nix warns about that on every invocation.
      #
      # The conf cannot live in /etc: `etc` arrives from the toolchain as a
      # read-only symlink into the store. NIX_CONF_DIR points at it instead,
      # which also makes the configuration explicit rather than inherited.
      mkContainerNixConf =
        pkgs:
        pkgs.writeText "review-council-nix.conf" ''
          experimental-features = nix-command flakes
          build-users-group =
        '';

      # ── The container image ─────────────────────────────────────────────────
      # Built by Nix from the same flake.lock as the native deployment, and
      # published by CI, so running the council needs docker and nothing else.
      #
      # Layered, with no nix database: a store path's layer is content-addressed,
      # so an unchanged toolchain produces identical layer digests and a pull
      # fetches only what changed. Measured 99 layers. The TARBALL is 333 MiB
      # (348,761,461 bytes) and the image docker reports after `docker load` is
      # 2.33 GB (2,331,098,089) -- the layers are gzipped, so the download is
      # not the image. See docs/CONTAINER.md for what is verified and what is not.
      mkContainer =
        pkgs:
        let
          tc = mkToolchain pkgs;
          # The shipped tree: runtime modules only. The dev verbs are not in the
          # image at all, so they cannot be run inside it.
          fw = mkFramework pkgs "user";
          deps = shellDeps pkgs;

          entrypoint = mkContainerEntrypoint pkgs;

          # dockerTools merges a content store path's TOP-LEVEL entries into the
          # image root, so dropping the framework in as-is would scatter
          # scripts/, skills/ and bots/ across /. Nest it under /opt.
          # A symlink, not a copy: the tree is read-only either way, and the
          # modules resolve their own root as <here>/.. -- which lands on
          # /opt/review-council. Nothing hardcodes that: entrypoint.py derives it
          # from its own location, so the tree works from a checkout and an image alike.
          frameworkAt = pkgs.runCommand "review-council-framework-at-opt" { } ''
            mkdir -p $out/opt
            ln -s ${fw} $out/opt/review-council
          '';

          nixConf = mkContainerNixConf pkgs;

          nixConfAt = pkgs.runCommand "review-council-nix-conf-at-opt" { } ''
            mkdir -p $out/opt/nix
            cp ${nixConf} $out/opt/nix/nix.conf
          '';
        in
        pkgs.dockerTools.buildLayeredImage {
          name = "review-council";
          tag = "latest";
          # fixed, so two builds of the same inputs are comparable
          created = "1970-01-01T00:00:00Z";
          # `lib.unique`: bashInteractive and shellDeps' bash are the same store
          # path, and a duplicate breaks the image build.
          contents = lib.unique (
            [
              tc
              frameworkAt
              nixConfAt
              entrypoint
              pkgs.bashInteractive
              # `baseline.py`'s changed_files shells out to git (`git diff`,
              # `git ls-files --exclude-standard`), so --baseline cannot work in
              # the container without it. The framework's own test check needs it
              # too.
              pkgs.git
            ]
            ++ deps
          );
          # The writable dirs, the passwd/group entries and the mode fixes. One
          # definition, shared with the Dockerfile's rootfs — see imagePrep.
          extraCommands = imagePrep;
          config = {
            Entrypoint = [ "${entrypoint}/bin/council-entrypoint" ];
            Cmd = [ "--help" ];
            WorkingDir = "/repo";
            User = "1000:1000";
            Env = [
              # explicit: the entrypoint reads HERMES_HOME
              "HOME=/home/council"
              "HERMES_HOME=/home/council/.hermes"
              # the probes read this instead of running `nix build`
              "REVIEW_COUNCIL_TOOLCHAIN=${tc}"
              # the conf staged by nixConfAt; without it the nix probes fail
              "NIX_CONF_DIR=/opt/nix"
              "PYTHONUNBUFFERED=1"
            ];
          };
        };

      # The tools the Dockerfile's materialisation step needs, taken from nixpkgs
      # rather than from the base image.
      #
      # `nixos/nix` ships a minimal set and its toolset is not a contract: it has
      # `grep`, `cut`, `tar` and `readlink`, but NOT `sed` or `awk`, and `/bin`
      # holds only `sh`. The step below piped through `sed`, so `docker build`
      # died at the last instruction with `/bin/sh: line 1: sed: command not
      # found` -- and nothing before it could have caught that, because the
      # Dockerfile only parses until it runs.
      #
      # Declaring them here keeps the build pinned and explicit, and puts them in
      # the BUILDER only: none of this reaches the runtime image.
      mkImagePrepTools =
        pkgs:
        pkgs.symlinkJoin {
          name = "review-council-image-prep-tools";
          paths = with pkgs; [
            coreutils
            gnused
            gnugrep
            gnutar
            findutils
          ];
        };

      # The same runtime tree as a plain directory, for the Dockerfile. Its
      # CLOSURE is the image's content: the toolchain, bash, git and the
      # entrypoint are NAMED IN A FILE so nix records them as references. A
      # symlink alone is not a reference, and an analyzer missing from the
      # closure would show up only as a probe reporting ran=False inside the
      # container, with nothing to say why.
      mkImageRoot =
        pkgs:
        let
          tc = mkToolchain pkgs;
          fw = mkFramework pkgs "user";
          deps = shellDeps pkgs;
          entrypoint = mkContainerEntrypoint pkgs;
          nixConf = mkContainerNixConf pkgs;
          runtime = [
            tc
            entrypoint
            pkgs.bashInteractive
            pkgs.git
          ]
          ++ deps;
        in
        pkgs.runCommand "review-council-image-root" { } ''
          mkdir -p $out
          cd $out

          mkdir -p opt/nix bin
          ln -s ${fw} opt/review-council
          cp ${nixConf} opt/nix/nix.conf
          # A symlink, so the Dockerfile can name a stable path in ENV rather than
          # a store hash it cannot know at build time.
          ln -s ${tc} opt/toolchain

          # Merge the runtime's `bin` into /bin, which is what dockerTools does
          # with `contents`. Without it the analyzers are reachable only through
          # the entrypoint's PATH, so `docker run --entrypoint sh` finds none of
          # them -- a divergence from `.#container` that would surface only while
          # someone is already debugging.
          for d in ${lib.concatMapStringsSep " " (p: "${p}") runtime}; do
            [ -d "$d/bin" ] || continue
            for f in "$d"/bin/*; do
              [ -e "$f" ] || continue
              ln -sf "$f" "bin/$(basename "$f")"
            done
          done

          ${imagePrep}

          # The prep as a FILE, and the reason it is a file: nix makes
          # everything under a store path read-only, so the modes set just above
          # do NOT survive into the Dockerfile's copy — `tmp` arrives 0555, not
          # 1777, and a probe that needs scratch then fails. mkContainer needs no
          # such step because dockerTools runs extraCommands on the image root,
          # where modes are preserved; the Dockerfile re-runs this file. One
          # definition of the prep, two ways of applying it.
          mkdir -p .nix
          cp ${pkgs.writeText "review-council-image-prep.sh" imagePrep} .nix/prep.sh

          # The runtime closure, named so nix records it as a reference. A
          # symlink would cover the framework and the toolchain, but git and the
          # shell deps are reached only through the entrypoint, so name them all
          # explicitly rather than depending on that indirection.
          printf '%s\n' ${lib.concatMapStringsSep " " (p: "${p}") runtime} > .nix/closure
        '';

      # ── The NixOS VM test ───────────────────────────────────────────────────
      # Proves the council runs end-to-end in a clean NixOS VM with a Hermes
      # available: the real pinned probes, the real gate, a real verdict.
      #
      # The agent is a STUB, deliberately. What is under test is the harness —
      # the fan-out, the bucketing, the beta measurement, the gate. A real model
      # would make the test slow, non-deterministic and billable, and would test
      # the model rather than this repository. The stub honours the same CLI
      # contract a real Hermes does (`hermes -p <profile> chat -q <prompt>`, then
      # the file the prompt names), which is exactly what "assume Hermes is
      # available" means at this boundary.
      #
      # NOT in `checks`, deliberately: a VM test needs KVM, and putting it in the
      # gate would require every contributor's machine to have it. `nix build
      # .#vm-test` runs it; docs/CONTAINER.md says when to.
      mkStubHermes =
        pkgs:
        pkgs.writeScriptBin "hermes" ''
          #!${pkgs.python3}/bin/python3
          """A stand-in for the hermes CLI, honouring its contract.

          `hermes -p <profile> chat -q <prompt>`: reads the prompt, writes the file
          the prompt names. Dispatches on the prompt's shape, most specific first --
          the goals prompt also names a path, so it must be matched before the
          reviewer branch or it would be mistaken for a sample.
          """
          import json
          import os
          import re
          import sys
          from pathlib import Path

          OUT_PATH = re.compile(r"exactly this path:\s+(\S+)")
          DIMS = ["security", "correctness", "readability", "architecture", "performance"]


          def arg(flag):
              argv = sys.argv[1:]
              for i, value in enumerate(argv):
                  if value == flag and i + 1 < len(argv):
                      return argv[i + 1]
              return ""


          prompt = arg("-q") or arg("--query")

          # `--version` and `--help` come first: they carry no prompt, and without
          # this the stub would answer them with the aggregate branch and report a
          # nonsense version in the test log.
          if "--version" in sys.argv[1:] or "-V" in sys.argv[1:]:
              print("hermes (vm-test stub) 1.0.0")
              sys.exit(0)
          if not prompt:
              print("usage: hermes -p <profile> chat -q <prompt>")
              sys.exit(0)

          if "set this round's goals" in prompt:
              match = OUT_PATH.search(prompt)
              if match:
                  target = Path(match.group(1).strip())
                  target.parent.mkdir(parents=True, exist_ok=True)
                  target.write_text(json.dumps({
                      "round": 1,
                      "goals": [{"dimension": d, "objective": "vm-test goal: " + d,
                                 "acceptance": "vm-test acceptance", "focus": ["main.py"]}
                                for d in DIMS],
                  }))
              print("goals written")
              sys.exit(0)

          if "THE GOALS YOU SET FOR THIS ROUND" in prompt:
              print("goal review turn")
              sys.exit(0)

          match = OUT_PATH.search(prompt)
          if not match:
              print("aggregate turn")
              sys.exit(0)

          target = Path(match.group(1).strip())
          target.parent.mkdir(parents=True, exist_ok=True)
          findings = []
          scores = {d: 100 for d in DIMS}
          if os.environ.get("VM_STUB_DEFECT") == "high":
              # One open high finding, and every score still 100. That isolates the
              # BLOCKING rule: the aggregate passes and the gate must refuse a pass
              # anyway. A stub that also lowered the score would let a broken
              # blocking check pass this test.
              findings.append({
                  "id": "GEN-0001", "dimension": "correctness", "severity": "high",
                  "status": "open", "location": {"path": "main.py", "line_range": "3"},
                  "claim": "the vm-test stub injected this defect on purpose",
                  "falsifiable_check": "read main.py:3",
              })
          target.write_text(json.dumps({
              "reviewer": "council-generalist", "scores": scores,
              "findings": findings, "tools_run": [],
          }))
          print("sample written")
          sys.exit(0)
        '';

      mkVmTest =
        pkgs:
        pkgs.testers.runNixOSTest {
          name = "review-council-vm";

          nodes.machine =
            # `_`, not `{ ... }`: the module needs none of its arguments (the
            # council package comes from the enclosing scope), and statix's
            # empty-pattern rule rejects the idiomatic spelling.
            _: {
              # The council plus the pinned toolchain, so the probes are real.
              environment.systemPackages = [
                (mkDispatcher pkgs "user")
                (mkStubHermes pkgs)
                # The testScript reads JSON back with `python3 -c`; the dispatcher
                # puts python on ITS OWN path, not the machine's.
                pkgs.python3
              ];
              # Room for the toolchain closure and a run directory.
              virtualisation.diskSize = 4096;
              virtualisation.memorySize = 4096;
            };

          testScript = ''
            machine.start()
            machine.wait_for_unit("multi-user.target")

            # 0. a target repository for the council to review. Created first:
            #    `doctor --repo` refuses a path that is not a directory, and the
            #    detection checks below all name it.
            machine.succeed("mkdir -p /tmp/target")
            machine.succeed("printf 'def add(a, b):\\n    return a + b\\n' > /tmp/target/main.py")

            # 1. the launcher resolves and EXECUTES. `which` alone would pass on a
            #    file that cannot run, so the version is the check.
            version = machine.succeed("hermes --version").strip()
            machine.log(f"stub hermes version: {version}")

            # 2. detection, before any profiles exist. This is the honest negative:
            #    Hermes is installed and the council still cannot review, because
            #    its profiles are not there. A doctor that said "ready" here would
            #    be the bug this feature exists to prevent.
            doctor = machine.succeed("council doctor --repo /tmp/target 2>&1 || true")
            machine.log(doctor)
            assert "no-launcher" not in doctor, doctor
            assert "NO COUNCIL PROFILES" in doctor, (
                "doctor did not report the missing profiles:\n" + doctor)
            assert "no-profiles" in machine.succeed(
                "council doctor --repo /tmp/target --json 2>/dev/null | "
                "python3 -c 'import json,sys; print(json.load(sys.stdin)[\"hermes\"][\"verdict\"])'"
            ), "the JSON verdict disagrees with the rendered one"

            # 3. give the profiles a provider, as `council setup bots` + `hermes
            #    setup` would, and the verdict must move to ready.
            machine.succeed(
                "mkdir -p /root/.hermes/profiles/council-generalist "
                "/root/.hermes/profiles/council-orchestrator"
            )
            for profile in ("council-generalist", "council-orchestrator"):
                machine.succeed(
                    f"printf 'model:\\n  provider: custom\\n  api_key: test-only\\n' "
                    f"> /root/.hermes/profiles/{profile}/config.yaml"
                )
            ready = machine.succeed(
                "council doctor --repo /tmp/target --json 2>/dev/null | "
                "python3 -c 'import json,sys; print(json.load(sys.stdin)[\"hermes\"][\"verdict\"])'"
            ).strip()
            assert ready == "ready", f"expected ready, got {ready}"

            # 4. THE REVIEW. Real probes, real gate, real verdict.
            out = machine.succeed(
                "council review /tmp/target --mode advisory --max-rounds 1 "
                "--samples 1 --threshold 90 2>&1"
            )
            machine.log(out)
            assert "OUTCOME:" in out, out

            run_dir = machine.succeed(
                "ls -d /tmp/target/.review-council/*/ | tail -1"
            ).strip()
            machine.log(f"run dir: {run_dir}")

            # every dimension the gate reads must exist, or the round is an error
            for dim in ("security", "correctness", "readability", "architecture",
                        "performance"):
                machine.succeed(f"test -f {run_dir}/round-1/{dim}.json")

            outcome = machine.succeed(
                f"python3 -c 'import json; d=json.load(open(\"{run_dir}/outcome.json\")); "
                f"print(d[\"outcome\"], d[\"scores\"])'"
            ).strip()
            machine.log(f"outcome: {outcome}")
            assert "satisfied" in outcome, f"a clean stub should satisfy: {outcome}"

            # beta is measured from the run, and with the pinned toolchain present
            # the deterministic half is fully covered.
            probes = machine.succeed(
                f"python3 -c 'import json; d=json.load(open(\"{run_dir}/probes.json\")); "
                f"print(len([p for p in d if p[\"ran\"]]))'"
            ).strip()
            machine.log(f"probes that ran: {probes}")
            assert int(probes) > 0, "no probe ran in the VM"

            # 6. the gate must be able to FAIL on the BLOCKING rule alone: every
            #    score is 100, so the aggregate passes, and one open high finding
            #    must still refuse the pass. A test that only ever passes proves
            #    nothing about the gate.
            machine.succeed("rm -rf /tmp/target/.review-council")
            machine.succeed(
                "VM_STUB_DEFECT=high council review /tmp/target --mode advisory "
                "--max-rounds 1 --samples 1 --threshold 90 2>&1 || true"
            )
            blocked = machine.succeed(
                "python3 -c 'import json,glob; "
                "p=sorted(glob.glob(\"/tmp/target/.review-council/*/outcome.json\"))[-1]; "
                "d=json.load(open(p)); print(d[\"outcome\"], d[\"scores\"])'"
            ).strip()
            machine.log(f"blocked run: {blocked}")
            assert blocked.split()[0] != "satisfied", (
                f"a high finding did not block a passing aggregate: {blocked}")
            assert "[100.0]" in blocked, (
                f"the aggregate should have PASSED, so the block is the finding: {blocked}")

            # and the user-facing deliverable must name the blocker, or the reader
            # is told "not satisfied" with nothing to act on.
            blocked_dir = machine.succeed(
                "ls -d /tmp/target/.review-council/*/ | tail -1"
            ).strip()
            steps = machine.succeed(f"cat {blocked_dir}/next-steps.md")
            assert "GEN-0001" in steps, (
                f"next-steps.md does not name the blocking finding:\n{steps}")
            assert "Blocked by" in steps, steps

            # 7. the modules are still not programs, inside the VM too.
            machine.fail("python3 ${mkFramework pkgs "user"}/scripts/probes.py --list")
            machine.succeed("council probes --list >/dev/null")
          '';
        };
    in
    {
      packages = forAllSystems (
        pkgs:
        {
          toolchain = mkToolchain pkgs;
          # The deployable skill as a read-only store path — what
          # programs.council.mode = "external-dirs" points Hermes at.
          skill = mkSkill pkgs;
          # What ships: the runtime tree. `dev-framework` adds the development
          # verbs and the suite, which is what the devshell runs from — the same
          # split the `audience` of a verb expresses.
          framework = mkFramework pkgs "user";
          dev-framework = mkFramework pkgs "dev";
          # `nix shell .#review-council` — the command plus the analyzers on one
          # PATH, which is what you want when running it by hand.
          review-council = pkgs.symlinkJoin {
            name = "review-council";
            paths = [
              (mkDispatcher pkgs "user")
              (mkToolchain pkgs)
            ];
          };
          default = mkToolchain pkgs;
        }
        # The image is a Linux userspace; dockerTools cannot build one from
        # darwin. Guarded rather than left to fail on the darwin systems above.
        // lib.optionalAttrs pkgs.stdenv.hostPlatform.isLinux {
          # `nix build .#container` -> an OCI image tarball for `docker load`.
          container = mkContainer pkgs;
          # `nix build .#image-root` -> the same runtime tree as a directory,
          # whose closure is what the Dockerfile copies. Same definitions as
          # `container`, so the two paths cannot drift.
          image-root = mkImageRoot pkgs;
          # `nix build .#image-prep-tools` -> the build-only tools the Dockerfile
          # needs. Never part of the image; see mkImagePrepTools.
          image-prep-tools = mkImagePrepTools pkgs;
          # `nix build .#vm-test` -> runs the council end-to-end in a NixOS VM.
          # A VM test needs KVM, so it is NOT in `checks`: the fast gate must not
          # require hardware a contributor may not have.
          vm-test = mkVmTest pkgs;
        }
      );

      # `nix fmt` needs this output or it fails outright. Wrapped rather than
      # bare so that `nix fmt` and checks.nixfmt agree on scope: the check skips
      # tests/golden (fixture data whose line count IS the golden kloc), and a
      # bare formatter would rewrite it and move every pinned score.
      formatter = forAllSystems (
        pkgs:
        pkgs.writeShellScriptBin "treefmt" ''
          exec ${pkgs.nixfmt-tree}/bin/treefmt \
            --excludes 'tests/golden/*' \
            --excludes '.review-council/*' \
            "$@"
        ''
      );

      # The declarative path. Hermes runs user-level with its own HERMES_HOME, so
      # the skill it loads, the CLI on its PATH and the settings that point at both
      # are user state — a home-manager module is the scope that matches.
      #
      # Defaults come from THIS flake, so importing the module is the whole setup.
      # Usage is in nix/home-manager.md; the options and their reasoning are in
      # nix/module.nix.
      #
      # `nix flake check` knows a fixed set of output names and would skip this one
      # with a warning, so checks.module-evaluates evaluates it explicitly.
      homeManagerModules.default =
        { lib, pkgs, ... }:
        {
          imports = [ (import ./nix/module.nix) ];
          programs.council.package =
            lib.mkDefault
              self.packages.${pkgs.stdenv.hostPlatform.system}.review-council;
          programs.council.skill = lib.mkDefault self.packages.${pkgs.stdenv.hostPlatform.system}.skill;
        };

      devShells = forAllSystems (pkgs: {
        default = pkgs.mkShell {
          name = "review-council";
          packages = [
            (mkToolchain pkgs)
            (mkActivate pkgs)
            # The FULL verb set, dev verbs included. This is the only surface with
            # `council ablate` / `council calibrate` / `council corpus`, because
            # working on the framework is exactly what a devshell is for.
            (mkDispatcher pkgs "dev")
          ];
          shellHook = ''
            echo "review-council devshell — pinned toolchain on PATH"
            echo "  nixpkgs: ${nixpkgs.rev or "unknown"}"
            echo "  tools:   $(command -v statix >/dev/null && echo statix) $(command -v deadnix >/dev/null && echo deadnix) $(command -v nixfmt >/dev/null && echo nixfmt) $(command -v ruff >/dev/null && echo ruff) $(command -v gitleaks >/dev/null && echo gitleaks)"
            echo "  run:     council --help   (every verb; the shipped app has the user ones)"
          '';
        };
      });

      # `nix run .#council` — ONE app. With no arguments it prints its verbs, so
      # the bare command is informative and costs nothing; nothing expensive
      # happens by accident.
      apps = forAllSystems (
        pkgs:
        let
          council = mkDispatcher pkgs "user";
        in
        {
          council = {
            type = "app";
            program = lib.getExe council;
            meta.description = council.meta.description;
          };
          default = self.apps.${pkgs.stdenv.hostPlatform.system}.council;
        }
      );

      # `nix flake check` — the framework's own gates, under the pinned
      # toolchain. Every check here must be able to fail: one that ends in
      # `|| true` prints "all checks passed!" while verifying nothing.
      checks = forAllSystems (
        pkgs:
        let
          tc = mkToolchain pkgs;
          # The shipped tree, and the dev one. checks.commands asserts that the
          # difference between them is EXACTLY the audience split in the CLI's own
          # verb table, so this list cannot rot into a comment.
          fw = mkFramework pkgs "user";
          fwDev = mkFramework pkgs "dev";
          app = mkDispatcher pkgs "user";
          dev = mkDispatcher pkgs "dev";

          # Copied writable: the store is read-only and pytest writes caches.
          src = pkgs.runCommand "review-council-src" { } ''
            cp -r ${./.} $out
            chmod -R u+w $out
          '';

          # The linters run against this, not `src`: tests/golden is fixture data
          # and its line count is the golden suite's kloc, so formatting it would
          # move every pinned score.
          srcLint = pkgs.runCommand "review-council-src-lint" { } ''
            cp -r ${./.} $out
            chmod -R u+w $out
            rm -rf $out/tests/golden
          '';
        in
        {
          # The declarative path's two artifacts. Without these it is exercised only
          # by a user's switch, which is a late place to find a typo.
          skill-layout = pkgs.runCommand "check-skill-layout" { } ''
            s=${mkSkill pkgs}
            for f in SKILL.md flake.nix flake.lock \
                     scripts/council.py scripts/council_loop.py \
                     assets/rubrics/reviewer-security/SKILL.md \
                     assets/bots/council-orchestrator/profile.yaml \
                     tests/golden/expect.json; do
              test -f "$s/$f" || { echo "missing from .#skill: $f" >&2; exit 1; }
            done
            # The copier never ships. Shipping it is how the deployed suite came
            # to import a file that is not there and run zero tests.
            test ! -e "$s/scripts/sync_to_skill.py" \
              || { echo "the copier shipped in .#skill" >&2; exit 1; }
            touch $out
          '';

          # `nix flake check` knows a fixed set of output names and skips anything
          # else with a warning, so homeManagerModules would never be evaluated.
          # Evaluate it against a stub for the home-manager surface it touches, and
          # assert that BOTH modes produce the setting each one promises.
          module-evaluates =
            let
              stub =
                { lib, ... }:
                {
                  # The attribute set is a whole, not a repeated `options.` prefix:
                  # statix's W20 flags the repeated-key form, and it is right — the
                  # dotted form reads as five separate declarations of `options`.
                  options = {
                    home = {
                      # A placeholder from the repo's allowlist, not an invented
                      # name: the portability test flags any /home/<name> that is
                      # not a known placeholder, and "stub" was a real hit.
                      homeDirectory = lib.mkOption {
                        type = lib.types.str;
                        default = "/home/user";
                      };
                      packages = lib.mkOption {
                        type = lib.types.listOf lib.types.anything;
                        default = [ ];
                      };
                      file = lib.mkOption {
                        type = lib.types.attrsOf lib.types.anything;
                        default = { };
                      };
                    };
                    # home-manager declares `assertions`; the module's mode check
                    # needs it, and its absence is what this check caught first run.
                    assertions = lib.mkOption {
                      type = lib.types.listOf lib.types.anything;
                      default = [ ];
                    };
                    services.hermes-agent.settings.skills.external_dirs = lib.mkOption {
                      type = lib.types.listOf lib.types.str;
                      default = [ ];
                    };
                  };
                };
              evalMode =
                mode:
                lib.evalModules {
                  modules = [
                    stub
                    (import ./nix/module.nix)
                    {
                      programs = {
                        council = {
                          enable = true;
                          package = pkgs.hello;
                          skill = mkSkill pkgs;
                          inherit mode;
                        };
                      };
                    }
                  ];
                };
              dirs = (evalMode "external-dirs").config.services.hermes-agent.settings.skills.external_dirs;
              linked = (evalMode "library").config.home.file;
            in
            pkgs.runCommand "check-module-evaluates" { } ''
              test ${builtins.toString (builtins.length dirs)} -eq 1 \
                || { echo "external-dirs set ${builtins.toString (builtins.length dirs)} entries, wanted 1" >&2; exit 1; }
              test ${builtins.toString (builtins.length (builtins.attrNames linked))} -eq 1 \
                || { echo "library mode set no home.file entry" >&2; exit 1; }
              touch $out
            '';

          # §1: formatting is a binary gate, over every Nix file.
          nixfmt = pkgs.runCommand "check-nixfmt" { nativeBuildInputs = [ tc ]; } ''
            cd ${srcLint}
            find . -name '*.nix' -not -path './.review-council/*' -print0 \
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

          # The suite is a gate, not a CI nicety. `pkgs.git` is a real
          # dependency: baseline.py's changed_files shells out to `git diff` and
          # `git ls-files`, exercised against a throwaway repository.
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

          # The golden suite, run the way CI runs it, so a moved score fails with
          # the number rather than a pytest traceback. Through the DEV dispatcher:
          # the fixtures live in tests/, which only the dev tree carries, and the
          # module refuses a direct invocation anyway.
          golden = pkgs.runCommand "check-golden" { nativeBuildInputs = [ tc ]; } ''
            ${dev}/bin/council golden --check
            touch $out
          '';

          # The toolchain must WORK, not merely exist: `python3 -m pytest` needs
          # pytest's runtime deps importable, which a bare symlinkJoin lacks.
          toolchain-built = pkgs.runCommand "check-toolchain" { } ''
            for b in statix deadnix nixfmt python3 pytest; do
              test -x ${tc}/bin/$b
            done
            ${tc}/bin/python3 -c 'import pytest, pluggy'
            touch $out
          '';

          # THE ANALYZER MATRIX. `toolchain-built` above asserts five binaries exist;
          # this asserts the ANALYZERS actually execute and parse, which is what
          # `council probes` feeds into beta and the deterministic half of the score.
          # Without it, a tool that is present but broken — wrong version, missing
          # runtime dep, unparsable output — lowers beta silently and the score
          # quietly becomes the LLM's judgement. It runs on EVERY system in
          # `systems`, so darwin is covered by the same claim rather than by a
          # separate assertion.
          probes =
            pkgs.runCommand "check-probes"
              {
                nativeBuildInputs = [ tc ];
              }
              ''
                mkdir -p fixture
                printf 'def add(a, b):\n    return a + b\n' > fixture/main.py
                printf '{ }\n' > fixture/flake.nix

                ${app}/bin/council probes --all --repo "$PWD/fixture" > probes.json

                ${tc}/bin/python3 - <<'PY'
                import json
                import sys

                doc = json.load(open("probes.json"))
                rows = doc["results"] if isinstance(doc, dict) and "results" in doc else doc
                ran = {r["tool"] for r in rows if r.get("ran")}

                # Every probe that needs no fixture content must have RUN. `ran`, not
                # `parsed` and not success: `flake-check` runs and reports FAILED on a
                # fixture with no outputs, and `osv-scanner` runs and reports nothing to
                # scan. Both are correct answers, so requiring a clean signal would
                # assert something untrue about a synthetic fixture.
                required = {
                    "bandit", "bash-n", "complexity", "deadnix", "declared-rules",
                    "dep-graph", "flake-check", "mypy", "nix-eval", "nixfmt",
                    "osv-scanner", "py-compile", "ruff", "secret-grep", "statix",
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

          # One language. A .sh file in the tree means someone has added a second
          # way to do things, which is exactly what this layout exists to prevent:
          # every verb is a Python module reached through `council`.
          no-shell-scripts = pkgs.runCommand "check-no-shell" { nativeBuildInputs = [ pkgs.findutils ]; } ''
            found=$(find ${src} -name '*.sh' -not -path '*/.git/*' | head -5)
            if [ -n "$found" ]; then
              echo "shell scripts in the tree:" >&2
              echo "$found" >&2
              exit 1
            fi
            touch $out
          '';

          # The command surface, driven by the app's own verb table. Silent
          # breakage otherwise: a verb naming a module that was renamed, a data
          # file missing from the framework tree, and the audience split leaking
          # dev verbs into the shipped app.
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

                    # 1. every USER verb's module ships, and every DEV verb's does
                    #    NOT. This asserts flake.nix's shipping manifest against the
                    #    CLI's own verb table, so a new user verb whose module was
                    #    not listed fails here, and a dev module leaking into the
                    #    shipped tree fails here too.
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

                    # 5. every user verb starts. --help is safe on all of them: the ones
                    #    that parse arguments answer it, the ones that act get it here.
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

                    # 9. the modules are not programs. A direct invocation must be
                    #    REFUSED and the same verb through the CLI must WORK, so this
                    #    fails both when the guard is dropped and when it is too eager.
                    #    That is the property keeping someone from running `corpus`,
                    #    `setup skill` or `review` by hand.
                    if python3 ${fw}/scripts/probes.py --list > /dev/null 2>&1; then
                      echo "scripts/probes.py ran without going through council" >&2
                      exit 1
                    fi
                    ${app}/bin/council probes --list > /dev/null || { echo "council probes --list failed" >&2; exit 1; }
                touch $out
              '';
        }
        # The image is a Linux userspace — `dockerTools` cannot build one from darwin —
        # so the same guard as the `container` output applies. Building it IS the
        # proof: `.#container` is a pure nix derivation over the same attrs as the
        # runtime tree, so a successful build is the whole claim, and no docker daemon
        # is involved because the output is a tarball. That is why this can be a check
        # where the VM test cannot (KVM) and why the image no longer needs a separate
        # CI job to be verified.
        // lib.optionalAttrs pkgs.stdenv.hostPlatform.isLinux {
          container = pkgs.runCommand "check-container" { } ''
            test -s ${mkContainer pkgs}
            touch $out
          '';
        }
      );
    };
}
