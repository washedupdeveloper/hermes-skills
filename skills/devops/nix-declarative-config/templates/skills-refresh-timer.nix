# Starter home-manager module (GLOBAL scope): publish agent skills at a path that
# never changes, refresh from upstream on a timer, and report what changed. Use it when
# skills must reach EVERY project and track upstream, not a frozen snapshot.
# NOT YET BUILT end-to-end: derived from documented behaviour (`skills.external_dirs`,
# silent skip of missing paths) plus standard Nix - run the SKILL.md verification first.
#
# Wire-up:
#   1. flake.nix: `inputs.caveman = { url = "github:JuliusBrussee/caveman"; flake = false; };`
#      no `rev` -> flake.lock pins the exact commit while the input keeps tracking the branch.
#   2. That flake must expose the skills as a package attribute, linkFarm over the
#      discovered skill dirs, e.g.:
#        packages.<system>.skills = pkgs.linkFarm "agent-skills"
#          (map (n: { name = n; path = "${root}/${n}"; })
#               (lib.attrNames (lib.filterAttrs
#                 (n: t: t == "directory" && builtins.pathExists "${root}/${n}/SKILL.md")
#                 (builtins.readDir root))));
#      linkFarm copies into the store, but the result is rebuilt from upstream on every
#      refresh, so it is a derived artifact, not a frozen copy.
#   3. Import this file and set my.skillsRefresh.enable = true;
#   4. Point Hermes at the stable path ONCE - declaratively if managed:
#        services.hermes-agent.settings.skills.external_dirs =
#          [ "${config.home.homeDirectory}/.local/share/agent-skills/current" ];
#      or, unmanaged:
#        hermes config set skills.external_dirs '["/abs/path/current"]'
{
  config,
  lib,
  pkgs,
  inputs,
  ...
}:

let
  cfg = config.my.skillsRefresh;

  # Timer owns `current`; home-manager owns only this parent dir and its `.keep` - if
  # both owned the symlink they would fight on every switch.
  # See references/unattended-refresh-job.md.
  root = "${config.home.homeDirectory}/.local/share/agent-skills";
  link = "${root}/current";

  stateDir = "${config.xdg.stateHome}/skills-refresh";

  refresh = pkgs.writeShellScript "skills-refresh" ''
    set -euo pipefail
    export PATH=${
      lib.makeBinPath [
        pkgs.nix
        pkgs.coreutils
        pkgs.diffutils
      ]
    }:$PATH

    mkdir -p "${stateDir}"
    prev="${stateDir}/manifest.prev"
    cur="${stateDir}/manifest.cur"

    # Move the lock forward, then rebuild: the resolved commit is recorded in
    # flake.lock, so the result stays reproducible after the fact.
    nix flake update --flake ${cfg.flakeDir} ${cfg.inputName}
    nix build --flake ${cfg.flakeDir} --out-link "${link}" .#${cfg.attr}

    # One hashed line per skill, so the report below is a real diff.
    find "${link}" -name SKILL.md -print0 \
      | sort -z | xargs -0 -r sha256sum > "$cur"

    if [ -f "$prev" ] && ! diff -q "$prev" "$cur" > /dev/null; then
      # Report only on change. `hermes send` pipes output to a configured messaging
      # platform - check `hermes send --help` for the exact flag, or swap in a notifier.
      diff -u "$prev" "$cur" | hermes send || true
    fi

    mv "$cur" "$prev"
  '';
in
{
  options.my.skillsRefresh = {
    enable = lib.mkEnableOption "refreshing provisioned agent skills from upstream";

    flakeDir = lib.mkOption {
      type = lib.types.str;
      description = "Absolute path to the flake declaring the skills input.";
    };

    inputName = lib.mkOption {
      type = lib.types.str;
      default = "caveman";
      description = "Name of the `flake = false` skills input in that flake.";
    };

    attr = lib.mkOption {
      type = lib.types.str;
      default = "skills";
      description = "Package attribute exposing the skills directory.";
    };

    schedule = lib.mkOption {
      type = lib.types.str;
      default = "daily";
      description = "systemd OnCalendar expression for the refresh.";
    };
  };

  config = lib.mkIf cfg.enable {
    home.file."${root}/.keep".text = "";

    systemd.user.services.skills-refresh = {
      Unit.Description = "Refresh provisioned agent skills from upstream";
      Service = {
        Type = "oneshot";
        ExecStart = "${refresh}";
      };
    };

    systemd.user.timers.skills-refresh = {
      Unit.Description = "Scheduled refresh of provisioned agent skills";
      Timer = {
        OnCalendar = cfg.schedule;
        Persistent = true; # catch up after the machine was off
        RandomizedDelaySec = "2h"; # do not hammer the forge on the hour
      };
      Install.WantedBy = [ "timers.target" ];
    };
  };
}
