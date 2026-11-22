---
name: grill-me
description: "Use when the user says 'grill me' outside a repo."
version: 3.0.0
author: "Matt Pocock (mattpocock/skills) + Hermes Agent"
license: MIT
platforms: [linux, macos, windows]
category: software-development
metadata:
  hermes:
    tags: [planning, interview, alignment, stateless]
    source: mattpocock/skills@main
    related_skills: [grilling, grill-with-docs]
writes: [none]
---

# grill-me

The **stateless** entry point: a loose idea, a decision, a piece of writing, a
product question — anything that is not a codebase change.

1. Load `grilling` (`skill_view(name="grilling")`) and follow it.
2. Write no files and leave no workspace behind. The interview is the output.
3. If the session produces decisions the user wants kept, offer `to-spec` or
   `handoff` — do not invent a document mid-interview.

Pick the right entry point:

| what is in front of you | use |
|---|---|
| an idea or decision, no repo | **grill-me** (this skill) |
| a repo and a change you can settle in one session | `grill-with-docs` |
| a repo, but only the interview, no docs | load `grilling` directly |

`grill-me` and `grill-with-docs` run the same interview; only the state differs.