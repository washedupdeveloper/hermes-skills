{
  description = "review-council — pinned, declarative deterministic review toolchain";

  # Determinism contract (research/nix-tooling.md §0): every score reproducible
  # from a pinned tool set on one pinned nixpkgs, so the set moves atomically and
  # `nix build .#toolchain` is the same store path everywhere. One command, one
  # app — the modules stay separate programs and become its verbs. See docs/NIX.md.
  #
  # `audience` is load-bearing: the shipped app exposes `user` verbs, the devshell
  # adds `dev`, and checks.commands asserts the split. This file configures;
  # nix/builders.nix constructs; the import surfaces are flake-module.nix and
  # checks.nix.
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

        # Consumer surface, then this repo's own gates; another flake imports the
        # first only (see flakeModules below).
        imports = [
          ./nix/flake-module.nix
          ./nix/checks.nix
        ];

        flake = {
          # Hermes runs user-level with its own HERMES_HOME, so the skill, the CLI
          # and the settings pointing at both are user state — hence home-manager.
          # Defaults come from THIS flake, so importing the module is the whole
          # setup; usage in nix/home-manager.md, options in nix/module.nix.
          #
          # `nix flake check` knows a fixed set of output names and would skip this
          # one with a warning, so the `module` group (nix/tests.nix) evaluates it.
          homeManagerModules.default =
            { lib, pkgs, ... }:
            {
              imports = [ (import ./nix/module.nix) ];
              programs.council.package =
                lib.mkDefault
                  self.packages.${pkgs.stdenv.hostPlatform.system}.review-council;
              programs.council.skill = lib.mkDefault self.packages.${pkgs.stdenv.hostPlatform.system}.skill;
            };

          # Another flake's integration point:
          #
          #     imports = [ inputs.review-council.flakeModules.default ];
          #
          # Same definitions this repo builds for itself, not a copy.
          flakeModules.default = ./nix/flake-module.nix;

          # `nix flake init -t` writes a working consumer, so onboarding is one
          # command rather than a doc. checks.templates asserts they still
          # reference the PUBLISHED flake and import the module — a rotted template
          # fails in someone else's repository.
          templates = {
            default = {
              path = ./templates/flake-parts;
              description = "A flake-parts flake that imports the council's packages, formatter and app";
            };
            flake-parts = {
              path = ./templates/flake-parts;
              description = "A flake-parts flake that imports the council's packages, formatter and app";
            };
            home-manager = {
              path = ./templates/home-manager;
              description = "A home-manager module that enables programs.council";
            };
          };
        };
      }
    );
}
