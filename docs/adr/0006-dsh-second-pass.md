# What a second reading of DeepSeek Harness added, and what it refused

**Decision.** The transferable artifact was the *rule format*, not the rules: what must
hold, the defect that shipped, the condition a reviewer judges, and the boundary past
which the rule stops applying. A rule with only the first cannot be reviewed, and a rule
set that cannot be reviewed becomes decoration. The rules themselves now live in the
skills that own their subjects (`defensive-patterns`, `postmortem`, `agent-harness-design`).

**Why.** Each adopted rule names a defect this repo had already met; each refusal names a
cost it would pay at this size.

**Rejected.** *Spill* (a blanket bounded-output rewrite) — Hermes already bounds each tool
with its own continuation contract, and a global transform would break them. *Bilingual
pairs* and *per-file coverage* — as in ADR-0004. *A second decision-record lifecycle* —
`docs/adr/` is that object here.

**Consequence.** A rule needing a seam Hermes lacks is a plugin in this repo, or prose
until the seam exists — never a table that reads like capability.
