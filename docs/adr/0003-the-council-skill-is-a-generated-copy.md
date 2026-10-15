# The council skill is a generated copy, not a reference

`skills/autonomous-ai-agents/council/` is a **copy** of the council, produced by
`council setup skill` — which writes to whatever `skills.external_dirs` resolves to,
and on the author's machine that is this repository. It reads as a contradiction of
[ADR-0001](0001-reference-not-symlink.md), so it needs the distinction stated:
ADR-0001 governs how **Hermes loads the skills this repo authors**. This governs how
**another repository's artifact is published into it**. The direction is opposite, so
the rule is opposite.

The alternative was to reference the council repo instead of copying. That fails the
requirement the skill exists to meet: **a machine with no council checkout must be able
to run `/council`.** The skill's whole purpose is to arrive with the toolchain it needs.
A reference would make every deployment a two-repo deployment.

The cost is real and already paid once: a copy drifts. Measured before the fix,
**11 files differed** from source (`__pycache__` aside) and the deployment's test suite
did not run at all — `test_modules.py` imported a file the sync never ships, so
collection aborted and **zero of its tests executed**. A suite that cannot fail is
worse than no suite, because it reads as green.

The discipline that follows, and that `scripts/claim-audit.py` now enforces:

- **The generator is the source of truth.** Edit `review-council`, then run
  `council setup skill`. Never edit the copy — the next sync silently reverts it.
- **The copy is checked, not trusted.** `claim-audit.py` compares every vendored
  script byte-for-byte against the sibling checkout and fails loudly on drift.
- **The copier never ships itself.** `sync_to_skill.py` excludes its own name, because
  the deployment cannot re-copy what it does not have. Anything that references it — a
  test, a doc line — must therefore say "repository only". Getting this wrong is what
  broke the deployed suite.
- **A deployed test must skip what it cannot assert.** `_require_repo()` guards the
  tests that assert repo-side wiring. In the deployment those are skipped by name, not
  failed.
