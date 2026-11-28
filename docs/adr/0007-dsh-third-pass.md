# The third pass over DeepSeek Harness: the codebase, not the rules

**Decision.** Ask what the agent's own codebase already seams, rather than what dsh does.
Seven seams were read in the pinned source — plugin root, tool-call hooks, model-request
hook, context engine, provider seam, disk hygiene, policy guidance — and every rule that
survived translation lives in the skill that owns its subject.

**What stayed prose.** A rule needing a seam Hermes does not have — a monotonic guard stage
(hooks run in registration order), per-session capability composition, ordered config patch
layers — is recorded as prose, never as a table that reads like capability.

**How a change lands.** Not by forking: `phoenix` builds `hermes-agent+harness-audit` by
calling this repo's `nix/plugin.nix` and overriding upstream's `minimal`, so behaviour
rides the flake input and the source stays upstream's.

**Rejected.** dsh's snapshot machinery, its doc-budget gate and PTC mode — the costs are in
ADR-0006, which is where the first refusal was argued.
