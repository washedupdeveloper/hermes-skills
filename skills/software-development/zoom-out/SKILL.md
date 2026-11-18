---
name: zoom-out
description: "Use when lost in code: map modules, callers, one layer."
version: 1.0.0
author: "Matt Pocock (mattpocock/skills, zoom-out), adapted for Hermes"
license: MIT
platforms: [linux, macos, windows]
category: software-development
metadata:
  hermes:
    tags: [navigation, architecture, exploration, map]
    source: mattpocock/skills@main
    related_skills: [codebase-design, domain-modeling]
---

# Zoom Out

When you do not know an area of code well enough to change it safely, **go up one layer of
abstraction** and produce a map — modules, their callers, and the vocabulary the project already uses
for them.

This is a five-minute move, not a research project. It exists because the alternative — reading files
until something clicks — produces a local understanding that cannot be written down, and therefore
cannot be checked.

## When to use

- You are about to change code you have not read before.
- A fix keeps moving between files and you cannot say why.
- You can name the function but not what depends on it.
- The user asked for an overview, or said "I don't know this part".

**Not** for: a file you already understand; a one-line change in familiar code; replacing reading
with a map when the detail is exactly what you need.

## The move

1. **Name the entry point.** The command, endpoint, event or test that reaches this code.
2. **Walk outward, one layer at a time.** Direct callers, then their callers, until you reach the
   edge (CLI, HTTP handler, scheduled job, test).
3. **Group by module**, not by file. A module is anything with an interface and an implementation —
   see `codebase-design`.
4. **Use the project's own words.** If the domain glossary says "claim" and "verdict", do not write
   "record" and "result". If there is no glossary, the words you choose here are a proposal for one.
5. **Say what is not on the map.** Known callers you did not trace, dynamic dispatch you cannot see,
   plugins. An unqualified map reads as complete.

## Output

A short map, in this shape:

```text
entry:    <tool> gate <run-dir>            (cli.py:gate)
  → score_reviews.evaluate(run_dir)         (the verdict)
      → apply_proofs(blocking, adjudication) (proofs.json)
      → claim_cap(records)                   (severity caps)
  → certification(satisfied, blocking, ...)  (the four words)
```

One line per module, with the file that holds the interface — not every function. Then two sentences:
what the map does **not** cover, and what you now believe the safe place to change is.

## Pitfalls

1. **Mapping everything.** A map of the whole repository is a symptom, not a deliverable. Map the path
   you will change.
2. **File trees instead of call graphs.** `src/` contains files; the question is who calls whom.
3. **Inventing vocabulary.** Two names for one thing costs the next reader twice.
4. **Treating the map as proof.** It records what you believe; the tests still decide.
5. **Stopping at the first caller.** One layer up is often the interesting one.

## Verification

- [ ] The entry point is named
- [ ] Every module on the map has its interface location
- [ ] The project's own vocabulary is used, or a deliberate new one is proposed
- [ ] What is not covered is stated
- [ ] The safe place to change is named