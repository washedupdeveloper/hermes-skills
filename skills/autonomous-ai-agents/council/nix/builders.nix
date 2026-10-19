# The derivation builders, as pure functions of `pkgs`.
#
# Nothing here reads `self` or `systems`, so the flake's perSystem block and an
# importing flake module share one definition. Two tool lists, deliberately:
# `toolNames` ships and is what a review RUNS; `devToolNames` is devshell-only.
# Per-tool verdicts: docs/TOOLCHAIN.md. Path literals are relative to THIS file.
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
    # Shipped, never probed -- on demand only. Unmaintained, matches name+version
    # so backported fixes are invisible, and it fetches NVD data over the network.
    # Routine CVE answer instead: the tracker in skills/reviewer-security/SKILL.md.
    # tests/test_probes.py pins both halves.
    "vulnix" # store / CVE scanner — on demand, never probed

    # --- secret + supply chain ---
    # Entropy + a few hundred rules over the WORKING TREE. Pairs with
    # `secret-grep`, this framework's dependency-free probe, which still runs when
    # the toolchain is absent.
    "gitleaks" # secret scanning
    # Dependency CVEs for PyPI, npm, cargo, Go, Ruby, Composer -- one binary
    # replacing pip-audit/npm-audit/cargo-audit, with no runtime dep to get wrong.
    "osv-scanner"
    # GitHub Actions security: the only analyzer that reads `.github/`, and a
    # workflow runs with the repository token's authority. Catches `uses: @main`
    # and a missing `permissions:` block (default token is write-all pre-2023).
    # Measured on numtide/flake-utils: 5 findings.
    "zizmor"

    # --- Python (DECISIONS #3: Python first-class) ---
    "ruff" # lint + format
    "mypy" # static types
    "pytest" # test runner
    "bandit" # security lint

    # pip-audit is DELIBERATELY NOT here: its wrapper execs
    # `sys.executable -m pip --version` first and the interpreter ships no pip, so
    # it was on PATH and could not execute at all. osv-scanner does the same job.
    # --- general ---
    "shellcheck" # shell lint

    # DELIBERATELY EXCLUDED -- semgrep: not in research/nix-tooling.md §0, and it
    # does not build here (pythonRuntimeDepsCheck: "pyjwt~=2.13.0 not satisfied by
    # version 2.14.0"). A tool that cannot build fails the whole toolchain.
  ];

  # The shipping manifest. `runtimeModules` is what a REVIEW needs and is copied
  # into the shipped tree (app, devshell, image); `devModules` are development
  # verbs, repo and devshell only. The split matters because several dev modules
  # ACT -- `corpus` plants defects, `setup skill` prunes a deployment, `calibrate`
  # and `ablate` spend agent turns -- and a file not in the image cannot run there.
  # checks.commands asserts this list against the CLI's verb table.
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
    # ships: it is how a user WITHOUT nix or docker gets the rest of the tree
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

  # Top-level attrs first, then python3Packages: several tools exist only there.
  resolveTool = pkgs: name: pkgs.${name} or (pkgs.python3Packages.${name} or null);

  # ONE store path with a merged bin/ plus the pinned inventory JSON alongside it.
  # symlinkJoin, not buildEnv: buildEnv links only the pathsToLink subtrees, which
  # would hide the inventory. Missing attrs are skipped rather than failing eval,
  # and the inventory reports them instead of silently shipping less.
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

      # pytest needs its TRANSITIVE deps, which symlinkJoin cannot supply: joining
      # the outputs gives site-packages/pytest without pluggy/iniconfig, so
      # `python3 -m pytest` dies with "No module named 'pluggy'" even though the
      # `pytest` wrapper works. A withPackages env carries the closure.
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

  # The tree the modules run from; they resolve their root as
  # `dirname(__file__)/..`. The repo UNDER REVIEW never appears here -- it arrives
  # as `--repo` or a run directory, which is what lets this tree be read-only.
  #
  # `audience` picks the contents as it picks the verb surface. The shipped tree
  # drops README/pyproject/flake.nix: the toolchain arrives baked, so no runtime
  # path builds a flake. `setup skill` is not a review and DOES need one -- see
  # flakeFiles below.
  # Contributor DX: devshell only. No probe runs these, the gate does not score
  # them, and the container does not carry them -- which is what keeps the shipped
  # toolchain the QA set rather than everything anyone has used.
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

  # A symlinkJoin of whatever resolves, so a tool missing on one platform degrades
  # to its absence rather than failing the shell.
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

  # The deployable skill, laid out as `council setup skill` writes it, but as a
  # store path: read-only, so it cannot drift from source and the copier is not
  # needed. Update is `nix flake update` + switch. Design: docs/bootstrap.md.
  # Decision: docs/adr/0004.
  #
  # EVERY script ships, not the `user` audience set: the deployed suite exercises
  # the dev modules, so the runtime subset alone leaves four tests importing absent
  # files. checks.skill-layout catches a mismatch, which is why it exists.
  mkSkill =
    pkgs:
    pkgs.runCommand "council-skill" { } ''
      mkdir -p $out/scripts $out/tests $out/assets/bots $out/assets/rubrics
      cp ${../skills}/council/SKILL.md $out/SKILL.md
      for s in ${../scripts}/*.py; do
        [ "$(basename "$s")" = sync_to_skill.py ] && continue
        cp "$s" $out/scripts/
      done
      # The gate's data files: without them score_reviews falls back to the
      # uncalibrated count-based curve, so the deployment scores differently.
      cp ${../scripts}/calibration.json $out/scripts/calibration.json
      cp ${../scripts}/eval-baseline.json $out/scripts/eval-baseline.json
      cp ${../tests}/*.py $out/tests/
      cp -r ${../tests}/golden $out/tests/golden
      cp -r ${../bots}/. $out/assets/bots/
      for r in ${../skills}/reviewer-* ${../skills}/review-council-orchestrator; do
        cp -r "$r" "$out/assets/rubrics/$(basename "$r")"
      done
      # The flake MODULES, not just the flake: `imports` are eager, so a flake.nix
      # naming nix/*.nix without them shipped cannot evaluate ANY output.
      # checks.skill-layout derives this from the deployed flake.nix.
      cp -r ${../nix} $out/nix
      cp ${../flake.nix} $out/flake.nix
      cp ${../flake.lock} $out/flake.lock
      chmod -R u+w $out
      rm -rf $out/scripts/__pycache__ $out/tests/__pycache__
    '';

  # The files that make the toolchain buildable, for `setup skill` to install so a
  # machine with ONLY the skill can `nix build <skill>#toolchain` -- the fallback
  # toolchain.py takes when nothing bakes the path. Not in the framework tree,
  # which made a sync from a nix tree find no flake and SKIP IT SILENTLY, leaving a
  # deployment whose flake.nix went stale with nothing to say so.
  #
  # Three copiers ship these files (here, mkSkill, sync_to_skill.py); all three
  # need the modules or the flake they install is inert.
  flakeFiles =
    pkgs:
    pkgs.runCommand "review-council-flake-files" { } ''
      mkdir -p $out
      cp ${../flake.nix} $out/flake.nix
      cp ${../flake.lock} $out/flake.lock
      cp -r ${../nix} $out/nix
    '';

  # The verb table lives in scripts/council.py and checks.commands asks the BUILT
  # APP for it (`council --verbs-json`), so a verb cannot exist in the CLI without
  # its module shipping. A table that exists once cannot drift.
  #
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

  # ONE generated launcher: put the pinned toolchain on PATH, hand off to
  # scripts/council.py, which owns the verb table, usage and dispatch. The
  # toolchain is BAKED, not discovered -- this launcher was built against one store
  # path, and the shipped tree has no flake for toolchain.py to build.
  # REVIEW_COUNCIL_DISPATCHED is what makes this the only way in.
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

  # The container image is defined once: `nix build .#container` (dockerTools) and
  # the Dockerfile both build the SAME runtime tree. A second copy is how "the image
  # works but the Dockerfile does not" happens.
  #
  # Runtime rootfs preparation. Both consumers run it with the image root as cwd, so
  # every path is relative. Unprivileged, so anything written into a mounted repo
  # belongs to the caller; a passwd entry is still required because nix resolves
  # $HOME through getpwuid() and fails without one.
  #
  # The home and working directory are world-writable because a CALLER IS NOT
  # NECESSARILY uid 1000 (`--user "$(id -u):$(id -g)"`); otherwise the run directory
  # lands in the repo while the profile home stays read-only, and the failure is a
  # traceback rather than a message.
  imagePrep = ''
    mkdir -p etc home/council/.hermes repo tmp
    # dockerTools ships `etc` as a read-only store symlink; a plain rootfs has none.
    chmod u+w etc 2>/dev/null || true
    # The files may ALREADY exist and be read-only, and `>` truncates in place, so
    # without this the write fails and the content silently stays whatever it was.
    chmod u+w etc/passwd etc/group 2>/dev/null || true
    echo 'root:x:0:0:root:/root:/bin/sh' > etc/passwd
    echo 'council:x:1000:1000:council:/home/council:/bin/sh' >> etc/passwd
    echo 'root:x:0:' > etc/group
    echo 'council:x:1000:' >> etc/group
    chmod 0777 home/council repo
    chmod -R 0777 home/council/.hermes
    # /tmp must be writable by ANY uid, because the probes put scratch there:
    # without it `tempfile.mkdtemp()` falls back to the working directory (/repo,
    # the repository under review) and a review left tmpXXXX dirs in someone's tree.
    chmod 1777 tmp
    # The entrypoint appends a passwd entry for the runtime uid; nix fails with
    # "cannot determine user's home directory" without one, degrading every nix probe.
    chmod 0666 etc/passwd etc/group
    # Insurance rather than a fix: with no nix database there is no lock file, but
    # nix still wants its per-user profile dir. mkdir BEFORE the chmod, or the
    # directory is created afterwards and left mode 755.
    mkdir -p nix/var/nix/profiles/per-user/council
    chmod -R a+w nix/var/nix 2>/dev/null || true
  '';

  # The image's ENTRYPOINT. Generated because it needs the pinned tools on PATH;
  # the logic is scripts/entrypoint.py, which refuses to run unless this variable
  # is set.
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

  # The pinned nix CLI needs a config file and a minimal image has none, so the
  # experimental features are OFF and `nix eval` / `nix flake check` fail with
  # "experimental feature 'nix-command' is disabled" -- the probe then reports
  # ran=False with nothing to explain it. `build-users-group` is cleared because
  # there is no `nixbld` group. NIX_CONF_DIR points here because /etc arrives as a
  # read-only store symlink from the toolchain.
  mkContainerNixConf =
    pkgs:
    pkgs.writeText "review-council-nix.conf" ''
      experimental-features = nix-command flakes
      build-users-group =
    '';

  # Built from the same flake.lock as the native deployment and published by CI.
  # Layered with no nix database, so an unchanged toolchain keeps identical layer
  # digests. Numbers, and what is verified: docs/CONTAINER.md.
  mkContainer =
    pkgs:
    let
      tc = mkToolchain pkgs;
      # The shipped tree: runtime modules only, so the dev verbs cannot be run here.
      fw = mkFramework pkgs "user";
      deps = shellDeps pkgs;

      entrypoint = mkContainerEntrypoint pkgs;

      # dockerTools merges a store path's TOP-LEVEL entries into the image root, so
      # dropping the framework in as-is scatters scripts/, skills/ and bots/ across
      # /. A symlink, not a copy: the modules resolve <here>/.. and land on
      # /opt/review-council, and entrypoint.py derives that from its own location.
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
      # `lib.unique`: bashInteractive and shellDeps' bash are the same store path,
      # and a duplicate breaks the image build.
      contents = lib.unique (
        [
          tc
          frameworkAt
          nixConfAt
          entrypoint
          pkgs.bashInteractive
          # `baseline.py`'s changed_files shells out to git, and the framework's own
          # test check needs it too.
          pkgs.git
        ]
        ++ deps
      );
      # The writable dirs, passwd/group entries and mode fixes, shared with the
      # Dockerfile's rootfs -- see imagePrep.
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

  # Tools for the Dockerfile's materialisation step, from nixpkgs rather than the
  # base image: `nixos/nix` has grep/cut/tar/readlink but NOT sed or awk, and that
  # step piped through sed -- `docker build` died at the last instruction with
  # `/bin/sh: line 1: sed: command not found`. Builder only; never in the runtime.
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

  # The same runtime tree as a plain directory, for the Dockerfile. Its CLOSURE is
  # the image's content: the toolchain, bash, git and the entrypoint are NAMED IN A
  # FILE so nix records them as references -- a symlink alone is not a reference,
  # and a missing analyzer would show up only as a probe reporting ran=False.
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
      # A symlink, so the Dockerfile can name a stable path in ENV rather than a
      # store hash it cannot know at build time.
      ln -s ${tc} opt/toolchain

      # Merge the runtime's `bin` into /bin, as dockerTools does with `contents`.
      # Without it the analyzers are reachable only through the entrypoint's PATH,
      # so `docker run --entrypoint sh` finds none of them.
      for d in ${lib.concatMapStringsSep " " (p: "${p}") runtime}; do
        [ -d "$d/bin" ] || continue
        for f in "$d"/bin/*; do
          [ -e "$f" ] || continue
          ln -sf "$f" "bin/$(basename "$f")"
        done
      done

      ${imagePrep}

      # The prep as a FILE because nix makes everything under a store path
      # read-only, so the modes set above do NOT survive the Dockerfile's copy --
      # `tmp` arrives 0555, not 1777. mkContainer needs no such step: dockerTools
      # runs extraCommands on the image root, where modes are preserved.
      mkdir -p .nix
      cp ${pkgs.writeText "review-council-image-prep.sh" imagePrep} .nix/prep.sh

      # The runtime closure, named so nix records it as a reference: git and the
      # shell deps are reached only through the entrypoint, so name them all.
      printf '%s\n' ${lib.concatMapStringsSep " " (p: "${p}") runtime} > .nix/closure
    '';

  # Proves the council runs end-to-end in a clean NixOS VM with a Hermes available:
  # the real pinned probes, the real gate, a real verdict.
  #
  # The agent is a STUB, deliberately. What is under test is the harness -- the
  # fan-out, the bucketing, the beta measurement, the gate. A real model would make
  # the test slow, non-deterministic and billable, and would test the model rather
  # than this repository. The stub honours the same CLI contract a real Hermes does.
  #
  # NOT in `checks`, deliberately: a VM test needs KVM. `nix build .#vm-test` runs
  # it; docs/CONTAINER.md says when to.
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
      # The dimension set is the ROUND's, not this stub's: hardcoding it meant a
      # dimension could never be ADDED under test. `COUNCIL_STUB_DIMS` lets the
      # add-a-dimension test say what the round has.
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

      # `--version` and `--help` first: they carry no prompt, and without this the
      # stub answers them with the aggregate branch.
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
      # One dimension can be scored low on demand (`accessibility:40`): presence
      # alone shows a dimension APPEARS; scoring it low shows it MOVES the aggregate.
      low = os.environ.get("COUNCIL_STUB_LOW", "")
      if ":" in low:
          name, value = low.split(":", 1)
          if name in scores:
              scores[name] = float(value)
      if os.environ.get("VM_STUB_DEFECT") == "high":
          # One open high finding, every score still 100: that isolates the BLOCKING
          # rule. A stub that also lowered the score would let a broken blocking
          # check pass this test.
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
        # `_`, not `{ ... }`: the module needs none of its arguments, and statix's
        # empty-pattern rule rejects the idiomatic spelling.
        _: {
          # The council plus the pinned toolchain, so the probes are real.
          environment.systemPackages = [
            (mkDispatcher pkgs "user")
            (mkStubHermes pkgs)
            # The testScript reads JSON back with `python3 -c`; the dispatcher puts
            # python on ITS OWN path, not the machine's.
            pkgs.python3
          ];
          # Room for the toolchain closure and a run directory.
          virtualisation.diskSize = 4096;
          virtualisation.memorySize = 4096;
        };

      testScript = ''
        machine.start()
        machine.wait_for_unit("multi-user.target")

        # 0. a target repository to review. First, because `doctor --repo` refuses a
        #    path that is not a directory and the detection checks all name it.
        machine.succeed("mkdir -p /tmp/target")
        machine.succeed("printf 'def add(a, b):\\n    return a + b\\n' > /tmp/target/main.py")

        # 1. the launcher resolves and EXECUTES. `which` alone would pass on a file
        #    that cannot run, so the version is the check.
        version = machine.succeed("hermes --version").strip()
        machine.log(f"stub hermes version: {version}")

        # 2. detection, before any profiles exist. The honest negative: Hermes is
        #    installed and the council still cannot review. A doctor saying "ready"
        #    here would be the bug this feature exists to prevent.
        doctor = machine.succeed("council doctor --repo /tmp/target 2>&1 || true")
        machine.log(doctor)
        assert "no-launcher" not in doctor, doctor
        assert "NO COUNCIL PROFILES" in doctor, (
            "doctor did not report the missing profiles:\n" + doctor)
        assert "no-profiles" in machine.succeed(
            "council doctor --repo /tmp/target --json 2>/dev/null | "
            "python3 -c 'import json,sys; print(json.load(sys.stdin)[\"hermes\"][\"verdict\"])'"
        ), "the JSON verdict disagrees with the rendered one"

        # 3. give the profiles a provider, as `council setup bots` + `hermes setup`
        #    would, and the verdict must move to ready.
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

        # beta is measured from the run; with the pinned toolchain present the
        # deterministic half is fully covered.
        probes = machine.succeed(
            f"python3 -c 'import json; d=json.load(open(\"{run_dir}/probes.json\")); "
            f"print(len([p for p in d if p[\"ran\"]]))'"
        ).strip()
        machine.log(f"probes that ran: {probes}")
        assert int(probes) > 0, "no probe ran in the VM"

        # 6. the gate must FAIL on the BLOCKING rule alone: every score is 100, so
        #    the aggregate passes and one open high finding must still refuse it.
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

        # and the deliverable must name the blocker, or the reader is told "not
        # satisfied" with nothing to act on.
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
        #    the edits go on a writable copy and the dispatcher is re-pointed at it,
        #    which keeps every toolchain export verbatim.
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

        # step 4: reinstall, so the reviewer profile carries the new rubric.
        # CORE_SKILLS is an explicit list, so the editor above had to add it there.
        installed = machine.succeed("/usr/local/bin/council-mod setup bots 2>&1")
        machine.log(installed)
        # The count AND the file: a profile that says six but is missing the rubric
        # would still answer with no criteria for that dimension.
        assert "6 skill(s)" in installed, installed
        machine.succeed(
            "test -f /root/.hermes/profiles/council-generalist/skills/"
            "reviewer-accessibility/SKILL.md")

        # 9. the round must carry the dimension, and it must MOVE THE NUMBER. A
        #    dimension merely present leaves [100.0] unchanged, so the stub scores
        #    this one 40 and the aggregate must land on the rebalanced weighted mean:
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
