# Load this repo by reference, never by symlink or copy

**Decision.** Hermes reads `skills/` through `skills.external_dirs`. Nothing is symlinked
into `$HERMES_HOME/skills`, nothing is copied.

**Why.** `external_dirs` is a read path, not a permission boundary: Hermes patches a skill
wherever it finds it, so a write aimed at "the live library" lands *through* a symlink into
this repo. Nix's profile symlink is safe because the store is read-only, not because it is
a link.

**Cost accepted.** The mount cannot protect the tree. Git is the boundary: an unattended
write shows in `git status` and reverts with `git checkout`.

**Rejected.** A copy script — imperative, drifts, and a real directory in the local skills
root outranks `external_dirs` silently.
