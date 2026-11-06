---
name: codebase-design
description: "Use when designing module shape or judging a refactor. Deep modules, one vocabulary."
version: 1.0.0
author: "Matt Pocock (mattpocock/skills, codebase-design), adapted for Hermes"
license: MIT
platforms: [linux, macos, windows]
category: software-development
metadata:
  hermes:
    tags: [architecture, modules, seams, refactor, vocabulary]
    source: mattpocock/skills@main (adapted from the published summary and glossary)
    related_skills: [improve-codebase-architecture, domain-modeling, request-refactor-plan]
---

# Codebase Design

Design **deep modules**: a lot of behaviour behind a small interface, placed at a clean seam, and
testable through that interface. Use this language whenever code is designed or restructured — the
aim is leverage for callers, locality for maintainers, and testability for everyone.

## The vocabulary, used exactly

Do not substitute "component", "service", "API" or "boundary". Consistent language is the point; a
synonym is a different concept wearing the same clothes.

| Term | Meaning | Avoid |
|---|---|---|
| **Module** | anything with an interface and an implementation. Deliberately scale-agnostic: a function, a class, a package, or a slice across tiers. | unit, component, service |
| **Interface** | everything a caller must know to use it correctly: the signature, **plus** invariants, ordering constraints, error modes, required configuration, and performance characteristics. | API, signature (too narrow) |
| **Implementation** | the body of code inside a module. | — |
| **Depth** | leverage at the interface: how much behaviour a caller (or a test) can exercise per unit of interface they must learn. **Deep** = much behaviour, small interface. **Shallow** = the interface is nearly as complex as the implementation. | — |
| **Seam** | (Michael Feathers) a place where behaviour can be altered without editing in that place; the location at which an interface lives. Where the seam goes is its own decision, separate from what sits behind it. | boundary (overloaded with DDD's bounded context) |
| **Adapter** | a concrete thing that satisfies an interface at a seam. Describes a **role**, not a substance. | — |

## Principles

1. **The deletion test.** Delete the module and inline it at every call site. If the code gets
   *shorter and no less clear*, the module was shallow — the interface was a tax. If it gets
   *longer or the call sites get complicated*, the module earned its keep.
2. **The interface is the test surface.** If a behaviour cannot be exercised through the interface,
   either the interface is wrong or the behaviour does not belong inside. Reaching past an interface
   to test is a design smell, not a testing convenience.
3. **One adapter is a hypothetical seam; two are a real one.** A seam with a single implementation is
   a guess about a second one. Do not pay for the indirection until the second adapter exists — but
   do keep the *seam* in mind when choosing where the interface sits.
4. **Depth is not size.** A 600-line module with a three-function interface is deep; a 60-line module
   whose caller must know nine flags and two orderings is shallow.
5. **Locality beats convenience.** Prefer the design where a change to one behaviour touches one
   file, even if it is a slightly longer file. Reading is cheaper than chasing.

## How to apply it

**When designing:** name the module, write its interface (including the invariants and error modes),
then ask what a caller must learn to use it. If the answer is more than a page, split the *behaviour*
or narrow the interface — not the file.

**When reviewing a refactor:** for each module changed, run the deletion test out loud. State the
depth in one sentence: "a caller gets X behaviour for Y interface." If you cannot, the module has no
stated purpose — which is a defect, not a style preference.

**When judging scope:** a module whose only job is forwarding calls is a cost. A module whose name
you cannot say without listing its parts is not a module yet.

## Pitfalls

1. **Naming things "service"** and thereby assuming it needs a network boundary.
2. **Confusing depth with length.** Counting lines says nothing about leverage.
3. **Adding an adapter for a seam with one implementation**, then testing the adapter instead of the
   interface.
4. **Letting the interface leak**: exposing internals "just for the test" makes the test the only
   consumer of a private contract, and the contract will drift.
5. **Vocabulary drift.** One document saying "module" and another saying "component" for the same
   thing means the next reader has to learn both.

## Verification

- [ ] Every module named in the change has a one-sentence interface description
- [ ] The deletion test was applied to each, not assumed
- [ ] No new adapter exists without a second implementation
- [ ] Behaviour is exercised through the interface, not around it
- [ ] No synonym ("component", "service", "API", "boundary") slipped into the design notes