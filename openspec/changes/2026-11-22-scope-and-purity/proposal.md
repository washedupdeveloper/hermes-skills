# Proposal

## Why

The library states one home per fact, a validated frontmatter and a readable
layout — but it does not state a skill's **scope**. Two skills can answer the
same question and nothing notices; a rule can be restated in nine skills (the
container-runtime policy was), and commands can assume a path the reader never
chose. A skill can also start a daemon or install a package without telling
anyone. The result is a library that is organized but not bounded.

## What Changes

- A skill declares `writes` from symbolic roots only, in two tiers: the project
  (`$PROJECT`, `$ARTIFACTS`, `$SCRATCH`) and, with an announcement, outside it
  (`$HERMES_HOME`, `$SYSTEM`).
- A skill declares `side_effects` from a closed vocabulary and opens a
  `**Heads-up.**` paragraph whenever it writes outside the project or spawns
  something (systemd, container, port, cron, background process, credential,
  global package).
- Every domain carries a `CATEGORY.md` stating its question and a "not here" list
  that must name real skills.
- A trigger phrase has exactly one owner across the catalog.
- One container runtime policy: podman is the runtime, docker is a marked
  fallback, and an unmarked `docker` invocation fails the gate.
- A renamed skill stays resolvable through `library/aliases.json`.

## Capabilities

### New Capabilities

None. This extends `skill-library`.

### Modified Capabilities

- `skill-library`: adds scope, persistence and runtime requirements to the
  existing five.

## Impact

`library/contract.json` (v3), `scripts/scope.py`, `scripts/validate.py`,
`tests/unit/test_validate.py`, every `SKILL.md`'s frontmatter, `skills/*/CATEGORY.md`,
`docs/runtime.md`, `docs/milestone-v3.md`. No skill loses a behaviour; the
frontmatter gains two fields and nine skills lose a duplicated paragraph.