---
name: grill-with-docs
description: "Use when grilling a repo plan and writing decisions."
version: 1.0.0
author: "Matt Pocock (mattpocock/skills) + Hermes Agent"
license: MIT
platforms: [linux, macos, windows]
category: software-development
metadata:
  hermes:
    tags: [planning, interview, glossary, adr, domain-modeling]
    source: mattpocock/skills@main
    related_skills: [grilling, domain-modeling, grill-me]
writes: [none]
---

# grill-with-docs

A grilling session pointed at a codebase, which **writes the vocabulary and the
hard decisions down while it runs**.

1. Load `grilling` (`skill_view(name="grilling")`) and run its rounds.
2. Load `domain-modeling` (`skill_view(name="domain-modeling")`) and use it for
   the vocabulary work: challenge terms against `GLOSSARY.md`, sharpen overloaded
   words, probe with concrete scenarios, and cross-check what the user says
   against the code.
3. Read the repository for facts before asking: the frontier is cheaper to answer
   when the agent has already looked.

## What gets written

- `GLOSSARY.md` — the moment a term resolves, never batched. No implementation
  detail; it is a glossary, not a spec.
- `docs/adr/NNNN-<decision>.md` — only when the decision is hard to reverse,
  surprising without context, **and** a real trade-off. Miss one, skip the ADR.
- Nothing else. No code during the session; no document the interview did not
  earn.

## Done

The frontier is empty, every crystallised term is in the glossary, the ADRs that
met the bar are written, and the user has confirmed the shared understanding.
Then implementation may begin.

| what is in front of you | use |
|---|---|
| an idea or decision, no repo | `grill-me` |
| a repo and a change you can settle in one session | **grill-with-docs** (this skill) |
| a repo, but only the interview, no docs | load `grilling` directly |

`grill-me` and `grill-with-docs` run the same interview; only the state differs.