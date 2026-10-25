---
name: reply
description: "Write the final reply: labelled claims, impact first."
version: 0.1.0
author: user, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
category: communication
metadata:
  hermes:
    tags: [reply, reporting, evidence, claims, framing]
    related_skills: [verify-and-stop, writing-for-agents, caveman]
    source: cursor/plugins pstack/skills/poteto-mode (SKILL.md, Writing the reply), adapted
---

# reply

The contract for the answer a task ends with. It governs what the reply asserts, not the voice:
terseness is `caveman`, document craft is `writing-for-agents`, and the proof behind a claim is
`verify-and-stop`. This skill adds the four things a reply must get right.

## When to Use

- Before sending the final answer of any task, especially after a long tool sequence.
- Not for a one-line acknowledgement, and not for the body of a document.

## The four rules

**Every claim carries its evidence or its label in the same sentence.** A claim is measured
(name the command), inferred (name what it follows from), or a guess (say so). A prediction, or
a cause you did not observe, is a guess. Never let a measured number and a recalled impression
share a paragraph without their labels.
*Check:* read each sentence that states a fact. Which of the three is it, and is that on the
page?

**Never hand the human a check you could run.** If a command, a fetch, or a read would settle
it, run it and report the result. Hand over only what needs the human's access, judgment, or
taste, and name which.
*Check:* for each open question in the reply, name the command that would answer it. If one
exists, the question does not belong in the reply.

**No fabricated artifact.** Never cite a link, path, line, or transcript you did not read or
produce this session. A reference you cannot open transfers your uncertainty to the reader as
confidence, which is worse than no reference.
*Check:* every link and path in the reply resolves for you, now.

**Frame impact before implementation.** Name who consumes the work and what changes for them,
then what the next maintainer inherits. Implementation detail follows, never leads.
*Check:* the first two sentences answer "who is this for" and "what is different for them".

## The shape

- One thought per sentence. A sentence that needs a second reading is two sentences.
- No dash and no colon as a mid-sentence connector: end the sentence or use a comma. A colon
  before a list is fine.
- Terse is not permission to drop content. The sections the task needs (what changed, what it
  costs, what was not done, what is open) stay, each in one line.
- A heading carries its fact rather than a label: "Gate green at HEAD" beats "Verification".

## Verification

- [ ] Every factual sentence is labelled measured, inferred, or guess
- [ ] No open question in the reply has a command that would answer it
- [ ] Every link and path was read or produced this session
- [ ] The first two sentences name the consumer and the change for them