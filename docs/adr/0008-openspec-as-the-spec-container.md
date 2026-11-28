# OpenSpec is the spec container, per repository

**Decision.** A repository may carry `openspec/`. When it does, every behaviour change
starts as a change directory and merges through `openspec archive`; `AGENTS.md` states the
rule, and the repo's CI runs `validate --all --strict`.

**Why.** A brief written in a conversation dies with the conversation. Four skills could
produce a plan but none left a durable artifact a later session could be held to.

**Evidence.** One task, two isolated agents, the same five requirements: prose (278 tokens)
against a validated change (874 tokens). Both passed an eight-point probe; the spec arm
missed the `--dry-run` early return that the prose arm validated, and the review's two
high findings named exactly that branch. `archive` refused a stale delta by name and
merged it after refresh. Small pilot — the delta is the signal, not the absolute score.

**Cost accepted.** ~874 tokens and four files per change; an external CLI; `validate
--strict` checks shape, not coverage — an independent review is still the check on whether
the spec is complete.
