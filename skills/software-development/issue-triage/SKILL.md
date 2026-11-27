---
name: issue-triage
description: "Use when triaging an issue into an agent-ready brief."
version: 1.0.0
author: "Matt Pocock (mattpocock/skills, triage), adapted for Hermes"
license: MIT
platforms: [linux, macos, windows]
category: software-development
metadata:
  hermes:
    tags: [triage, issues, pull-requests, briefs, backlog]
    source: mattpocock/skills@5863806dd4e15c63174bee4e7515a4256792ecfa (engineering/triage)
    related_skills: [github, grilling, domain-modeling, to-tickets]
writes: [none]
side_effects: [none]
scope_answers: ["how an issue becomes an agent-ready brief"]
scope_triggers: [triage an issue, issue to brief]
scope_out: [splitting a plan into tickets (to-tickets), the pr body (pr-description)]
---

# Issue triage

Move an issue — or an external pull request, which is an issue with code attached — through
a small state machine, and leave behind the artifact that makes the next step cheap: a
**brief** an agent or a human can act on without re-deriving the context.

The bundled `github` skill owns the mechanics (`gh issue view`, `gh issue edit`, comments,
labels). This skill owns the decision and the artifact.

## The state machine

| Role | Values |
|---|---|
| **Category** (exactly one) | `bug` — something is broken; `enhancement` — new behaviour or an improvement |
| **State** (exactly one) | `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix` |

Transitions: an unlabelled item enters `needs-triage`. From there it goes to `needs-info`,
`ready-for-agent`, `ready-for-human` or `wontfix`. `needs-info` returns to `needs-triage`
when the reporter answers. The owner can override at any time.

- **Conflicting state labels are a stop.** Two states on one item means somebody already
  disagreed; ask before touching it.
- **The label strings are the repository's.** `gh label list` is the source; map the five
  states onto what exists once, and keep that mapping where the next session will find it.

For a PR, the states read against the code: `ready-for-agent` means a brief is attached and
an agent should take the next step on the diff; `ready-for-human` means it is ready to merge.

## When to Use

- "What needs triage?", "what is ready for an agent?", "look at #42".
- "Move #42 to ready-for-agent" — an explicit override; apply it, confirm, skip the grilling.
- A bug report or feature request needs a decision and an owner.
- Don't use for: writing the implementation tickets once the work is agreed (`to-tickets`),
  or a change that is already in review (`two-axis-review`).

## 1. Show what needs attention

Query the tracker and present three buckets, oldest first:

1. **Unlabelled** — never triaged.
2. **`needs-triage`** — evaluation in progress.
3. **`needs-info` with reporter activity since the last triage note** — needs re-evaluation.

One line per item with a count per bucket, and `[PR]` or `[issue]` on each line when both
are in scope. Let the owner choose. Discovery surfaces only *external* PRs; a named PR is
always triaged regardless of its author.

## 2. Gather context before recommending

- Read the whole item: body, comments, labels, author, dates; for a PR, the diff.
- **Parse any prior triage notes first**, so a resolved question is not asked twice.
- Read the domain glossary and the ADRs in the area the change touches.
- **Redundancy check**: search the code for an existing implementation of the requested
  behaviour *by domain concept*, not by the request's wording. Report where you looked. A
  hit is `wontfix`, already implemented.
- **Prior-rejection check**: read the out-of-scope record (below) for a request that
  resembles this one.

## 3. Verify the claim, then recommend

Verify **before** grilling, because a confirmed claim is what makes a brief strong:

- **A bug**: reproduce it from the reporter's steps. Report the code path, or that it did
  not reproduce, or that the detail is insufficient — which is itself a strong `needs-info`.
- **A PR**: check it out and run what it claims. Report what actually ran.

Then state the category, the recommended state, the reasoning, and the relevant codebase
summary. Wait for direction — the owner's judgement outranks a correct analysis.

## 4. Grill only if the request needs shape

When the request is under-specified, run `grilling` a round of questions at a time, and use
`domain-modeling` to sharpen the terms as decisions land. Capture what was settled; it goes
into the brief, not into the conversation.

## 5. Apply the outcome

**Say what you are about to do — label, comment, close — then do it.**

- `ready-for-agent` → post an agent brief (below).
- `ready-for-human` → the same structure, plus one line saying why it cannot be delegated:
  a judgement call, external access, a design decision, manual testing.
- `needs-info` → post triage notes (below).
- `wontfix` → close, and the comment depends on why:
  - **Already implemented** — point at where it lives. Do **not** write to the out-of-scope
    record; that record is for *rejected* requests, not built ones.
  - **Rejected bug** — a polite explanation, then close.
  - **Rejected enhancement** — write the out-of-scope entry, link it from the closing
    comment, then close.
- `needs-triage` → apply the label; comment only if there is partial progress worth keeping.

## The agent brief

```markdown
## Goal

<one sentence: the behaviour that will be true when this is done>

## Context

- <file:line, symbol, or doc that owns the area>
- <the glossary term this uses>
- <the prior decision or ADR that constrains it>

## Acceptance

- [ ] <a condition a test can decide>
- [ ] <another>

## Out of scope

<what this deliberately does not do, and where the follow-up would live>
```

Rules: pointers instead of pasted code; acceptance conditions that can come out false; the
project's vocabulary, not a new one. A brief without acceptance criteria is a wish with a
label on it.

## The needs-info notes

```markdown
## Triage notes

**Established so far:**
- <what was settled, including anything resolved while grilling>

**What we still need (@reporter):**
- <a specific, answerable question>
```

Questions must be specific and actionable. "Please provide more information" is not a
question, and the answers already gathered must survive in the comment.

## The out-of-scope record

One file per rejected request, under a directory the repository already uses for decisions —
`.out-of-scope/`, or `docs/decisions/` where that exists: the request in one line, the reason
it was rejected, and the date. The closing comment links to it. The record exists so the same
request is not re-litigated — a rejection nobody wrote down is a rejection that comes back.

## Pitfalls

1. **Triaging by title.** The body and the comments are where the actual request is.
2. **Grilling before verifying.** Half the questions answer themselves once the claim is
   reproduced or refuted.
3. **"Already implemented" without a pointer.** It reads as "go away" and will be re-filed.
4. **Writing to the out-of-scope record for something that shipped.** The record then
   contradicts the code.
5. **Re-asking a resolved question** because the earlier triage note was not read.
6. **Closing a rejected enhancement with no record.** The next reporter files it again.
7. **Overriding the owner's state choice** because the analysis disagreed.

## Verification

- [ ] Exactly one category role and one state role, or a conflict reported as a stop
- [ ] Prior triage notes were read, and no resolved question was re-asked
- [ ] The redundancy check reports where it looked, not only its conclusion
- [ ] A bug was reproduced, or the report says it was not and why
- [ ] The brief's acceptance conditions can each come out false
- [ ] Every mutation to the tracker was stated before it was made