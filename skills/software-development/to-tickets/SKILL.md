---
name: to-tickets
description: "Split a plan into tracer-bullet tickets with blockers."
version: 1.0.0
author: Matt Pocock (mattpocock), adapted by user, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
category: software-development
metadata:
  hermes:
    tags: [planning, tickets, vertical-slices, decomposition, blocking]
    source: mattpocock/skills@v1.3.1
    related_skills: [to-spec, wayfinder, handoff]
---

# to-tickets

Break a plan, spec or conversation into **tickets**: tracer-bullet vertical slices,
each declaring what **blocks** it.

Work from what is already in context. If given a path or issue reference, read it
first.

## Slice rules

- Each slice cuts a narrow but **complete** path through every layer (schema, API,
  logic, tests) — vertical, never a horizontal slice of one layer.
- A completed slice is **demoable or verifiable on its own**.
- Each slice is sized to fit in **one fresh context window**.
- Do any **prefactoring first** — make the change easy, then make the easy change.

Give each ticket its **blocking edges**: the tickets that must finish before it can
start. A ticket with no blockers can start immediately.

## Wide refactors are the exception

A **wide refactor** is one mechanical change (rename a column, retype a shared
symbol) whose blast radius fans across the whole codebase — no single edit lands
green, so vertical slicing cannot work. Sequence it as **expand–contract**:

1. **Expand** — add the new form beside the old, so nothing breaks.
2. **Migrate** — move call sites over in batches sized by blast radius (per package,
   per directory), each batch blocked by the expand. CI stays green batch to batch
   because the old form still exists.
3. **Contract** — delete the old form once no caller remains, blocked by every
   migrate batch.

If even the batches cannot stay green, the blast radius is too wide to land
incrementally — say so and propose a different sequencing rather than pretending.

## Use the project's language

Ticket titles and bodies use the vocabulary from `GLOSSARY.md` and respect any ADRs
in the area (see `domain-modeling`). A ticket written in a private dialect costs the
next reader the whole glossary anyway.

## Where tickets go

**Default to one markdown file per ticket** under `docs/tickets/`, with blocking
edges written as text. This needs no tooling and works anywhere.

If the repo uses GitHub Issues, publish there instead (the bundled `github` skill
covers the mechanics) and express blocking as real links.

State which backend you used in your reply — the reader needs to know where to look.

## Verification

- [ ] Every slice is vertical, demoable alone, and fits one context window
- [ ] Every ticket names its blockers, and the graph has no cycles
- [ ] Wide refactors are sequenced expand–contract, not forced into slices
- [ ] Vocabulary matches `GLOSSARY.md`; no ADR is contradicted
