{
  description = "review-council — pinned, declarative deterministic review toolchain";

  # Determinism contract (research/nix-tooling.md §0): every category score must
  # be reproducible from a pinned tool set on a pinned nixpkgs revision. Every
  # tool comes from this one input, pinned in flake.lock, so the set moves
  # atomically and `nix build .#toolchain` yields the same store path everywhere.
  #
  # ONE COMMAND. The modules under scripts/ stay separate programs; the INTERFACE
  # is unified. There is exactly one app, `council`, and the modules are its
  # verbs:
  #
  #     nix run .#council -- review <repo>
  #     nix run .#council -- setup bots
  #
  # With no arguments it prints that list. Nothing in this repo is run by hand.
  #
  # `audience` is load-bearing, not documentation: the shipped app exposes `user`
  # verbs, the devshell also exposes `dev` ones, and checks.commands asserts the
  # split so it cannot decay into a comment.
  #
  # The toolchain, the framework tree, the command surface, the gates and the
  # formatter are declarative and pinned. The council LOOP cannot be: it spawns
  # non-deterministic LLM agents over the network, an effect rather than a build,
  # so it is exposed as a pinned interface — see docs/NIX.md.
  #
  # STRUCTURE. This file is the configuration, not the construction: the builders
  # are in nix/builders.nix, the consumer-facing outputs in nix/flake-module.nix,
  # and this repo's own gates in nix/checks.nix.
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

    flake-parts.url = "github:hercules-ci/flake-parts";
    # Without this every consumer's flake.lock carries a second nixpkgs-lib, which
    # is the one real cost of being a flake-parts flake. Following ours removes it.
    flake-parts.inputs.nixpkgs-lib.follows = "nixpkgs";
  };

  outputs =
    inputs:
    inputs.flake-parts.lib.mkFlake { inherit inputs; } (
      { self, ... }:
      {
        # No x86_64-darwin: nixpkgs 26.11 dropped it, so advertising it makes
        # `nix flake show` error instead of listing anything.
        systems = [
          "x86_64-linux"
          "aarch64-linux"
          "aarch64-darwin"
        ];

        # The consumer-facing surface, then this repo's own gates. Importing the
        # first alone is what another flake does — see flakeModules below.
        imports = [
          ./nix/flake-module.nix
          ./nix/checks.nix
        ];

        flake = {
          # The declarative path. Hermes runs user-level with its own HERMES_HOME, so
          # the skill it loads, the CLI on its PATH and the settings that point at both
          # are user state — a home-manager module is the scope that matches.
          #
          # Defaults come from THIS flake, so importing the module is the whole setup.
          # Usage is in nix/home-manager.md; the options and their reasoning are in
          # nix/module.nix.
          #
          # `nix flake check` knows a fixed set of output names and would skip this one
          # with a warning, so checks.module-evaluates evaluates it explicitly.
          homeManagerModules.default =
            { lib, pkgs, ... }:
            {
              imports = [ (import ./nix/module.nix) ];
              programs.council.package =
                lib.mkDefault
                  self.packages.${pkgs.stdenv.hostPlatform.system}.review-council;
              programs.council.skill = lib.mkDefault self.packages.${pkgs.stdenv.hostPlatform.system}.skill;
            };

          # The integration point for another flake:
          #
          #     imports = [ inputs.review-council.flakeModules.default ];
          #
          # That yields the packages, the formatter and the app — the same
          # definitions this repo builds for itself, not a copy of them.
          flakeModules.default = ./nix/flake-module.nix;
        };
      }
    );
}
