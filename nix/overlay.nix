# nix/overlay.nix — add the harness-audit plugin to a Hermes Agent package, without
# patching Hermes: `pkgs.hermes-agent.override { extraPythonPackages = [ … ]; }` gives the
# wrapper `--suffix PYTHONPATH`, and Hermes finds the plugin through the
# `hermes_agent.plugins` entry point. No Hermes source tree or profile home is touched.
#
# `default` rebuilds Hermes, and is the only shape that gets upstream's plugin/core
# collision check; `wrapper` wraps the EXISTING binary instead. See plugins/README.md.
#
# Takes no arguments (each overlay builds the plugin from the consumer's pkgs) and is
# exposed one level deep, where `nix flake check` expects it.
{ }:
let
  # Every plugin in ./plugins, built from the consumer's own pkgs: one home for the list, so a
  # consumer cannot enable the audit plugin and silently miss the guard.
  pluginsFor = prev: [
    (prev.callPackage ./plugin.nix {
      src = ../plugins/harness-audit;
      module = "harness_audit";
    })
    (prev.callPackage ./plugin.nix {
      src = ../plugins/library-guard;
      module = "library_guard";
    })
  ];

in
{
  default =
    final: prev:
    let
      base = prev.hermes-agent or null;
      plugins = pluginsFor prev;
    in
    prev.lib.optionalAttrs (base != null) {
      hermes-agent = base.override {
        extraPythonPackages = plugins;
      };
      plugin = builtins.head plugins;
      plugins = plugins;
    };

  wrapper =
    final: prev:
    let
      base = prev.hermes-agent or null;
      plugins = pluginsFor prev;
      suffix = prev.lib.concatMapStringsSep ":" (p: "${p}/${prev.python3.sitePackages}") plugins;
    in
    prev.lib.optionalAttrs (base != null) {
      hermes-agent = prev.symlinkJoin {
        name = "hermes-agent+hermes-skills-plugins";
        paths = [ base ];
        nativeBuildInputs = [ prev.makeWrapper ];
        postBuild = ''
          wrapProgram $out/bin/hermes \
            --suffix PYTHONPATH : "${suffix}"
        '';
        meta = base.meta or { };
      };
      plugin = builtins.head plugins;
      plugins = plugins;
    };
}
