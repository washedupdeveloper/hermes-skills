{
  description = "hermes-skills — a portable library of agent skills, with a gate that runs with or without Nix";

  # One input, and it is optional to the project: `python3 scripts/validate.py` is the
  # gate. This flake exists so a Nix user gets the same gate under a pinned interpreter,
  # plus the formatter and the review checks that only matter to a maintainer here.
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
      # `nix flake check` runs `scripts/validate.py`, the Python suite, the prose claim
      # audit and the formatter, then the eval-tier checks this repository holds itself to.
      # None of it is required to USE the library — see README.md.
      checks = forAllSystems (
        pkgs:
        import ./nix/checks.nix {
          inherit pkgs;
          lib = pkgs.lib;
          src = ./.;
        }
      );

      devShells = forAllSystems (pkgs: {
        default = pkgs.mkShell {
          packages = [
            pkgs.python3
            pkgs.nixfmt
          ];
        };
      });
    };
}
