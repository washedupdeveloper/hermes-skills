---
name: agent-harness-design
description: "Use when designing harness seams, tools, registries."
version: 1.0.1
author: user, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
category: software-development
metadata:
  hermes:
    tags: [harness, architecture, plugins, seams, registries, composition, agent-loop]
    related_skills: [deterministic-quality-gates, writing-for-agents, hermes-agent]
---

# agent-harness-design

Rules for the machinery an agent runs on: tools, skills, plugins, registries, and the
composition that decides which of them exist in one session. Every rule below states the
defect it prevents and the check that can fail, so a violation is a red gate rather than
a matter of taste.

The rules were read out of DeepSeek Harness (`dsh`), an all-plugin harness built on
Cordis, as a **design document rather than a dependency**. What was adopted, and what was
rejected with its reason, is recorded in `docs/adr/0004-adopt-dsh-harness-rules.md`.

## When to Use

- Adding a tool, a skill source, a plugin, or an extension point to a harness.
- A capability must be swappable: local vs remote, host vs sandbox, one provider vs another.
- Composition is edited by copying a config file per machine.
- Something reaches the model that the session log cannot reconstruct.
- Designing or reviewing a registry (skills, tools, providers, presets).

Not for using a finished harness — that is `hermes-agent`. Not for scoring one — that is
`deterministic-quality-gates`.

## Rules

### A registration is an effect

Every contribution — a tool, a prompt section, an adapter, a listener, a provider — is
installed through one API that returns a disposer, and teardown unwinds it in reverse
order. Prevents: a reload that leaves a second copy of a listener registered, and a
teardown that keeps a tool the next session can still call.

Check: register the same contribution twice, dispose once, assert one remains; dispose
again, assert zero.

### A seam has three roles, never one

A **seam** is a swappable capability: a service definition (the interface), a service
provider (one implementation), and a consumer (usually a model-facing tool). One role
alone is not a seam, and adding a capability means designing all three. Prevents a
provider nobody calls, and a consumer that imports a concrete implementation instead of
the seam — which is what makes the next provider a fork.

Check: delete the shipped provider and mount a second one; the consumer works unchanged.

### New behavior goes on a documented extension point

A harness keeps one table of goal → mechanism (add a provider, add a capability, intercept
a request, persist state). New behavior attaches there; changing the loop itself is the
exception that must update the map. Prevents the loop becoming the only place behavior can
live, which turns every later change into a loop change.

Check: every change names the extension point it used, or names the map entry it added.

### Model-visible means logged

Anything that reaches a model request must be reconstructable from the session log, and a
new model-visible input requires a durable record. Prevents prompt content that exists
only in memory, so no transcript can reproduce the run and no bug is replayable.

Check: rebuild the request from the log alone and compare it with what was sent.

### Composition is layered, and every row is patchable by id

A profile is ordered layers applied to an empty entry list: bundles, then the user's patch,
then per-invocation overlays. A patch replaces one row's whole config by id, or inserts
rows. The composed tree is dumpable. Prevents the fork-a-config-file-per-machine pattern,
which diverges silently and cannot be diffed.

Check: dump the composed tree, replace one row by id, dump again — one row changed.

### Registries layer per scope; rank decides inside a layer

A registry keeps a global layer plus one layer per scope (agent, preset, project). A read
merges the layers: the nearest layer wins a duplicate name outright, and a rank
(project > custom > user > bundled) breaks ties only inside one layer. Prevents a project
file silently shadowing a user file with no stated rule, and makes the winner explainable.

Check: the same name in two layers loads the nearer one; the same name twice in one layer
loads the lower rank and reports the loser.

### Discovery reports complete or incomplete, never absence

A registry read carries whether discovery finished. Incomplete is not empty: keep the
last-good view, never cache an incomplete catalog. The reasoning and the three-state
model are in `deterministic-quality-gates`; this rule is the same one applied to
catalogs.

### The catalog carries identity; the body loads on demand

The model-visible catalog carries name and description only — no bodies, no paths, no
routing hints. A body is read at load time and never cached, so a body-only edit changes
the next load without rewriting history. Prevents an always-loaded prompt that pays for
every skill body on every turn, and a stale body after an edit.

Check: edit one body only; the next load returns the new text and the catalog is
unchanged.

