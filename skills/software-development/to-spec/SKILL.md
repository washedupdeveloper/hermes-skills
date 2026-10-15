---
name: to-spec
description: "Turn a conversation into a written spec."
version: 1.0.0
author: Matt Pocock (mattpocock), adapted by user, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
category: software-development
metadata:
  hermes:
    tags: [spec, planning, synthesis, seams, requirements]
    source: mattpocock/skills@v1.3.1
    related_skills: [to-tickets, domain-modeling, grill-me]
---

# to-spec

Synthesize the current conversation and codebase understanding into a spec. **Do
not interview the user** — that is `grill-me`'s job. This skill writes down what is
already agreed.

## Process

1. **Explore the repo** if you have not, so the spec reflects the real current
   state. Use the project's `GLOSSARY.md` vocabulary throughout and respect ADRs in
   the area (see `domain-modeling`).

2. **Sketch the test seams.** A seam is a boundary you can test through. Prefer
   existing seams to new ones, and the **highest** seam available — fewer seams is
   better, and the ideal number is one. If a new seam is needed, propose it at the
   highest point you can.

   Confirm the seams with the user before writing; a wrong seam invalidates the
   implementation decisions that hang off it.

3. **Write the spec**, then save it. Default to `docs/specs/<slug>.md`; if the repo
   uses GitHub Issues, publish there instead and say so.

## Spec template

```markdown
## Problem Statement
The problem, from the user's perspective.

## Solution
The solution, from the user's perspective.

## User Stories
A long numbered list. Each: "As an <actor>, I want <feature>, so that <benefit>".
Cover every aspect; this is the completeness check.

## Implementation Decisions
Modules to build or modify, their interfaces, schema changes, API contracts,
architectural decisions, technical clarifications.

Do NOT include file paths or code snippets — they go stale fast.

Exception: if a prototype produced a snippet that encodes a decision more
precisely than prose can (a state machine, reducer, schema, type shape), inline
just the decision-rich part and note it came from a prototype.

## Testing Decisions
The seams chosen and why, and what each one covers.

## Out of Scope
What this deliberately does not do.
```

## Verification

- [ ] No interview happened — this synthesizes existing agreement
- [ ] Seams were confirmed with the user before the decisions were written
- [ ] User stories are exhaustive enough to reveal a gap
- [ ] No file paths or code snippets in Implementation Decisions
- [ ] Vocabulary matches `GLOSSARY.md`; no ADR contradicted
