# The declarative half of the bootstrap.
#
# See docs/bootstrap.md for the four paths and why this one is the only one where
# drift is impossible, and docs/adr/0004 for the store-path decision.
#
# Home-manager module: Hermes runs user-level with its own HERMES_HOME, so the
# skill it loads, the CLI on its PATH and the settings that point at both are all
# user state. Import it into the user's HM module list:
#
#   home-manager.users.<name>.imports = [ inputs.review-council.homeManagerModules.default ];
{
  config,
  lib,
  options,
  ...
}:
let
  cfg = config.programs.council;

  # Hermes' own module is a SEPARATE input, so this repo must evaluate without it.
  # `options` (not `config`) is the map that answers "is that option declared here".
  hermesModulePresent = options.services or { } ? hermes-agent;
in
{
  options.programs.council = {
    enable = lib.mkEnableOption "the review council";

    package = lib.mkOption {
      type = lib.types.package;
      description = "The `council` CLI — every verb, with the pinned toolchain on PATH.";
    };

    skill = lib.mkOption {
      type = lib.types.package;
      description = ''
        The deployable skill tree: SKILL.md, scripts/, tests/, assets/bots,
        assets/rubrics, and the two flake files. Built by this flake as `.#skill`.

        It is a **store path**, which is the point: read-only, so the deployed
        skill cannot be edited in place and therefore cannot drift from source.
      '';
    };

    mode = lib.mkOption {
      type = lib.types.enum [
        "external-dirs"
        "library"
      ];
      default = "external-dirs";
      description = ''
        How the skill reaches Hermes.

        `external-dirs` (the default) hands the store path to Hermes' own module as
        an extra search path. This is the form that actually protects the source:
        the tree is read-only, so a background write cannot land in it.

        `library` links it into `<hermesHome>/skills/autonomous-ai-agents/council`
        instead. Use it when Hermes is not configured through Nix. Note the
        difference from `external-dirs`: this is a *link*, and a link redirects a
        write rather than preventing one.
      '';
    };

    hermesHome = lib.mkOption {
      type = lib.types.str;
      default = "${config.home.homeDirectory}/.hermes";
      description = "HERMES_HOME. Read only in `library` mode.";
    };
  };

  config = lib.mkIf cfg.enable (
    lib.mkMerge [
      { home.packages = [ cfg.package ]; }

      # Default: one owner for the setting. List options concatenate, so this adds to
      # whatever the user declared rather than replacing it.
      (lib.mkIf (cfg.mode == "external-dirs" && hermesModulePresent) {
        services.hermes-agent.settings.skills.external_dirs = [ "${cfg.skill}" ];
      })

      (lib.mkIf (cfg.mode == "library") {
        home.file."${cfg.hermesHome}/skills/autonomous-ai-agents/council".source = cfg.skill;
      })

      # A mode was asked for that this configuration cannot satisfy. Fail the build
      # rather than installing a CLI nothing points at.
      {
        assertions = [
          {
            assertion = cfg.mode != "external-dirs" || hermesModulePresent;
            message = ''
              programs.council.mode is "external-dirs" but the Hermes module is not
              imported, so nothing consumes skills.external_dirs and the skill would
              be installed for nobody. Either import Hermes' nixosModules /
              homeManagerModules, or set programs.council.mode = "library".
            '';
          }
        ];
      }
    ]
  );
}
