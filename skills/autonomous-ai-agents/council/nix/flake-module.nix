# What another flake gets from
#   imports = [ inputs.review-council.flakeModules.default ];
#
# Consumer-facing surface only: packages, formatter, one app. This repo's gates
# stay in nix/checks.nix — a consumer does not want its tree run through this
# repo's suite. The builders are shared with checks.nix, not copied, so what a
# consumer builds and what this flake's checks exercise are one definition.
{ lib, inputs, ... }:
let
  builders = import ./builders.nix {
    inherit lib;
    nixpkgs = inputs.nixpkgs or { };
  };
in
{
  perSystem =
    { pkgs, config, ... }:
    {
      packages = {
        toolchain = builders.mkToolchain pkgs;
        # The deployable skill as a read-only store path — what
        # programs.council.mode = "external-dirs" points at.
        skill = builders.mkSkill pkgs;
        # What ships. `dev-framework` adds the dev verbs and the suite — the same
        # split a verb's `audience` expresses.
        framework = builders.mkFramework pkgs "user";
        dev-framework = builders.mkFramework pkgs "dev";
        # `nix shell .#review-council` — the command plus the analyzers on one PATH.
        review-council = pkgs.symlinkJoin {
          name = "review-council";
          paths = [
            (builders.mkDispatcher pkgs "user")
            (builders.mkToolchain pkgs)
          ];
        };
        default = builders.mkToolchain pkgs;
      }
      # dockerTools cannot build a Linux userspace from darwin, so this is guarded
      # rather than left to fail on the darwin systems above.
      // lib.optionalAttrs pkgs.stdenv.hostPlatform.isLinux {
        # `nix build .#container` -> an OCI image tarball for `docker load`.
        container = builders.mkContainer pkgs;
        # `nix build .#image-root` -> the runtime tree as a directory, whose
        # closure the Dockerfile copies. Same definitions as `container`.
        image-root = builders.mkImageRoot pkgs;
        # `nix build .#image-prep-tools` -> build-only tools for the Dockerfile,
        # never part of the image. See builders.mkImagePrepTools.
        image-prep-tools = builders.mkImagePrepTools pkgs;
        # `nix build .#vm-test` -> the council end-to-end in a NixOS VM. Needs KVM,
        # so it is NOT in `checks`: the fast gate must not require hardware a
        # contributor may not have.
        vm-test = builders.mkVmTest pkgs;
      };

      formatter = pkgs.writeShellScriptBin "treefmt" ''
        exec ${pkgs.nixfmt-tree}/bin/treefmt \
          --excludes 'tests/golden/*' \
          --excludes '.review-council/*' \
          "$@"
      '';

      apps =
        let
          council = builders.mkDispatcher pkgs "user";
        in
        {
          council = {
            type = "app";
            program = lib.getExe council;
            meta.description = council.meta.description;
          };
          default = config.apps.council;
        };
    };
}
