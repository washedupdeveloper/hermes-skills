# Workflow actions, runner images and installs are pinned to commits

**Decision.** Every `uses:` is a 40-hex SHA with its version in a trailing comment; runner
images are dated (`ubuntu-24.04`, not `-latest`); the Hermes install carries a rev.

**Why.** A tag or a `-latest` label is mutable: whoever owns it executes code in this CI,
with this workflow's token, and no diff lands here. The failure is silent and total.

**Cost accepted.** A SHA is not updated by anything, so the update path is built instead of
inherited: a grouped Dependabot PR a week, the whole gate on it, and a person reading the
diff. A runner deprecation arrives as a red job rather than as a silent upgrade.

**Enforced.** `nix/tests.nix` asserts the pins with a negative control per predicate.
