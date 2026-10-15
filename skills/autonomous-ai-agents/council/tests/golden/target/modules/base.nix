{ pkgs, ... }:

{
  # A deliberately tiny module. The golden suite does not care what this does —
  # only that it exists, so kloc is a fixed, known number.
  networking.hostName = "host";

  environment.systemPackages = [ pkgs.curl ];

  services.openssh = {
    enable = true;
    settings.PasswordAuthentication = false;
  };

  users.users.reviewer = {
    isNormalUser = true;
    extraGroups = [ "wheel" ];
  };

  nix.settings.trusted-users = [ "root" "reviewer" ];

  system.stateVersion = "26.05";
}
