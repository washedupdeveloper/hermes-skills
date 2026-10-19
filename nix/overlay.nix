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
  pluginOf = prev: prev.callPackage ./plugin.nix { };
in
{
  default =
    final: prev:
    let
      base = prev.hermes-agent or null;
      plugin = pluginOf prev;
    in
    prev.lib.optionalAttrs (base != null) {
      hermes-agent = base.override {
        extraPythonPackages = [ plugin ];
      };
      inherit plugin;
    };

  wrapper =
    final: prev:
    let
      base = prev.hermes-agent or null;
      plugin = pluginOf prev;
    in
    prev.lib.optionalAttrs (base != null) {
      hermes-agent = prev.symlinkJoin {
        name = "hermes-agent+harness-audit";
        paths = [ base ];
        nativeBuildInputs = [ prev.makeWrapper ];
        postBuild = ''
          wrapProgram $out/bin/hermes \
            --suffix PYTHONPATH : "${plugin}/${prev.python3.sitePackages}"
        '';
        meta = base.meta or { };
      };
      inherit plugin;
    };
}
