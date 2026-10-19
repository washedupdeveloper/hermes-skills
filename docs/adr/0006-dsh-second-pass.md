# The second pass over DeepSeek Harness: bug classes, incident classes, request logging

The first pass ([ADR-0004](0004-adopt-dsh-harness-rules.md)) took four harness rules and
rejected the framework. Reading the same repository again, with the tree's own review and
incident documents in scope, produced three things worth keeping and a longer list worth
refusing. The repository was then deleted locally: a clone of a public repository is not a
source of truth, and a snapshot of it left in `~/projects` would become one.

## The transferable artifact is the rule format, not the rules

Every rule in dsh's `docs/defensive-patterns/` carries four parts: what must hold, the
defect that shipped or nearly shipped, the condition a reviewer judges, and the boundary
past which the rule does not apply. A rule with the first and not the third and fourth
cannot be reviewed — it gets applied to everything and then ignored, which is how a rule
set becomes decoration.

That format is now the first section of the `defensive-patterns` skill, and the rules that
filled it are stated language-agnostic. The instances in dsh are TypeScript; the classes —
timing carrying correctness, one value standing for three facts, teardown requesting
quiescence instead of reaching it, a spawned process inheriting the ambient environment —
are not.

## Adopted

- **`defensive-patterns`** — the five habits and the bug classes, each with its check and
  boundary. New skill.
- **`postmortem`** — the incident discipline: a timeline from the log rather than from
  memory, one section per independent mechanism, "why the tests missed it" as a mandatory
  section, and a guardrail that was watched failing. Its `references/failure-classes.md`
  carries the six classes dsh's postmortems actually found, because a class recurs through
  a different file while an instance does not.
- **Three gate rules**, into the skills that already own their subjects rather than a new
  one: mock the boundary and not the pipeline, a refresh that regenerates the expectation
  certifies the regression, and a skipped test is unmeasured. The last two come from
  incidents where a suite was green throughout.
- **The tool-surface rules** (`agent-experience` in dsh), as
  `writing-for-agents/references/tool-surface.md`: what a model is given on every turn
  versus on demand, put each parameter's rules on the parameter, say each fact once, bound
  the output and mark the truncation.
- **A logged model request.** The first pass implemented "model-visible means logged" for
  tool calls only. dsh also records a request header per call, and that is the measurement
  every context argument needs: the plugin now writes one line per request with the counts,
  the input-token size, and a digest of the system prompt — no prompt text, no message
  bodies. It is read with `harness_audit(action="requests")`.

## Refused, each for a cost this repo would pay

- **Spill** (a global bounded-output rewrite). Hermes already bounds each tool with its own
  continuation contract — a `read_file` offset, a saved file for a truncated command,
  head+tail for code execution. A blanket transform would break those contracts to solve a
  problem they already solve. The rule survives as a rule; the mechanism does not.
- **Bilingual documentation pairs.** dsh carries a `.zh.md` and an `.i18n.yaml` beside
  nearly every document, and its own review skill admits a green pairing hash proves
  nothing about translation quality. Two files per fact is the drift ADR-0003 records.
- **Per-file 100% coverage.** Unchanged from ADR-0004, and the incidents now make the
  argument better: 100% line coverage was green throughout a bridge that could not open a
  single session.
- **The Agent Notes lifecycle** (proposed → implemented → rejected → archived, with a
  supersession check per new note). This repo has `docs/adr/`, which is the same object at
  the size the repo is. Two decision records would be two homes.
- **`docs/subsystems/` type catalogues and branded ids at every boundary.** Costs that buy
  discipline across 342 packages and buy nothing across Markdown files.

## What the second pass changed in the first pass's own work

The tool pipeline now has a stage table, because the interesting dsh rule is not which
stages exist but that a concern belongs to exactly one: a policy that must not be reordered
is a guard, an around-dispatch concern wraps, and the result is rewritten once. Hermes has
no guard stage — hooks run in registration order — and the skill says so instead of
describing a mechanism that is not there.
