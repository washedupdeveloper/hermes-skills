# The eval tier: assertions about what the configuration SAYS.
#
# Three tiers, and the tier is chosen by what the assertion needs:
#
#   eval  -- a value in the evaluated configuration. No build, milliseconds, and
#            `lib.runTests` names the failing test with both values.
#   build -- the artifact a builder produced. `nix/checks.nix`.
#   e2e   -- what a running machine does with it. `.#vm-test`, kept OUT of
#            `checks` because it needs /dev/kvm, which a contributor may not have.
#
# The rule this encodes: an assertion belongs in the cheapest tier that can make
# it. `module-evaluates` used to be a `runCommand` asserting two hardcoded counts
# -- an eval assertion paying for a build, and reporting a bare exit code when it
# failed. It is now the `module` group below, which asserts each property by name
# and prints the expected and actual value on failure.
#
# Groups are separate checks so `nix flake check --keep-going` reports every
# failing group rather than stopping at the first.
{
  lib,
  pkgs,
  flake,
  systems,
}:
let
  # A stand-in for the home-manager surface `nix/module.nix` touches. The real
  # module is imported against it, so what is under test is the module that
  # ships, not a copy.
  #
  # `withHermes` decides whether the Hermes module is present, which is the one
  # condition the module branches on: `hermes-agent` is a separate input, so this
  # repo must evaluate both with and without it.
  #
  # The `services` namespace exists in BOTH branches, because home-manager always
  # has one — any other service module declares it. Only `hermes-agent` inside it
  # is optional. Declaring nothing at all would be a different claim (a config
  # with no home-manager at all), and the module would rightly fail it: a
  # definition under `mkIf false` still needs its option path to exist.
  mkStub =
    withHermes:
    { lib, ... }:
    {
      options = {
        home = {
          # A placeholder from the repo's own allowlist, not an invented name:
          # the portability test flags any /home/<name> that is not a known
          # placeholder.
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
        # home-manager declares `assertions`; the module's mode check reads it.
        assertions = lib.mkOption {
          type = lib.types.listOf lib.types.anything;
          default = [ ];
        };
      }
      // (
        if withHermes then
          {
            services.hermes-agent.settings.skills.external_dirs = lib.mkOption {
              type = lib.types.listOf lib.types.str;
              default = [ ];
            };
          }
        else
          {
            services = lib.mkOption {
              type = lib.types.attrsOf lib.types.anything;
              default = { };
            };
          }
      );
    };

  # `pkgs.hello` stands in for both the CLI and the skill tree: the assertions
  # below are about the WIRING (which option gets which path), and the real
  # artifacts are built and inspected by `checks.skill-layout`.
  eval =
    {
      withHermes ? true,
      council ? { },
    }:
    lib.evalModules {
      modules = [
        (mkStub withHermes)
        ./module.nix
        {
          programs.council = {
            enable = true;
            package = pkgs.hello;
            skill = pkgs.hello;
          }
          // council;
        }
      ];
    };

  cfgOf =
    args:
    let
      result = eval args;
    in
    {
      inherit (result.config) assertions home;
      council = result.config.programs.council;
      dirs = result.config.services.hermes-agent.settings.skills.external_dirs or [ ];
    };

  # The library-mode link path, derived the way the module derives it. Bound to a
  # name rather than interpolated inline: `${cfgOf { }.council.hermesHome}` closes
  # the interpolation at the `}` of the empty argument.
  defaultCfg = cfgOf { };

  libraryLink = "${defaultCfg.council.hermesHome}/skills/autonomous-ai-agents/council";

  failedAssertions = cfg: builtins.filter (a: !a.assertion) cfg.assertions;

  # Every system in `systems` is a promise that the per-system outputs exist for
  # it. Comparing attribute NAMES does not force the derivations, so this stays
  # milliseconds even for the darwin system on a Linux host.
  #
  # Sorted because `attrNames` is sorted and flake-parts keeps `systems` in
  # declaration order; comparing the two unsorted would be a false failure.
  sortedSystems = lib.sort builtins.lessThan systems;

  systemsWith = set: builtins.attrNames set;
