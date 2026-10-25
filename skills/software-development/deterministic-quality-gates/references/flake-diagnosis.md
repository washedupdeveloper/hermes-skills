# Flake diagnosis

The CI half of test reliability: what to freeze before theorising, how to classify a
probabilistic failure, the smallest topology that reproduces it, and what a
diagnosis-only request does and does not authorize. The local half — masking, budgets,
quiescence — is `test-reliability.md`.

## Freeze the evidence, then classify

A flake is diagnosed from frozen evidence, never from the fix that eventually worked:
repository, workflow, job and commit SHA; runner labels and timestamps; the exact failing
test; the first stable failure signature; and infrastructure messages kept separate from
test output. Classify into a named class before any edit.

**Check:** several failing runs and several passing runs of the *same* SHA are compared,
and each independent fact is reported separately — one passing rerun is not an
infrastructure fault, and one timeout is not a product race.
**Boundary:** a deterministic local failure needs no classification; provider transience is
classified only at that boundary; when no host metrics exist, say so and classify from what
the logs carry.

## Reproduce at the smallest topology that shows the signature

Climb only as far as the signature requires: one test process -> concurrent tests in one
file -> independent worker processes -> the owning gate at its configured worker count ->
separate jobs sharing the implicated host resource.

**Check:** the rung, the active configuration and the platform are named; a race takes a
barrier at the contested transition; a collision proves simultaneous acquisition or atomic
allocation; and the fix fails before and passes after under that same topology.
**Boundary:** never lower a production timeout or add random load to manufacture a failure;
where the platform is unreachable, record the limit instead of substituting a passing run
elsewhere; and never rerun until it happens to pass.

## A diagnosis-only request is read-only

"Investigate this flake" authorizes the cause and the evidence — not a fix, not a CI rerun,
not a workflow change.

**Check:** the report stops at the requested boundary, with no diff and no rerun; an
authorized fix lands in the component that allocates, publishes readiness, mutates global
state, or owns teardown — never a normalizer, a retry wrapper, a broader timeout, global
serialization, or a weaker assertion.
**Boundary:** only the user's explicit request widens the scope beyond the diagnosis.

## Evidence to report

The frozen identifiers, the class, the reproduction rung and platform, the failing and
passing runs compared, and — for a fix — the pre-fix failure and the post-fix pass under
the same topology. A hypothesis that was never reproduced is reported as a hypothesis.