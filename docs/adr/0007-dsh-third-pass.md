# The third pass over DeepSeek Harness: the codebase, the record, and what stayed prose

Pass 1 ([ADR-0004](0004-adopt-dsh-harness-rules.md)) took four harness rules and rejected the
framework. Pass 2 ([ADR-0006](0006-dsh-second-pass.md)) took the rule format, the bug and
incident classes, three gate rules and the tool surface. The repository was deleted locally
after each, by design.

Pass 3 asked a different question: **what does the agent's own codebase already seam, and
which rules from the un-mined documents survive translation into it?** Seven scopes were read
in parallel — the six `docs/defensive-patterns/` documents, the four postmortems, the testing
policy with the repo's own `AGENTS.md`/`development.md`, the `.agents/` tree (2,647 files),
the skills and system-prompt subsystems, the capability-seam documents, and the code-review
practice. The candidates, refusals and source paths are the ledger below.

## What the agent codebase actually seams (verified against the pinned source)

The source is local and read-only — the revision `flake.lock` pins:

```sh
nix eval --impure --raw --expr \
  'builtins.toString (builtins.getFlake "~/projects/phoenix").inputs.hermes-agent.outPath'
# /nix/store/dz54zag4246sjz6hk1gp7jn5vnbxqzb8-source
```

There is **no writable clone** of the agent on this machine; the local `~/projects/hermes-agent`
is this skills repository. Verified present in the source:

| seam | where | what it serves |
|---|---|---|
| plugin root | `plugins/<name>/` + `plugins/plugin_loader.py`, loaded via `register(ctx)` | the extension point everything else rides |
| tool-call hooks | `pre_tool_call`, `post_tool_call`, `transform_tool_result` (first-string-wins) | policy, audit, output rewriting |
| model-request hook | `pre_api_request` | the request log the `harness-audit` plugin already writes |
| context/prompt engineering | `plugins/context_engine/` | what the model is shown, as a projection |
| provider seam | `plugins/model-providers/` | a second provider without touching the loop |
| disk hygiene | `plugins/disk-cleanup/` | upstream counterpart of our `ephemeral-cleanup` |
| policy guidance | `plugins/security-guidance/` | guidance injected at the seam |

Re-confirmed **absent** (unchanged from ADR-0006): a monotonic guard stage in the tool
pipeline (hooks run in registration order, so a "must run last" check has no guarantee);
per-session capability composition (`isolate` realms); ordered per-row config patch layers
with a composed-tree dump.

**How a change lands, the Nix-declared way.** Not by forking: `phoenix` already builds
`hermes-agent+harness-audit` by calling `inputs.hermes-skills/nix/plugin.nix` and overriding
the upstream `minimal` package. Agent behavior changes ride the flake input; the source stays
upstream's. A rule needing a seam Hermes lacks is either implemented as a plugin here, or
recorded as prose until the seam exists — never as a table that reads like capability.

## Adopted

