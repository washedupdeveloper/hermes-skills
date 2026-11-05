{
  description = "hermes-skills — locally-authored Hermes skills, the harness-audit and library-guard plugins, and a gate over the tree";

  # One input. The gate is a tree check, and the plugin is pure Python, so nixpkgs is here
  # for a pinned Python and the linters. Hermes itself is deliberately NOT an input: the
  # overlay takes `pkgs.hermes-agent` from whoever consumes it, so this flake never pins a
  # second Hermes and cannot disagree with the one the machine actually runs.
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs =
    { self, nixpkgs }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "aarch64-darwin"
      ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f (import nixpkgs { inherit system; }));
      # Each plugin directory is one package; `pyproject.toml` is the single home for its name,
      # version and description (nix/plugin.nix reads them).
      pluginFor =
        pkgs: src: module:
        pkgs.callPackage ./nix/plugin.nix { inherit src module; };
      pluginsFor = pkgs: {
        harness-audit = pluginFor pkgs ./plugins/harness-audit "harness_audit";
        library-guard = pluginFor pkgs ./plugins/library-guard "library_guard";
      };
    in
    {
      # `nix flake check` is the one command. It covers the tree, the shipped
      # artifact, the retained Python suite and `setup.sh`'s behaviour — see
      # nix/checks.nix for which tier each belongs to.
      checks = forAllSystems (
        pkgs:
        import ./nix/checks.nix {
          inherit pkgs;
          lib = pkgs.lib;
          src = ./.;
        }
        # A plugin is a shipped artifact, so `nix flake check` builds it: a packaging
        # break (a missing entry point, a module the interpreter cannot import) then fails
        # the gate instead of only `nix build .#<plugin>`.
        // pluginsFor pkgs
      );

      packages = forAllSystems (
        pkgs:
        pluginsFor pkgs
        // {
          # The plugin the overlay was first written for.
          default = (pluginsFor pkgs).harness-audit;
        }
      );

      # Consume it as: nixpkgs.overlays = [ hermes-skills.overlays.default ];
      # See nix/overlay.nix for the two shapes and why they cost differently. The overlay
      # builds the plugin from the consumer's own pkgs, so it takes no arguments and sits
      # one level deep — the shape `nix flake check` validates.
      overlays = import ./nix/overlay.nix { };
    };
}
