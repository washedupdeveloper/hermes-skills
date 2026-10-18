# Workflow actions and the Hermes install are pinned to commits, not tags

`uses: actions/checkout@v7` names a **mutable tag**. Whoever can move that tag — the
action's maintainer, or anyone who compromises their account — executes code in this
repository's CI, with this workflow's token, without a single change landing here. The
same applies to `nix profile install github:NousResearch/hermes-agent#minimal`, which
follows a branch and therefore tests a different product tomorrow.

So every `uses:` is a 40-hex commit SHA with the version it was chosen for in a trailing
comment, and the Hermes install carries a rev.

**What this gives up, stated plainly.** A SHA pin is not updated by anything: no
dependabot rule is configured here, so a security fix in an action reaches this repo only
when a person edits the line. A major tag auto-updates and is therefore both more
convenient and the actual supply-chain hole. The comment beside each pin is what keeps the
staleness visible; `nix flake check` is what keeps the pin from drifting back, because the
rule is a property of the source file rather than a matter of review.

**Rejected: pinning the major, which is what `review-council`'s `docs/CI.md` recorded as
the trade-off.** That reasoning assumed the tag's owner is trusted to only ever move it
forward to a compatible release. A tag is not a promise the reader can verify, and the
failure is silent and total: no diff, no review, arbitrary code with a token. The
convenience it buys — automatic patch updates — is worth less than the ability to say what
ran, and the update path is one commit either way.

**Not adopted: a floating `ubuntu-latest`.** The runner image is also mutable, and pinning
it to `ubuntu-24.04` would make the gate reproducible. It is left alone deliberately: a
runner-image bump is visible in the job summary and cannot execute third-party code, so
the trade-off that applies to actions does not apply here.

The pins are asserted in `nix/tests.nix` under `workflows`, with a negative control per
predicate — a check that cannot fail would pass on any workflow at all.