| rule cluster | home | state |
|---|---|---|
| CI flake diagnosis: freeze the evidence and classify; reproduce at the smallest topology; a diagnosis-only request is read-only | `deterministic-quality-gates/references/flake-diagnosis.md` | **written**; its `SKILL.md` pointer **pending** (blocked, below) |
| verify the world, not the self-report; only a with-key run proves a model-facing path | `deterministic-quality-gates/references/test-reliability.md` | **pending** (blocked) |
| an uncovered line is dead code until its author says otherwise | `deterministic-quality-gates/SKILL.md` | **pending** (blocked) |
| never repeat a passing check for a commit or push; name a non-zero selected-test count | `verify-and-stop` | **pending** (blocked) |
| five failure classes: an inherited composition pin; a control acting on a layer that does not decide; a boundary fake covering only the happy grammar; channel evidence replayable by its author; a during-run property sampled after the run | `postmortem/references/failure-classes.md` | applied |
| session record and lifecycle: additive migrations; settle every attempt; pure projections; cancellable phases commit nothing; retry only when the cause changed; revision revocation; normalized seams; dependency direction; one-shot fail-closed approval; event domain by lifetime; vendoring | `agent-harness-design` | applied |
| the slop list; budget order relocate -> condense -> raise; a pasted declaration is a registered equivalence block | `writing-for-agents` | applied |
| seven surface/identity rules: additive published names; one read path; outcome normalization; no module-scope await; loader-contract exports; closed key vocabulary; release as one predicate | `defensive-patterns` | applied |
| two more classes: one symbol with two export homes; a lookup branching on the caller's context | `postmortem/references/failure-classes.md` | applied |
| the delegation authority triple; a report states intent, not what landed; ambiguity fails closed | `cavecrew` | applied |
| skill-dispatch mechanics: size and volatility off the every-turn surface; digest-gated catalogue; exact-name fresh loads; corrupt fails loud while a blip is not a deletion | `writing-for-agents/references/tool-surface.md` | applied |
| exact-name identity; a duplicate name never merges — the nearest layer wins | `skill-library-curation` | applied |
| record hygiene: alternatives mandatory; scoped supersession check; a rejection lives only while tempting; consolidation only if every unique rationale survives | `domain-modeling` | applied |
| review practice: weight a reviewer by the blamed old lines; a gating reviewer runs the protected branch's program and never the reviewed revision; the reviewing system lands no artifact; the whitelist request; verify base and head before reading the diff | `review-council` (the deployed council skill is a **generated copy** — ADR-0003 — so editing it here would be silently reverted) | recorded, not applied |

**The full mining batch landed after the first fold of this pass**, so the table above grew
with its second commit: the seven surface/identity rules, the two extra classes, the
delegation triple, the dispatch mechanics, the identity rules and the record hygiene rules
all came from the batch's complete outputs (its transcripts are the delegation record for
`deleg_2b8bc9b7`).

**The four "pending (blocked)" edits** were staged in one script whose approval prompt went
unanswered; they were not re-issued under another tool on purpose. To apply them: add the
`flake-diagnosis.md` pointer beside the existing `test-reliability.md` mention in the gates
skill; insert the uncovered-line rule before `## Procedure`; insert the verify-the-world
section before `## Evidence to report` in `test-reliability.md`; insert the push-check rule
after the first bullet of `## Rules` in `verify-and-stop`.

## Refused, each for a cost this repo would pay

- **Bilingual doc pairs, per-file 100% coverage, the Agent Notes lifecycle, Cordis, branded
  ids** — refused in earlier passes; re-encountered in pass 3, not re-litigated.
- **dsh's snapshot machinery** (recorded-session scenarios required per PR, reserved golden
  trees, lane-by-suffix placement, fixtures as normalization fixed points): the portable half
  is the refresh rule we already own ("a refresh that regenerates the expectation certifies
  the regression"); the rest is tooling for a monorepo with a replay corpus we do not have.
- **The doc-budget gate machinery** (a manifest of ceiling word counts enforced in CI): no CI
  manifest to review a ceiling diff here; adopted as judgement in `writing-for-agents`.
- **PTC mode** (model-authored programs against host bindings) and **per-session capability
  composition**: no scoped-registration primitive exists; `execute_code` is the one sandboxed
  execution mode, and a second would shadow the tool pipeline.
- **CI plumbing specifics** (coverage partitions, gate concurrency knobs, pool failover,
  stack-tool post-sync validation): repository- and tooling-specific; no portable rule beyond
  the check-selection rule adopted above.
- **Host sandbox-escalation retries** and the FIXME/TODO taxonomy: dsh-toolchain-specific;
  "never bypass a failing test" is already our reject-flake-masking rule under another name.

## Verification

- Every adopted rule names a file; every refused one names the cost.
- Every applied rule carries a check that can come out false (the ADR-0006 format rule).
- The seam table asserts only what a file listing or a grep in the pinned source confirmed;
  the two refusals that rest on a missing seam name the mechanism that would have to exist.
- Re-measure after the four blocked edits land:
  `$HERMES_PYTHON skills/software-development/skill-library-curation/scripts/skill-audit.py skills`
  (instrument hash `e5d7979d…`); they are not counted as applied here.