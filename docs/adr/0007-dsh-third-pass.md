# The third pass over DeepSeek Harness: the codebase, the record, and what stayed prose

Pass 1 ([ADR-0004](0004-adopt-dsh-harness-rules.md)) took four harness rules and rejected the
framework; pass 2 ([ADR-0006](0006-dsh-second-pass.md)) took the rule format, the bug and incident
classes, three gate rules and the tool surface. Pass 3 asked a different question: **what does the
agent's own codebase already seam, and which rules survive translation into it?**

Seven scopes were read in parallel: the six `docs/defensive-patterns/` documents, the four
postmortems, the testing policy against the repo's own `AGENTS.md`, the `.agents/` tree, the skills
and system-prompt subsystems, the capability-seam documents, and the review practice.

## What the agent codebase seams

The source is local and read-only — the revision `flake.lock` pins it:

```sh
nix eval --impure --raw --expr \
  'builtins.toString (builtins.getFlake "~/projects/phoenix").inputs.hermes-agent.outPath'
```

| seam | where | what it serves |
|---|---|---|
| plugin root | `plugins/<name>/` + `plugins/plugin_loader.py`, loaded via `register(ctx)` | the extension point everything else rides |
| tool-call hooks | `pre_tool_call`, `post_tool_call`, `transform_tool_result` (first-string-wins) | policy, audit, output rewriting |
| model-request hook | `pre_api_request` | the request log the `harness-audit` plugin writes |
| context/prompt engineering | `plugins/context_engine/` | what the model is shown, as a projection |
| provider seam | `plugins/model-providers/` | a second provider without touching the loop |
| disk hygiene | `plugins/disk-cleanup/` | upstream counterpart of `ephemeral-cleanup` |
| policy guidance | `plugins/security-guidance/` | guidance injected at the seam |

Re-confirmed **absent**, unchanged from ADR-0006: a monotonic guard stage in the tool pipeline
(hooks run in registration order, so "must run last" has no guarantee); per-session capability
composition; ordered per-row config patch layers with a composed-tree dump.

**How a change lands, the Nix-declared way.** Not by forking: `phoenix` builds
`hermes-agent+harness-audit` by calling `inputs.hermes-skills/nix/plugin.nix` and overriding the
upstream `minimal` package, so behaviour changes ride the flake input and the source stays
upstream's. A rule needing a seam Hermes lacks is implemented as a plugin here, or recorded as prose
until the seam exists — never as a table that reads like capability.

## Adopted

Every rule below is applied and names its home.

| rule cluster | home |
|---|---|
| CI flake diagnosis: freeze the evidence and classify; reproduce at the smallest topology; a diagnosis-only request is read-only | `deterministic-quality-gates/references/flake-diagnosis.md` |
| verify the world, not the self-report; only a with-key run proves a model-facing path | `deterministic-quality-gates/references/test-reliability.md` |
| an uncovered line is dead code until its author says otherwise | `deterministic-quality-gates/SKILL.md` |
| never repeat a passing check for a commit or push; name a non-zero selected-test count | `verify-and-stop` |
| five failure classes: an inherited composition pin; a control acting on a layer that does not decide; a boundary fake covering only the happy grammar; channel evidence replayable by its author; a during-run property sampled after the run | `postmortem/references/failure-classes.md` |
| session record and lifecycle: additive migrations; settle every attempt; pure projections; cancellable phases commit nothing; retry only when the cause changed; revision revocation; normalized seams; dependency direction; one-shot fail-closed approval; event domain by lifetime; vendoring | `agent-harness-design` |
| the slop list; budget order relocate → condense → raise; a pasted declaration is a registered equivalence block | `writing-for-agents` |
| seven surface/identity rules: additive published names; one read path; outcome normalization; no module-scope await; loader-contract exports; closed key vocabulary; release as one predicate | `defensive-patterns` |
| two more classes: one symbol with two export homes; a lookup branching on the caller's context | `postmortem/references/failure-classes.md` |
| the delegation authority triple; a report states intent, not what landed; ambiguity fails closed | `cavecrew` |
| skill dispatch: size and volatility off the every-turn surface; digest-gated catalogue; exact-name fresh loads; corrupt fails loud while a blip is not a deletion | `writing-for-agents/references/tool-surface.md` |
| exact-name identity; a duplicate name never merges — the nearest layer wins | `skill-library-curation` |
| record hygiene: alternatives mandatory; scoped supersession check; a rejection lives only while tempting; consolidation only if every unique rationale survives | `domain-modeling` |
| review practice: weight a reviewer by the blamed old lines; a gating reviewer runs the protected branch's program, never the reviewed revision; the reviewing system lands no artifact; the whitelist request; verify base and head before reading the diff | `review-council` — a **generated copy** (ADR-0003), so editing it here is silently reverted |

## Refused, each for a cost this repo would pay

- **Bilingual doc pairs, per-file 100% coverage, the Agent Notes lifecycle, Cordis, branded ids** —
  refused in earlier passes; re-encountered, not re-litigated.
- **dsh's snapshot machinery** (recorded-session scenarios per PR, reserved golden trees,
  lane-by-suffix placement): the portable half is the refresh rule we own — a refresh that
  regenerates its expectation certifies the regression. The rest serves a monorepo with a replay
  corpus we do not have.
- **The doc-budget gate** (a manifest of ceiling word counts enforced in CI): there is no manifest
  here to review a ceiling diff against; adopted as judgement in `writing-for-agents`.
- **PTC mode and per-session capability composition**: no scoped-registration primitive exists;
  `execute_code` is the one sandboxed execution mode, and a second would shadow the tool pipeline.
- **CI plumbing specifics** (coverage partitions, concurrency knobs, pool failover): repository- and
  tooling-specific, with no portable rule beyond the check-selection rule above.
- **Host sandbox-escalation retries and the FIXME/TODO taxonomy**: toolchain-specific; "never bypass
  a failing test" is already the reject-flake-masking rule under another name.

## Verification

- Every adopted rule names a file; every refused one names the cost.
- Every applied rule carries a check that can come out false.
- The seam table asserts only what a file listing or a grep in the pinned source confirmed.