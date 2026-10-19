# nix/overlay.nix — add the harness-audit plugin to a Hermes Agent package, without
# patching Hermes.
#
# Hermes' own flake documents the seam this uses:
#
#     pkgs.hermes-agent.override { extraPythonPackages = [ ... ]; }
#
# The wrapper it generates then carries `--suffix PYTHONPATH` pointing at those packages,
# and the agent discovers the plugin through the `hermes_agent.plugins` entry point. So
# neither the Hermes source tree nor the profile home is touched: the overlay changes only
# the wrapper's PYTHONPATH.
#
# Two shapes, because they cost very different amounts:
#
#   overlays.default   rebuilds the Hermes derivation with the extra package — correct,
#                      upstream-sanctioned, and the only shape that gets upstream's own
#                      plugin/core collision check.
#   overlays.wrapper   wraps the EXISTING binary instead, so Hermes is not rebuilt at all.
#                      Verified against the installed store path: the wrapped `hermes
#                      plugins list` reports the plugin with source `entrypoint`.
#
# Each overlay builds the plugin from the consumer's own pkgs, so this file needs no
# arguments and the flake exposes it one level deep, where `nix flake check` expects it:
#
#     nixpkgs.overlays = [ hermes-skills.overlays.default ];
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
