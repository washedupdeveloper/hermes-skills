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

      # The CLI this repository's own specs are validated with. It is a package of the flake
      # rather than a thing installed at run time: `nix run .#openspec` resolves through
      # `flake.lock`, so the version moves when the lock moves and nowhere else.
      packages = forAllSystems (pkgs: {
        openspec = pkgs.openspec;
      });

      apps = forAllSystems (pkgs: {
        openspec = {
          type = "app";
          program = "${pkgs.openspec}/bin/openspec";
          meta.description = "Validate and archive the spec tree under openspec/";
        };
      });

      devShells = forAllSystems (pkgs: {
        # What `scripts/ci-local.sh` needs: the interpreter the gate runs on, pytest for
        # the suite, actionlint for the workflow, nixfmt for the formatter.
        default = pkgs.mkShell {
          packages = [
            pkgs.python3
            pkgs.python3Packages.pytest
            pkgs.actionlint
            pkgs.nixfmt
            pkgs.openspec
          ];
        };
      });
    };
}
