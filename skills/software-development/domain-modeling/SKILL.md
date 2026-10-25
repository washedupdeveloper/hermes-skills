---
name: domain-modeling
description: "Use when sharpening a glossary or an ADR set."
version: 1.1.0
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

## Maintaining the ADR set

An ADR is a **decision record**. Its `Action Items` are the temporary part, and the failure
mode is a checklist nobody closes — the record then reads as open work forever, and the next
session cannot tell a live decision from an abandoned one.

**Audit by running, not reading.** For each unchecked item, find the command that would prove
it and run it. A completed item keeps the command and its result, so the record needs no
rerun; a bare `[x]` is a claim with nothing behind it.

**Work that is not a decision leaves.** "Add the second architecture when that machine
exists" is a task with a trigger, not a trade-off: move it to the project's work list and
leave a pointer. An ADR that grows a to-do list is two documents in one, and the to-do list
is the half that rots.

**An item that cannot converge is a design defect.** A chore like "re-check this value when
it changes" usually means a fact was recorded with the wrong half-life. Replace the chore
with the decision — record what is stable, drop what is not — instead of performing it
forever.

**A fully-ticked checklist is not a retirement signal -- it is the part that finished.**
"Every box is checked, so can it go?" answers itself once you ask what the record still
carries: the decision in force, the options rejected and why, and the consequences. Only the
action items ever reach done; the rest describes the system as it is, and it stays until
something replaces it. A record whose decisions have left the tree is the one that goes,
whatever its boxes say.

**One fact, one home -- and confirm the target carries it before deleting a copy** (the rule
and its failure mode are `writing-for-agents`'s). Applied to a record and its site: leave the
site the half it cannot borrow -- that the absence is deliberate, and the surprising part --
and the record keeps the reasoning and the measurement. The two copies must agree first; the
second is often the stale one, and deleting the wrong one loses the fact.

**Retiring an ADR takes two empty greps**: no file in the tree points at it
(`grep -rn 'adr/000N'` — code comments and docs cite these files), and none of its decisions
is still in force. Either one present and the record stays; the checklist was temporary, the
decision is not.

**A superseded ADR is the one to keep longest.** Its decision was reversed, so what survives
in it is the trap that reversed it. That is the only place the trap is written down, and
deleting the record invites the same change again.

## Record hygiene

- **Alternatives considered is mandatory.** A decision recorded without what it beat invites
  re-litigation at the next session.
- **Every new record triggers a scoped supersession check** — the existing records it could
  supersede, found by the decision it states rather than by its title.
- **A rejection survives only while the idea stays tempting.** Proposals are rejected, never
  archived; when the idea stops tempting, the refusal goes with the record.
- **Supersession consolidates only if every unique rationale, alternative, consequence and
  verification survives** the merge. Otherwise the superseded record is frozen as history and
  never cited as authority.

## Verification

- [ ] Every term used in the work appears in the glossary with one meaning
- [ ] Contradictions between stated behaviour and code were surfaced, not smoothed over
- [ ] `GLOSSARY.md` contains no implementation detail
- [ ] Each ADR passes all three tests