### Invocation is two independent switches

Whether the model may load a contribution and whether a human may invoke it are separate
flags, declared in metadata, defaulting to true. Prevents a human runbook offered to the
model as a task, and a machine-only procedure listed to a person as a command.

Check: a model-only entry is absent from the human command list, and the reverse.

### One home per fact

Each fact lives in the tier whose job it is; everywhere else links to it. The tiers: standing
orders an agent needs every session · the architecture map · the per-subsystem reference ·
decision records · the rules review enforces · the per-package contract. Prevents the same
rule written twice and drifting once.

### A decision is a record with a lifecycle

A decision record has a path-encoded state — proposed, implemented, rejected — a date, and
the alternatives it gave up. Once shipped it is rewritten to present tense and kept true to
what shipped; superseding creates a new record rather than editing one into a different
decision; an archived record is frozen and never cited as current authority.

### Defaulting is explicit at the boundary

The defaulting step is a named `resolve(request): Spec` in the owning implementation, never
a hidden `?? default` inside the operation that consumes it. Prevents a default that cannot
be found by reading the call site, and a spec that differs between two callers.

### Tunables are config, not constants

Deployment-varying choices are validated config fields changeable from the composition
file; a `DEFAULT_*` constant or a test hook is not configurability. Protocol constants,
external specs and security invariants stay fixed. Prevents a value that only its author
can change.

### Misconfiguration fails loud

Fail at load when the check is self-contained, otherwise at the earliest resolvable point.
Never silently skip a missing referent. Prevents a plugin that appears mounted and
contributes nothing.

### Wire each invariant into a gate, and prove the gate rejects an invalid case

A mechanically checkable invariant belongs in the executed top-level gate, in the cheapest
tier that can decide it. Every acceptance rule carries a **negative control**: a
deliberately invalid case driven through the same predicate, so a rule that silently
matches everything is caught. A rule with no failing input is not yet a gate.

Check: for each new rule, one assertion that it rejects the invalid case and one that it
accepts the valid one — at the boundary, not merely inside it.

## Mapping: dsh concept to Hermes mechanism

| dsh | Hermes today |
|---|---|
| Cordis context, `ctx.<key>` services | tools, plugins, and MCP servers registered per session |
| Registrations as effects | toolset and plugin load/unload per profile |
| Profile = ordered bundles + patches | profile + `config.yaml` + `external_dirs`, changed with `hermes config set` |
| `--dump-config` | the composed config and the skill index (`skills_list`) |
| Skill registry, rank precedence | `$HERMES_HOME/skills`, `skills.external_dirs`, `.bundled_manifest` |
| Skill catalog + `skill` tool | skill index in the system prompt + `skill_view` |
| Two invocation switches (model vs human) | **not equivalent** — Hermes has no user/model switch; it gates at offer time on relevance only: `requires_toolsets`, `requires_tools`, `fallback_for_toolsets`, `environments`, `session_platforms`, and `required_environment_variables` |
| Agent Notes (proposed/implemented/rejected) | `docs/adr/` in this repo; commit messages elsewhere |
| `verify-*` scripts in one `doc-sync` gate | `nix flake check`, split into an eval tier and a run tier |
| Recorded-session snapshots | session transcripts in `state.db` |

## What not to copy

- **The framework, not just the rules.** Cordis is a TypeScript dependency; adopting it to
  get these properties would rebuild Hermes around a second runtime.
- **Per-file 100% coverage on every source file.** It buys the all-plugin discipline at a
  cost this repo does not carry; the eval tier plus a negative control covers the rules
  here.
- **Bilingual documentation pairs.** Two files per fact is a second home for the fact, and
  the pairing gate is the only thing keeping them equal.
- **Branded ids on every boundary crossing.** Worth it at dsh's package count, overhead at
  a skill tree's.

## Verification

- [ ] Every new contribution returns a disposer, and a teardown test proves it is called
- [ ] The change names the extension point it used, or the map entry it added
- [ ] Every model-visible input is reconstructable from the log
- [ ] Composition is changed by a patch keyed to a row id, not by copying a file
- [ ] A registry winner is explainable by layer first, rank second
- [ ] Each new invariant is in the top-level gate, with a negative control beside it
- [ ] Each new fact has one home, and the other tiers link to it
