# Versions the repository adopts in more than one place.
#
# One home, checked by `nix/tests.nix` at every adoption site: `AGENTS.md`, the CI job, the
# `openspec` skill's `templates/ci-job.yml`, and that skill's `scripts/bootstrap.sh`. Bumping
# is this file plus those four lines; the gate fails, naming path and line, if they disagree
# or if a fifth file starts naming the package without being added to the checked set.
{
  openspecCli = "1.15.0";
}
