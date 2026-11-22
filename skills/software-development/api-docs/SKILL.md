---
name: api-docs
description: "Use when documenting a public API declaration."
version: 1.0.0
author: "Effect (effect, jsdocs), via pingdotgg/t3code, adapted for Hermes"
license: MIT
platforms: [linux, macos, windows]
category: software-development
metadata:
  hermes:
    tags: [documentation, api, jsdoc, docstrings, public-surface]
    source: effect@t3code-vendored (.repos/effect/.agents/skills/jsdocs), pinned via pingdotgg/t3code@e5d757f51b342a5ebc50312790e39a1baca61194
    related_skills: [writing-for-agents, domain-modeling, two-axis-review]
writes: [none]
---

# API documentation

A public declaration's doc block is the contract for a caller who will never read the
implementation. It has one job: say what the caller gets, and what will bite them.

`writing-for-agents` owns prose that agents read and maintain; this skill owns the reference
documentation of a published surface — JSDoc, docstrings, godoc, reference pages.

## When to Use

- Authoring or reviewing documentation for an exported function, type, class or module.
- Refining a module's reference page, or clearing documentation diagnostics.
- A public API has a doc block that restates the signature, narrates the code, or is empty.
- Don't use for: a README, a guide, a design note (`domain-modeling` owns the ADR shape), or
  anything not exported.

## The description

**One paragraph, self-contained, practical.** What the caller gets, in the caller's
language — not how it works inside.

- **Start functions and methods with a present-tense action verb**: *Return*, *Create*,
  *Parse*, *Emit*. Start values with the noun family their neighbours use, so a module's
  list of exports reads as one voice.
- **Do not restate the signature.** The signature is already on screen; repeating it in
  prose costs a line and adds nothing.
- **No implementation narration, no change history.** "First we X then Y" and "this used to
  Z" are session vantage; the caller cannot act on either. The one test for a sentence lives
  in `writing-for-agents`'s `session-vantage` reference.
- **One fact, one home.** A constraint stated on the parameter does not need a second
  sentence in the description — the tool-surface rule, applied to a doc block.

## Optional sections, in this order

Each appears **at most once**, separated from the description and from each other by one
blank line:

| Section | Holds | Must not |
|---|---|---|
| **When to use** | A positive use case distinct from the description — the situation that calls for this rather than its neighbour. | Repeat the description, or list anti-patterns. |
| **Details** | The non-obvious mechanics a caller must know: ordering, units, ownership of a returned value, what happens on empty. | An implementation tour. |
| **Gotchas** | A concrete caveat or failure mode, and what it does. | "Use with care", "not recommended" — those name no failure. |

Then tags (`@param`, `@returns`, `@throws`, `@see`) in whatever order the ecosystem's
checker expects.

## Examples

- **An example is a test nobody runs.** Either make it runnable — a doctest, a snippet test,
  a checked fixture — or mark it explicitly as illustrative. An unchecked example rots into
  a lie faster than prose.
- **Show the smallest call that works**, plus one for the mode a reader would otherwise get
  wrong. Not a tour of every parameter.
- **A runnable example must be executed in the gate** for the surface it documents; if no
  such gate exists, say so rather than implying it is verified.

## Linking, and refining

- **`@see` points at the declaration a caller would confuse this one with**, and at the
  concept it depends on. When an API has a close alternative, auditing those links is part
  of the work — a wrong cross-reference is worse than none.
- **Refining an existing doc preserves verified facts and good examples.** Rewrite what is
  wrong or missing; do not mechanically re-word what a maintainer already checked.
- **`@internal`, non-exported declarations and default exports** are outside a public
  reference. Do not document what is not published, and do not publish what exists only to
  be documented.

## Pitfalls

1. **A description that is a type signature in English.** "Takes a string and returns a
   number" is the signature; the caller needed to know *which* string.
2. **Three Gotchas and no When-to-use.** The section that decides between two similar APIs
   is the one that saves the support ticket.
3. **An example that no longer compiles** because nothing runs it.
4. **A `@see` to a renamed symbol.** Links rot silently; the audit in the gate is the only
   thing that notices.
5. **Documenting the implementation's helper as if it were public.**
6. **Bilingual or duplicated doc files** where one is generated from the other: two homes
   for one fact, and only a generator can keep them equal.

## Verification

- [ ] Every declaration added or changed in the public surface has a description
- [ ] Each description says what the caller gets, not how it works
- [ ] Each optional section appears at most once, in the order above
- [ ] Every example either runs in a gate or is marked illustrative
- [ ] Every Gotcha names a failure mode
- [ ] Every `@see` resolves to a symbol that exists