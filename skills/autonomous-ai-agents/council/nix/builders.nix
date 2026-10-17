# The derivation builders, as pure functions of `pkgs`.
#
# Split out of flake.nix so the flake reads as configuration rather than as 1,300
# lines of construction. Nothing here reads `self` or `systems`: every builder is
# `pkgs -> derivation`, which is what lets the flake's own perSystem block and an
# importing flake module share one definition instead of copying it.
#
# `toolNames` and the module lists live here because only the toolchain builders
# read them — an inventory nothing else consults is part of the toolchain, not part
# of the flake's output surface.
#
# TWO tool lists, and the split is the point:
#   `toolNames`    the centralised QA toolchain. It ships — devshell, container,
#                  `nix shell .#review-council` — and carries exactly what a review
#                  RUNS. See docs/TOOLCHAIN.md for the per-tool verdict.
#   `devToolNames` contributor DX, devshell only. Nothing in the pipeline reads these,
#                  so they are not part of the product and each contributor can
#                  install their own instead.
#
# Path literals are relative to THIS file, so they are `../<dir>`: the repo root is
# one level up.
{
  lib,
  nixpkgs ? { },
}:
let
  toolNames = [
    # --- Nix / NixOS / Clan — the framework's primary scope ---
    "nix" # the CLI itself: `nix flake check`, `nix eval`
    "nixfmt" # RFC 166 formatter. nixpkgs-fmt is DEPRECATED (RFC 101).
    "nixfmt-tree" # treefmt preconfigured for nixfmt; the repo `formatter`
    "statix" # nix lints; `statix check . -o json`
    "deadnix" # dead nix code; `deadnix --output-format json --fail .`
    # SHIPPED BUT NOT PROBED — on demand only. `vulnix` is here so closure CVEs can be
    # asked when that is the question, and it is absent from scripts/probes.py so a
    # routine review never pays for it: it fetches NVD data over the network (minutes,
    # and the answer moves with the date), it is unmaintained, and it matches
    # name+version so backported fixes are invisible. Advisory CVEs for the pinned
    # nixpkgs have a cheap routine answer instead — the tracker in
    # skills/reviewer-security/SKILL.md. tests/test_probes.py pins both halves.
    "vulnix" # store / CVE scanner — on demand, never probed

    # --- secret + supply chain ---
    # Entropy detection plus a few hundred rules, over the WORKING TREE. Pairs with
    # `secret-grep`, this framework's own dependency-free regex probe: gitleaks is
    # stronger, secret-grep still runs when the toolchain is absent.
    "gitleaks" # secret scanning
    # Dependency CVEs for every ecosystem the framework covers: PyPI, npm,
    # cargo, Go, Ruby, Composer. It replaces pip-audit, npm-audit and
    # cargo-audit with ONE binary, and unlike them it has no runtime
    # dependency of its own -- see the note where pip-audit used to be.
    "osv-scanner"
    # GitHub Actions workflow security. The only analyzer that reads `.github/`, and
    # a workflow is executed by a forge with the repository token's authority, so it
    # is attack surface nothing else here looks at. Catches the class an LLM reviewer
    # has to notice by hand: `uses: owner/repo@main` (a moving branch executing on
    # every push) and a missing `permissions:` block (the default token is write-all
    # on repositories created before February 2023). Measured on
    # numtide/flake-utils: 5 findings, including the `@main` action.
    "zizmor"

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
    # The `shell` stack's scored tool. It had no probe until the audit, so a shell
    # repository had an expected tool that could never run.
    "shellcheck" # shell lint

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
    "metrics.py" # metrics — acceptance/address/iterations from judged findings
    "toolchain.py" # setup toolchain
    "install_bots.py" # setup bots
    "install_dispatcher.py" # setup dispatcher
    "init.py" # setup init — the guided first-run path
    # setup skill — ships because it is how a user WITHOUT nix or docker gets
    # the rest of the tree. It was dev-only until the user-facing verb existed,
    # and a module reachable from the shipped surface has to be in it.
    "sync_to_skill.py"
    "goal.py" # goal — the /goal contract and quality-gate emitter
    "cron.py" # cron — print or install a scheduled unattended review
    "pr.py" # pr — post a run's verdict to a GitHub pull request
    "council_config.py" # shared: the one place configuration lives
    "entrypoint.py" # the container ENTRYPOINT
    "hermes_home.py" # shared: where HERMES_HOME is
    "_shared.py" # shared: the helpers more than one module needs
    "hermes.py" # shared: locate the launcher, report what can be known
    "calibration.json" # the threshold + curves
    "eval-baseline.json" # the nix-eval-time baseline
  ];

  devModules = [
    "ablate.py" # dev/ablate
    "calibrate.py" # dev/calibrate
    "golden.py" # dev/golden
    "inject_defects.py" # dev/corpus
    "version.py" # dev/version — the release policy, docs/VERSIONING.md
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
  # ── Contributor DX: on PATH in the devshell, and nowhere else ────────────
  # No probe runs these, the gate does not score them, and the container does not
  # carry them. They are what a human working ON the framework wants: an editor that
  # understands the option system, a way to look inside a closure, and the density
  # meters for reading a report by hand. Keeping them out of `toolNames` is what makes
  # the shipped toolchain the QA set rather than everything anyone has ever used, and
  # it lets a contributor install their own editor tooling without colliding with it.
  devToolNames = [
    "nixd" # LSP, option-system aware
    "nil" # LSP + `nil diagnostics`
    "nix-tree" # closure browser (--dot, --diff)
    "nix-diff" # derivation-level diff
    "nix-fast-build" # parallel eval+build of `checks`
    "nix-du" # GC-root disk attribution
    "tokei" # density meter: `tokei -t Nix --output json`
    "cloc" # density meter: `cloc --json --include-lang Nix`
    "jq" # JSON glue, for reading a report by hand
  ];

  # The devshell's extra tooling. A `symlinkJoin` of whatever resolves, so a tool
  # missing on one platform degrades to its absence rather than failing the shell.
  mkDevTools =
    pkgs:
    pkgs.symlinkJoin {
      name = "review-council-dev-tools";
      paths = builtins.filter (p: p != null) (map (resolveTool pkgs) devToolNames);
    };

  mkFramework =
    pkgs: audience:
    let
      dev = audience == "dev";
      modules = runtimeModules ++ (if dev then devModules else [ ]);
    in
    pkgs.runCommand "review-council-framework" { } ''
      mkdir -p $out/scripts
      ${lib.concatMapStringsSep "\n" (n: "cp ${../scripts}/${n} $out/scripts/${n}") modules}
      cp -r ${../skills} $out/skills
      cp -r ${../bots} $out/bots
      ${lib.optionalString dev "cp -r ${../tests} $out/tests"}
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
      cp ${../skills}/council/SKILL.md $out/SKILL.md
      for s in ${../scripts}/*.py; do
        [ "$(basename "$s")" = sync_to_skill.py ] && continue
        cp "$s" $out/scripts/
      done
      # The gate's data files. The copier names these two explicitly too:
      # without them score_reviews falls back to the uncalibrated count-based
      # curve, so the deployment would score differently from the checkout.
      cp ${../scripts}/calibration.json $out/scripts/calibration.json
      cp ${../scripts}/eval-baseline.json $out/scripts/eval-baseline.json
      cp ${../tests}/*.py $out/tests/
      cp -r ${../tests}/golden $out/tests/golden
      cp -r ${../bots}/. $out/assets/bots/
      for r in ${../skills}/reviewer-* ${../skills}/review-council-orchestrator; do
        cp -r "$r" "$out/assets/rubrics/$(basename "$r")"
      done
      # The flake MODULES, not just the flake. `imports` are eager, so a flake.nix
      # that names nix/*.nix without them shipped cannot evaluate ANY output -- the
      # deployed skill's `.#toolchain` included. checks.skill-layout derives this
      # requirement from the deployed flake.nix so it cannot be forgotten again.
      cp -r ${../nix} $out/nix
      cp ${../flake.nix} $out/flake.nix
      cp ${../flake.lock} $out/flake.lock
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
      cp ${../flake.nix} $out/flake.nix
      cp ${../flake.lock} $out/flake.lock
      # The modules flake.nix imports. `imports` are eager, so a flake.nix without
      # them evaluates to nothing -- and this tree is what REVIEW_COUNCIL_FLAKE_DIR
      # points the launcher and `setup skill` at. Three copiers ship these files
      # (here, mkSkill, sync_to_skill.py); all three need the modules or the flake
      # they install is inert.
      cp -r ${../nix} $out/nix
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
      # The dimension set is the ROUND's, not this stub's. Hardcoding it meant a
      # dimension could never be ADDED under test: the stub would answer a
      # six-dimension round with five scores, and the missing dimension would look
      # like a gate failure rather than a test double that did not know about it.
      # `COUNCIL_STUB_DIMS` lets the add-a-dimension test say what the round has.
      DIMS = [d.strip() for d in os.environ.get("COUNCIL_STUB_DIMS", "").split(",")
              if d.strip()] or [
          "security", "correctness", "readability", "architecture", "performance",
      ]


      def arg(flag):
          argv = sys.argv[1:]
          for i, value in enumerate(argv):
              if value == flag and i + 1 < len(argv):
                  return argv[i + 1]
          return ""


      def prompt_text():
          """The prompt, from `--query-file` or `-q` / `--query`.

          `council_loop` sends `--query-file` because a reviewer prompt exceeds
          ARG_MAX, so a stub reading only `-q` sees NOTHING, prints usage and exits --
          and the whole VM test then exercises an empty round while still passing its
          own assertions. That is why this reads both forms.
          """
          path = arg("--query-file")
          if path:
              try:
                  return Path(path).read_text(encoding="utf-8", errors="replace")
              except OSError:
                  return ""
          return arg("-q") or arg("--query")


      prompt = prompt_text()

      # `--version` and `--help` come first: they carry no prompt, and without
      # this the stub would answer them with the aggregate branch and report a
      # nonsense version in the test log.
      if "--version" in sys.argv[1:] or "-V" in sys.argv[1:]:
          print("hermes (vm-test stub) 1.0.0")
          sys.exit(0)
      if not prompt:
          print("usage: hermes -p <profile> chat (-q <prompt> | --query-file <path>)")
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
      # One dimension can be scored low on demand (`accessibility:40`). Without it
      # a test can only show that a new dimension APPEARS in the round; scoring it
      # low is what shows it MOVES the aggregate, i.e. that it is really part of
      # the score rather than a file nobody reads.
      low = os.environ.get("COUNCIL_STUB_LOW", "")
      if ":" in low:
          name, value = low.split(":", 1)
          if name in scores:
              scores[name] = float(value)
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

        # 8. THE OTHER ACCEPTANCE CLAUSE, EXECUTED: "a new reviewer can be added
        #    following the docs alone". The framework is a read-only store path, so
        #    the documented edits go on a writable copy, and the dispatcher is
        #    copied and re-pointed at it -- that keeps every toolchain export
        #    verbatim instead of restating them here.
        machine.succeed(
            "cp -r ${mkFramework pkgs "user"} /tmp/fw && chmod -R u+w /tmp/fw")
        added = machine.succeed("python3 ${./vm-add-dimension.py} /tmp/fw")
        machine.log(added)
        assert "6 dimensions" in added, added

        machine.succeed("mkdir -p /usr/local/bin")
        machine.succeed(
            "sed 's|exec python3 .*/scripts/council.py|"
            "exec python3 /tmp/fw/scripts/council.py|' "
            "\"$(readlink -f \"$(command -v council)\")\" > /usr/local/bin/council-mod"
        )
        machine.succeed("chmod +x /usr/local/bin/council-mod")
        assert machine.succeed(
            "grep -c /tmp/fw/scripts/council.py /usr/local/bin/council-mod"
        ).strip() == "1", "the wrapper does not point at the modified tree"

        # step 4: reinstall, so the reviewer profile carries the new rubric. The doc
        # used to say the installer globbed reviewer-*/SKILL.md and needed no edit;
        # it does not -- CORE_SKILLS is an explicit list -- so the editor above adds
        # the rubric there and this asserts the profile actually received it.
        installed = machine.succeed("/usr/local/bin/council-mod setup bots 2>&1")
        machine.log(installed)
        # The count, and the file itself: a profile that says six but is missing the
        # rubric would still answer with no criteria for that dimension.
        assert "6 skill(s)" in installed, installed
        machine.succeed(
            "test -f /root/.hermes/profiles/council-generalist/skills/"
            "reviewer-accessibility/SKILL.md")

        # 9. the round must carry the dimension, and the dimension must MOVE THE
        #    NUMBER. Step 4's five-dimension run scored exactly [100.0]; a dimension
        #    that is merely present leaves that unchanged, so the stub scores this
        #    one 40 and the aggregate has to land on the rebalanced weighted mean:
        #    0.93*100 + 0.07*40 = 95.8.
        machine.succeed("rm -rf /tmp/target2 && mkdir -p /tmp/target2")
        machine.succeed("printf 'def add(a, b):\\n    return a + b\\n' > /tmp/target2/main.py")
        out2 = machine.succeed(
            "COUNCIL_STUB_DIMS=security,correctness,readability,architecture,"
            "performance,accessibility "
            "COUNCIL_STUB_LOW=accessibility:40 "
            "/usr/local/bin/council-mod review /tmp/target2 --mode advisory --max-rounds 1 "
            "--samples 1 --threshold 90 2>&1"
        )
        machine.log(out2)
        run2 = machine.succeed("ls -d /tmp/target2/.review-council/*/ | tail -1").strip()
        machine.log(f"six-dimension run dir: {run2}")
        for dim in ("security", "correctness", "readability", "architecture",
                    "performance", "accessibility"):
            machine.succeed(f"test -f {run2}/round-1/{dim}.json")

        six = machine.succeed(
            f"python3 -c 'import json; d=json.load(open(\"{run2}/outcome.json\")); "
            f"print(d[\"outcome\"], d[\"scores\"][-1])'"
        ).strip()
        machine.log(f"six-dimension run: {six}")
        verdict, aggregate = six.split()[0], float(six.split()[1])
        assert verdict == "satisfied", six
        assert aggregate < 99.9, (
            f"the added dimension did not move the aggregate: {six}")
        assert abs(aggregate - 95.8) < 1.0, (
            f"the aggregate is not the rebalanced weighted mean: {six}")
      '';
    };
in
{
  inherit
    toolNames
    devToolNames
    runtimeModules
    devModules
    resolveTool
    mkToolchain
    mkDevTools
    mkActivate
    mkFramework
    mkSkill
    flakeFiles
    shellDeps
    mkDispatcher
    imagePrep
    mkContainerEntrypoint
    mkContainerNixConf
    mkContainer
    mkImagePrepTools
    mkImageRoot
    mkStubHermes
    mkVmTest
    ;
}
