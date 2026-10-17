# What another flake gets from
#   imports = [ inputs.review-council.flakeModules.default ];
#
# The consumer-facing surface only: the packages, the formatter and the one app.
# This repo's own gates live in nix/checks.nix, because a consumer does not want
# its tree run through this repo's test suite.
#
# The builders are shared with nix/checks.nix rather than copied, so the packages a
# consumer builds and the packages this flake's checks exercise are one definition.
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
        # programs.council.mode = "external-dirs" points Hermes at.
        skill = builders.mkSkill pkgs;
        # What ships: the runtime tree. `dev-framework` adds the development
        # verbs and the suite, which is what the devshell runs from — the same
        # split the `audience` of a verb expresses.
        framework = builders.mkFramework pkgs "user";
        dev-framework = builders.mkFramework pkgs "dev";
        # `nix shell .#review-council` — the command plus the analyzers on one
        # PATH, which is what you want when running it by hand.
        review-council = pkgs.symlinkJoin {
          name = "review-council";
          paths = [
            (builders.mkDispatcher pkgs "user")
            (builders.mkToolchain pkgs)
          ];
        };
        default = builders.mkToolchain pkgs;
      }
      # The image is a Linux userspace; dockerTools cannot build one from
      # darwin. Guarded rather than left to fail on the darwin systems above.
      // lib.optionalAttrs pkgs.stdenv.hostPlatform.isLinux {
        # `nix build .#container` -> an OCI image tarball for `docker load`.
        container = builders.mkContainer pkgs;
        # `nix build .#image-root` -> the same runtime tree as a directory,
        # whose closure is what the Dockerfile copies. Same definitions as
        # `container`, so the two paths cannot drift.
        image-root = builders.mkImageRoot pkgs;
        # `nix build .#image-prep-tools` -> the build-only tools the Dockerfile
        # needs. Never part of the image; see builders.mkImagePrepTools.
        image-prep-tools = builders.mkImagePrepTools pkgs;
        # `nix build .#vm-test` -> runs the council end-to-end in a NixOS VM.
        # A VM test needs KVM, so it is NOT in `checks`: the fast gate must not
        # require hardware a contributor may not have.
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
