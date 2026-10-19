# Workflow actions and the Hermes install are pinned to commits, not tags

`uses: actions/checkout@v7` names a **mutable tag**. Whoever can move that tag — the
action's maintainer, or anyone who compromises their account — executes code in this
repository's CI, with this workflow's token, without a single change landing here. The
same applies to `nix profile install github:NousResearch/hermes-agent#minimal`, which
follows a branch and therefore tests a different product tomorrow.

So every `uses:` is a 40-hex commit SHA with the version it was chosen for in a trailing
comment, and the Hermes install carries a rev.

**What this gives up, stated plainly.** A SHA pin is not updated by anything. A major tag
auto-updates and is therefore both more convenient and the actual supply-chain hole, so the
update path has to be built instead of inherited: `.github/dependabot.yml` opens one grouped
PR a week that bumps the SHAs, CI runs the whole gate on it, and a person reads the diff.
That is GitHub-hosted, so no third-party action is added. The comment beside each pin keeps
the staleness visible; `nix flake check` keeps the pin from drifting back, because the rule
is a property of the source file rather than a matter of review.

**Rejected: pinning the major, which is what `review-council`'s `docs/CI.md` recorded as
the trade-off.** That reasoning assumed the tag's owner is trusted to only ever move it
forward to a compatible release. A tag is not a promise the reader can verify, and the
failure is silent and total: no diff, no review, arbitrary code with a token. The
convenience it buys — automatic patch updates — is worth less than the ability to say what
ran, and the update path is one commit either way.

**Adopted later, in the same spirit: the runner images are pinned too.** `ubuntu-latest`,
`macos-latest` and `windows-latest` are mutable labels — the image changes under the
workflow with no diff here — so they are now `ubuntu-24.04`, `macos-26` and `windows-2025`,
each verified against `actions/runner-images` at the time of pinning. The cost is that a
runner deprecation arrives as a red job rather than a silent upgrade, which is the trade
this file argues for everywhere else.

The pins are asserted in `nix/tests.nix` under `workflows`, with a negative control per
predicate — a check that cannot fail would pass on any workflow at all.
