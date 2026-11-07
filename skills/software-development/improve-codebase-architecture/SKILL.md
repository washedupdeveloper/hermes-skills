---
name: improve-codebase-architecture
description: "Use to find shallow modules and propose deep refactors."
version: 1.0.0
author: "Matt Pocock (mattpocock/skills, improve-codebase-architecture), adapted for Hermes"
license: MIT
platforms: [linux, macos, windows]
category: software-development
metadata:
  hermes:
    tags: [architecture, refactor, deep-modules, design-alternatives, rfc]
    source: mattpocock/skills@main
    related_skills: [codebase-design, zoom-out, request-refactor-plan]
---

# Improve Codebase Architecture

Surface architectural friction and propose **deepening** refactors: turning shallow modules into
deep ones. The aim is testability and AI-navigability, not tidiness.

Speak in `codebase-design`'s vocabulary — module, interface, depth, seam, adapter — and apply its
principles (the deletion test; the interface is the test surface; one adapter is hypothetical, two
are real). Do not drift into "component", "service", "API" or "boundary".

## 1. Scope before scanning

YAGNI. Deepening pays off where the code changes often, because the payoff is in future edits. So let
the history choose the target:

- If the user named a direction (a module, a subsystem, a pain point), take it and skip the inference.
- Otherwise walk a good stretch of `git log --oneline` and let the recurring files pull your attention
  first. If the changes are scattered with no hot spot, widen the net.
- Read the domain glossary (`GLOSSARY.md`) and any ADRs in the area first. An ADR already settled is
  not yours to re-litigate.

## 2. Find the friction

For each hot module, name the specific symptom — not "it's messy":

| symptom | what it looks like | the deepening move |
|---|---|---|
| **shallow module** | the interface has as many decisions as the body has statements; callers pass config through | move the decisions inside; take a narrower input |
| **leaked seam** | callers reach past the interface (private fields, internal files, raw dicts) | make the interface the only door, or move the seam |
| **test-only interface** | a method exists solely so a test can reach inside | make the behaviour reachable through the real interface, or delete the behaviour |
| **adapter with one implementation** | an indirection justified by a second implementation that does not exist | inline it; keep the seam in mind, not the adapter |
| **change ripple** | one behaviour change touches N files | pull the behaviour into one module behind one interface |

## 3. Propose, do not perform

Write the proposal as an RFC, one per opportunity:

```markdown
## Opportunity: <module>
Symptom: <one of the above, with file:line>
Deletion test: <what happens if the module is inlined — does the code get shorter?>
Proposal: <the interface after the change, including invariants and error modes>
Cost: <what moves, what breaks, what must be re-tested>
Risk: <what could get worse; what the fallback is>
```

**Two designs minimum.** For a non-trivial opportunity, sketch the interface two ways that differ
materially — not "with and without a flag", but e.g. a minimal interface that does one thing well vs a
caller-shaped interface that absorbs the common sequence. Compare them on depth, not on taste. If a
second design cannot be stated, the first was not a design — it was the code, restated.

Where the tooling allows, dispatch the two sketches as parallel subagents and compare their answers;
where it does not, write both yourself before choosing.

## 4. What makes a proposal weak

- It names the module but not its interface.
- The "after" is bigger than the "before" with no stated leverage.
- It cannot be tested through the interface.
- It proposes a new abstraction for a seam with one implementation.
- Its justification is readability, with no example of a change that becomes cheaper.

## Verification

- [ ] The target was chosen from history, or named by the user
- [ ] The glossary and ADRs were read first
- [ ] Every symptom names a file:line and one of the five categories
- [ ] The deletion test was applied, not asserted
- [ ] Two materially different designs exist for each non-trivial proposal
- [ ] Each proposal states cost, risk and fallback