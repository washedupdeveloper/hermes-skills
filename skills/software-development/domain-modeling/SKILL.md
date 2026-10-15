---
name: domain-modeling
description: "Sharpen a project's glossary and record its decisions."
version: 1.0.0
author: Matt Pocock (mattpocock), adapted by user, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
category: software-development
metadata:
  hermes:
    tags: [domain-modeling, glossary, adr, vocabulary, terminology]
    source: mattpocock/skills@v1.3.1
    related_skills: [grill-me, to-spec]
---

# domain-modeling

Build and sharpen the project's domain model *as you design*. This is the active
discipline — challenging terms, inventing edge cases, and writing the glossary and
decisions down the moment they crystallise.

Merely **reading** `GLOSSARY.md` for vocabulary is not this skill; any skill can do
that in one line. This skill is for when you are **changing** the model.

## Files

Single-context repo:

```
/
├── GLOSSARY.md
├── docs/adr/0001-<decision>.md
└── src/
```

Multi-context repo — a `GLOSSARY-MAP.md` at the root points at each context's
glossary and ADR directory.

Create files **lazily**: only when there is something to write. No `GLOSSARY.md`
until the first term resolves; no `docs/adr/` until the first ADR is needed.

## During the session

**Challenge against the glossary.** When the user uses a term that conflicts with
the recorded language, say so immediately: "the glossary defines *cancellation* as
X, but you seem to mean Y — which is it?"

**Sharpen fuzzy language.** When a term is vague or overloaded, propose a precise
canonical one: "you're saying *account* — do you mean the Customer or the User?
Those are different things."

**Probe with concrete scenarios.** Invent edge cases that force precision about
where one concept ends and the next begins.

**Cross-reference the code.** When the user states how something works, check
whether the code agrees. Surface the contradiction: "the code cancels whole
Orders, but you just said partial cancellation is possible — which is right?"

**Update `GLOSSARY.md` inline.** The moment a term resolves. Do not batch — capture
as it happens.

`GLOSSARY.md` holds **no implementation detail**. It is a glossary and nothing
else — not a spec, not a scratch pad, not a home for decisions.

## ADRs — offer sparingly

Offer an ADR only when **all three** hold:

1. **Hard to reverse** — changing your mind later costs meaningfully.
2. **Surprising without context** — a future reader will ask "why this way?"
3. **A real trade-off** — genuine alternatives existed and one was chosen for reasons.

Miss any one, skip the ADR. Formats: `references/glossary-format.md`,
`references/adr-format.md`.

## Verification

- [ ] Every term used in the work appears in the glossary with one meaning
- [ ] Contradictions between stated behaviour and code were surfaced, not smoothed over
- [ ] `GLOSSARY.md` contains no implementation detail
- [ ] Each ADR passes all three tests
