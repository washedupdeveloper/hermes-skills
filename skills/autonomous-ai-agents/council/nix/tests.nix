# The eval tier: assertions about what the configuration SAYS.
#
# An assertion belongs in the cheapest tier that can make it — eval (a value, no
# build, milliseconds, and `lib.runTests` names the failing test with both
# values), build (an artifact, nix/checks.nix), e2e (a running machine,
# `.#vm-test`, kept OUT of `checks` because it needs /dev/kvm). Groups are
# separate checks so `--keep-going` reports every failing group.
{
  lib,
  pkgs,
  flake,
  systems,
}:
let
  # Stand-in for the home-manager surface `nix/module.nix` touches; the real
  # module is imported against it, so the module under test is the one that ships.
  #
  # `withHermes` is the one condition the module branches on — `hermes-agent` is a
  # separate input, so this repo must evaluate both ways. `services` must exist in
  # BOTH branches: a definition under `mkIf false` still needs its option path,
  # and a config with no home-manager at all is a different claim.
  mkStub =
    withHermes:
    { lib, ... }:
    {
      options = {
        home = {
          # From the repo's own allowlist, not an invented name: the portability
          # test flags any /home/<name> that is not a known placeholder.
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

  # `pkgs.hello` stands in for both the CLI and the skill tree: these assertions
  # are about the WIRING; the real artifacts are inspected by `checks.skill-layout`.
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

  # Derived the way the module derives it. Bound to a name because
  # `${cfgOf { }.council.hermesHome}` would close the interpolation at the `}`.
  defaultCfg = cfgOf { };

  libraryLink = "${defaultCfg.council.hermesHome}/skills/autonomous-ai-agents/council";

  failedAssertions = cfg: builtins.filter (a: !a.assertion) cfg.assertions;

  # Comparing attribute NAMES does not force the derivations, so this stays
  # milliseconds even for darwin on a Linux host. Sorted because `attrNames` is
  # sorted and flake-parts keeps `systems` in declaration order.
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
    # Key asserted separately from value: a bare `.source` lookup on a missing key
    # dies with `attribute '...' missing`, an eval error rather than a named test.
    test_library_mode_links_into_the_documented_path = {
      expr = builtins.attrNames (cfgOf { council.mode = "library"; }).home.file;
      expected = [ libraryLink ];
    };

    test_the_link_points_at_the_skill = {
      # `or null` so a missing key fails this test with both values instead of
      # aborting the group with an eval error.
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

    # The message is the point: it must name the way out, or the failure has no
    # remedy.
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
    # `systems` is a build contract: a listed system promises every per-system
    # output exists for it.
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

    # The two integration points a flake or a user's switch consumes; without
    # them the declarative path is prose.
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

    # `nix flake check` knows a fixed set of output names and skips the rest with
    # a warning. The two it cannot know are enumerated below, so a new custom
    # output has to be added here on purpose.
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
