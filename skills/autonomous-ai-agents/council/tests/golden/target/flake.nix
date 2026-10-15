{
  description = "golden-fixture: a miniature flake, so the golden suite has a fixed target";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs =
    { nixpkgs, ... }:
    {
      nixosConfigurations.host = nixpkgs.lib.nixosSystem {
        system = "x86_64-linux";
        modules = [ ./modules/base.nix ];
      };
    };
}