in
{
  module = {
    # --- external-dirs: the default, and the one that protects the source -----
    test_external_dirs_mode_hands_the_skill_to_hermes = {
      expr = (cfgOf { }).dirs;
      expected = [ "${pkgs.hello}" ];
    };

    test_external_dirs_mode_links_nothing = {
      expr = builtins.attrNames (cfgOf { }).home.file;
      expected = [ ];
    };

    test_the_cli_is_installed_in_both_modes = {
      expr = [
        (cfgOf { }).home.packages
        (cfgOf { council.mode = "library"; }).home.packages
      ];
      expected = [
        [ pkgs.hello ]
        [ pkgs.hello ]
      ];
    };

    # --- library: the link, and what a link does NOT protect ----------------
    # The key is asserted separately from the value: a drifted link PATH is the
    # failure mode, and a bare `.source` lookup on a missing key dies with
    # `attribute '...' missing` -- an eval error rather than a named test.
    test_library_mode_links_into_the_documented_path = {
      expr = builtins.attrNames (cfgOf { council.mode = "library"; }).home.file;
      expected = [ libraryLink ];
    };

    test_the_link_points_at_the_skill = {
      # `or null` so a missing key reports as a failed test with both values
      # instead of aborting the group with an eval error -- the reason the path
      # is asserted separately above.
      expr = (cfgOf { council.mode = "library"; }).home.file.${libraryLink}.source or null;
      expected = pkgs.hello;
    };

    test_library_mode_sets_no_search_path = {
      expr = (cfgOf { council.mode = "library"; }).dirs;
      expected = [ ];
    };

    # --- defaults ----------------------------------------------------------
    test_the_default_mode_is_external_dirs = {
      expr = (cfgOf { }).council.mode;
      expected = "external-dirs";
    };

    test_hermes_home_defaults_under_the_home_directory = {
      expr = (cfgOf { }).council.hermesHome;
      expected = "/home/user/.hermes";
    };

    # --- the mode/input mismatch is refused, not silently inert -------------
    test_no_assertion_fails_in_a_supported_configuration = {
      expr = failedAssertions (cfgOf { });
      expected = [ ];
    };

    test_external_dirs_without_the_hermes_module_is_refused = {
      expr = map (a: a.assertion) (
        failedAssertions (cfgOf {
          withHermes = false;
        })
      );
      expected = [ false ];
    };

    # The message is the whole point of the assertion: it has to name the way
    # out, or a user meets a failure with no remedy.
    test_the_refusal_names_the_remedy = {
      expr = lib.any (a: lib.hasInfix "library" a.message) (
        failedAssertions (cfgOf {
          withHermes = false;
        })
      );
      expected = true;
    };

    test_library_mode_needs_no_hermes_module = {
      expr = [
        (failedAssertions (cfgOf {
          withHermes = false;
          council.mode = "library";
        }))
        (builtins.attrNames
          (cfgOf {
            withHermes = false;
            council.mode = "library";
          }).home.file
        )
      ];
      expected = [
        [ ]
        [ libraryLink ]
      ];
    };

    # --- disabled means nothing at all --------------------------------------
    test_a_disabled_module_changes_nothing = {
      expr =
        let
          cfg = cfgOf { council.enable = false; };
        in
        {
          inherit (cfg) assertions dirs;
          inherit (cfg.home) packages;
          files = builtins.attrNames cfg.home.file;
        };
      expected = {
        assertions = [ ];
        dirs = [ ];
        packages = [ ];
        files = [ ];
      };
    };
  };

  flake = {
    # `systems` is a build contract, not a wish list: a system listed here is a
    # promise that every per-system output exists for it.
    test_every_declared_system_has_packages = {
      expr = systemsWith flake.packages;
      expected = sortedSystems;
    };

    test_every_declared_system_has_checks = {
      expr = systemsWith flake.checks;
      expected = sortedSystems;
    };

    test_every_declared_system_has_the_app = {
      expr = systemsWith flake.apps;
      expected = sortedSystems;
    };

    test_every_declared_system_has_the_formatter = {
      expr = systemsWith flake.formatter;
      expected = sortedSystems;
    };

    test_every_declared_system_ships_the_review_council_package = {
      expr = lib.filter (s: !(flake.packages.${s} ? review-council)) systems;
      expected = [ ];
    };

    # The two integration points another flake or a user's switch consumes.
    # Without these the declarative path exists only in prose.
    test_the_consumer_facing_outputs_exist = {
      expr = [
        (flake.homeManagerModules ? default)
        (flake.flakeModules ? default)
      ];
      expected = [
        true
        true
      ];
    };

    # `nix flake check` knows a fixed set of output names and skips anything else
    # with only a warning. The two it cannot know are this flake's integration
    # points, and the `module` group above is what evaluates them -- so the
    # remainder is enumerated and a new custom output has to be added here on
    # purpose.
    test_the_only_outputs_nix_cannot_check_are_the_two_module_sets = {
      expr = lib.subtractLists [
        "apps"
        "checks"
        "darwinConfigurations"
        "darwinModules"
        "devShell"
        "devShells"
        "formatter"
        "homeConfigurations"
        "homeModules"
        "hydraJobs"
        "legacyPackages"
        "nixosConfigurations"
        "nixosGenerations"
        "nixosModules"
        "overlays"
        "packages"
        "templates"
      ] (systemsWith flake);
      expected = [
        "flakeModules"
        "homeManagerModules"
      ];
    };
  };
}
