# Versions the repository adopts in more than one place.
#
# `openspecCliSites` is the list, not a description of one. `nix/tests.nix` builds the adopted set
# from it (plus `.github/workflows/`, which it discovers), so a file that names the CLI without
# being listed here fails the gate rather than escaping it — and a listed file that is missing fails
# too. The list is data so that the gate has one place to read, and no prose needs to restate its
# size: an earlier revision said "four places" in three different files, and nothing checked the
# number.
{
  openspecCli = "1.15.0";

  openspecCliSites = [
    "AGENTS.md"
    "skills/software-development/openspec/scripts/bootstrap.sh"
    "skills/software-development/openspec/templates/ci-job.yml"
  ];
}
