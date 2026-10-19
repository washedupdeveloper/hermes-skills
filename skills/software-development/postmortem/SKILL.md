---
name: postmortem
description: "Use after an incident: write the postmortem."
version: 1.0.0
author: user, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
category: software-development
metadata:
  hermes:
    tags: [incident, postmortem, root-cause, guardrails, evidence]
    related_skills: [systematic-debugging, defensive-patterns, verify-and-stop, writing-for-agents]
    source: DeepSeek Harness (deepseek-ai/deepseek-harness) docs/postmortem, distilled
---

# postmortem

A postmortem is the record of a defect that shipped, and the reason it can never ship
again. Its product is **guardrails**, not prose: a postmortem with no new check is a story.

Write one when a defect reached a user, when a near-miss was caught by luck rather than by
a gate, or when the fix took more than one attempt. Do **not** write one for a defect found
in review before merge — that is a missing test, and it belongs in the diff.

Generic failure classes worth recognising while you investigate:
`references/failure-classes.md`.

## The timeline comes from the log, not from memory

Reconstruct the sequence from durable evidence and cite it: the session id and the event
indices, the commit and the line, the request id, the CI job, the timestamp. A timeline
written from recollection is a summary of what you believed, and the belief is the thing
under investigation.

The payoff is real: an agent's postmortem of its own failed session found that the first
three actions were individually plausible and shared no acceptance target — a fact only
visible in the persisted event log, not in the summary the agent had already written about
itself. If the incident was an agent session, the log is `harness_audit(action="recent")`
plus the session transcript.

## Sections, and what each must carry

- **Status** — resolved, mitigated, or open. A mitigation is not a resolution.
- **Executive summary** — the defect, its cost, and what now prevents it, in three
  sentences. Written last.
- **Impact** — who or what was affected, and what was *not* (no data loss, no bypass, no
  unconfined execution). The "not" half is what keeps the severity honest.
- **Timeline** — evidence-cited, in order, including the wrong turns. A timeline that
  omits the misdiagnosis teaches the next reader nothing about the diagnosis.
- **Root cause** — one section per independent mechanism. Two bugs behind one error string
  is the normal case, not the exception: isolate the first fix and re-run before concluding
  the second does not exist.
- **Why the tests missed it** — mandatory. If 100% line coverage was green throughout, that
  sentence belongs here, with the reason: coverage proves lines *ran*, never that the
  feature works the way it ships.
- **Guardrails added** — each one with the command that fails on the original defect, and
  the note that you watched it fail. A guard nobody has seen go red is indistinguishable
  from one that cannot.
- **Lessons** — the rule, not the story. Each lesson is a sentence the next engineer can
  act on.

## A fix is not a guardrail

Three different objects, and the postmortem needs the third:

| object | what it proves |
|---|---|
| the fix | the defect is gone in this tree |
| the regression test | the defect is gone and would be noticed if it returned |
| the guardrail | the *class* cannot return unnoticed — a gate, a rule with a home, a check in CI |

Prove the middle one by reintroducing the defect and watching the check fail, then
restoring it. A guardrail with no negative control is prose with a filename.

## Trust the trace, not the theory

Instrument before you theorise. A plausible mechanism that explains the symptom is worth
nothing until the trace shows it — and in the case this section is drawn from, the elegant
explanation was real but was the *second* bug; the first was a one-line mistake a
ten-minute instrumentation found after hours of reasoning.

The corollary for the write-up: state which hypotheses you falsified, and how. That is the
part of the document that helps the next investigation, and it is the part a tidy narrative
deletes.

## Blameless means naming the process, not the person

"Nobody wrote a test that loads the plugin the way the product loads it" is blameless and
actionable. "The author forgot" is neither. The process gap is the only thing a guardrail
can close.

The same rule applies to a document that already exists: when a postmortem's rule is
contradicted by the code, the finding is a design discussion, not a rule to quietly delete.

## Freeze the record

A superseded postmortem stays visible and labelled. Never edit an archived one to match the
current code — the record of what was believed at the time is the useful artifact, and a
postmortem edited to agree with today's tree erases the evidence that the tree changed.

## Verification

- [ ] The timeline cites ids, commits or line numbers, not recollection
- [ ] Every root cause has its own section; independent mechanisms are not merged
- [ ] "Why the tests missed it" exists and names the coverage claim that was green
- [ ] Every guardrail names the command that fails on the original defect
- [ ] Each guardrail was watched failing before it was trusted
- [ ] The lessons are rules, not narration; no lesson names a person
- [ ] Impact states what was *not* affected, with evidence
