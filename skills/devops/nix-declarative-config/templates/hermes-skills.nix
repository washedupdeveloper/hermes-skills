# Starter home-manager module: link agent skills from a pinned upstream repo into
# ~/.hermes/skills/<name> as symlinks into the Nix store. Wire-up: flake.nix gets
# `inputs.caveman = { url = "github:JuliusBrussee/caveman"; flake = false; }`, the module
# gets `extraSpecialArgs = { inherit inputs; }`, then set my.hermesRepoSkills.enable = true.
# Swap `src` for the fetchFromGitHub form below when you do not want a new input.
{ config, lib, pkgs, inputs, ... }:

let
  cfg = config.my.hermesRepoSkills;

  # Non-flake repo -> `flake = false` input, used as a path.
  src = inputs.caveman;

  # fetchFromGitHub alternative (no flake input needed):
  # src = pkgs.fetchFromGitHub {
  #   owner = "JuliusBrussee";
  #   repo = "caveman";
  #   rev = "f5d729488caa8f6a5b6c8086fe2cccd3e8a63f91";
  #   hash = lib.fakeHash;   # build once; Nix prints the real hash
  # };

  # Children are the skills; each holds a SKILL.md.
  skillsRoot = src + "/skills";

  # Discover by marker file: new skills appear after `nix flake update`, and
  # non-skill siblings (registry.json, *.mjs, native/, generated/) drop out.
  discovered = lib.filterAttrs
    (name: type:
      type == "directory"
      && builtins.pathExists "${skillsRoot}/${name}/SKILL.md")
    (builtins.readDir skillsRoot);

  selected =
    if cfg.skills == null then discovered
    else lib.filterAttrs (name: _: builtins.elem name cfg.skills) discovered;

  missing = lib.optionals (cfg.skills != null)
    (lib.filter (n: !(discovered ? ${n})) cfg.skills);
in
{
  options.my.hermesRepoSkills = {
    enable = lib.mkEnableOption "agent skills linked from a pinned upstream repo";

    skills = lib.mkOption {
      type = lib.types.nullOr (lib.types.listOf lib.types.str);
      default = null;
      description = "Which skills to link. null = every discovered skill.";
      example = [ "caveman" "caveman-commit" "caveman-review" ];
    };

    hermesHome = lib.mkOption {
      type = lib.types.str;
      default = ".hermes";
      description = "Hermes home relative to $HOME (HERMES_HOME).";
    };
  };

  config = lib.mkIf cfg.enable {
    assertions = [{
      assertion = missing == [ ];
      message =
        "my.hermesRepoSkills.skills: not present in the pinned repo: "
        + lib.concatStringsSep ", " missing;
    }];

    # ~/.hermes/skills/<name> -> /nix/store/.../skills/<name>. Hermes discovers
    # symlinked skill dirs (os.walk followlinks=True), so they load like real ones.
    # Read-only by design: `nix flake update caveman && home-manager switch`.
    home.file = lib.mapAttrs'
      (name: _:
        lib.nameValuePair "${cfg.hermesHome}/skills/${name}" {
          source = "${skillsRoot}/${name}";
        })
      selected;
  };
}
