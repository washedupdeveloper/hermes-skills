---
name: handoff
description: "Compact a session for another agent to resume."
version: 1.0.0
author: Matt Pocock (mattpocock), adapted by user, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
category: software-development
metadata:
  hermes:
    tags: [handoff, context, session, continuity, summary]
    source: mattpocock/skills@v1.3.1
    related_skills: [to-spec, domain-modeling]
---

# handoff

Write a document that lets a fresh session continue this work without re-reading
the conversation. The reader is another agent with none of your context.

Trigger this **before** context runs low, not after — a handoff written under
compression is missing exactly the detail it exists to preserve.

## What goes in

State, not narrative. A handoff is a resume point, not a report of what happened.

- **Goal** — what we are trying to achieve, in one or two sentences.
- **State** — what is done, what is in progress, what is untouched.
- **Next action** — the single next concrete step, specific enough to start.
- **Open questions** — anything unresolved that blocks or shapes the work.
- **Pointers** — paths to the artifacts that hold the detail.

Add a **suggested skills** section naming which skills the next session should
load, and why.

## Do not duplicate artifacts

If a spec, plan, ADR, issue, commit or diff already carries something, **reference
it by path** instead of restating it. A handoff that paraphrases its own sources
drifts out of sync with them and becomes a second, wrong source of truth.

Reference by absolute path so the next session can open it directly.

## Redact

Strip secrets, tokens, credentials and personal data. A handoff is often written
somewhere less protected than the work itself.

## Where to write it

Default to the OS temp directory (`$TMPDIR`, else `/tmp`; `%TEMP%` on Windows) so
it never lands in the user's repo by accident.

Write into the project instead when the handoff is meant to be durable — a
multi-day effort, or one a teammate will pick up. Ask which, if unclear.

## A handoff is a claim about state, not state

A summary written from memory drifts the moment the work continues, and its reader has
no way to tell a verified assertion from an inferred one. Before acting on an assertion
in a handoff — and before repeating it to the user — check it against live evidence. Two
classes are worth distrusting most:

- **Attributions of cause.** "Another agent is editing the repo concurrently" is an
  inference, and a wrong one is expensive: it sends the reader hunting a process that
  does not exist. Attribute a running process from its recorded metadata rather than the
  shape of its command line — Hermes writes `~/.hermes/logs/process-results/<id>.json`
  carrying `task_id` and `parent_session_id`, which names the session that started it.
  A process's cwd tells you what it is touching; only the metadata tells you whose it is.
- **Anything that can change after the summary was taken.** A count, a file list, a git
  state, a running process. Re-measure it; the number in the summary is a snapshot, not a
  fact about now.

A compaction summary has the same standing, with a sharper edge: it is a paraphrase of
work that may be **your own**, so "I did not do that" is not evidence — the metadata is.
An inherited claim of a concurrent actor is the one most likely to be a misreading of your
own compacted actions.

## Verification

- [ ] A reader with no prior context can state the goal and the next action
- [ ] Assertions about current state re-checked against live evidence, not repeated
- [ ] Every artifact is referenced by path, not paraphrased
- [ ] No secrets, tokens or personal data
- [ ] Suggested skills named, each with a reason
