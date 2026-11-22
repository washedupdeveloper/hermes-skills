# Versions the repository adopts in more than one place.
#
# `openspecCli` is not a version anyone installs: it is what `nix run .#openspec` must
# resolve to, asserted against `pkgs.openspec.version` so a nixpkgs bump fails the gate
# instead of silently changing the CLI that validates the specs.
#
# `openspecCliSites` is the list, not a description of one. `nix/tests.nix` builds the adopted set
# from it (plus `.github/workflows/`, which it discovers), so a file that names the CLI without
# being listed here fails the gate rather than escaping it — and a listed file that is missing fails
# too. The list is data so that the gate has one place to read, and no prose needs to restate its
# size: an earlier revision said "four places" in three different files, and nothing checked the
# number.
{
  openspecCli = "1.14.1";

  openspecCliSites = [
    "AGENTS.md"
    "skills/software-development/openspec/SKILL.md"
    "skills/software-development/openspec/scripts/bootstrap.sh"
    "skills/software-development/openspec/templates/ci-job.yml"
  ];
}
