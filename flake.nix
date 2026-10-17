{
  description = "hermes-skills — the locally-authored Hermes skills, with a gate over the tree";

  # One input. The gate is a tree check: no package is built for anyone, so
  # nixpkgs is here for a pinned Python and the linters, and nothing else.
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
      );
    };
}
