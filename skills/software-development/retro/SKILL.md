---
name: retro
description: "Retrospect a session and improve the agent's setup."
version: 1.0.0
author: Matt Pocock (mattpocock), adapted by user, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
category: software-development
metadata:
  hermes:
    tags: [retro, retrospective, environment, guardrails, agent-setup]
    source: mattpocock/skills@v1.3.1
    related_skills: [writing-for-agents, systematic-debugging]
---

# retro

Suggest improvements to the **agent's environment** so future runs go better. This
is not a review of the code — it is a review of the setup that produced it.

Read the primary sources for the session: the transcript, the diffs, the commands
that ran and failed. Default to the current session.

## Where to look

**Navigation** — was it hard to find the right file? Are there hidden dependencies
between files? Would a **navigation pointer** help? *Use when* the session spent a
long time locating something.

**Automated checks** — is there a check that would have caught the mistake the agent
made? Read the repo's **own** check command first (its task runner, its CI workflow).
A check that exists but sits unwired or silently broken is the finding — not a
reason to invent a new one. A repo with **no guardrail** (no pre-commit hook, no CI
job running its lint/typecheck/test command) is itself a finding: an unguarded repo
is a standing missed opportunity, not a neutral default.

**Coding standards** — should the reviewer be given a new rule? Should an existing
rule be removed or clarified? Classify the violation first:

- **Mechanical** — a fixed syntactic pattern. Best enforced by a linter, not prose.
- **Judgement** — context-dependent. Belongs in the reviewer's standards.

Prose rules for mechanical violations are the wrong tool: a linter is deterministic,
free on every run, and cannot be argued with.

## The context-pressure asymmetry

All work passes through two stages: **implementation** and **review**.

The implementation agent carries the most **context pressure** — exploration, writing
code, debugging failures. The review agent carries the least: it receives a diff, so
it need not explore or debug.

So **the reviewer imposes coding standards, not the implementer**. Rules pushed into
the implementer's context crowd out the work; the reviewer has room for them.

## Where each kind of guidance belongs

- `AGENTS.md` / `CLAUDE.md` — loaded into **every** turn. Use *incredibly* sparingly:
  navigation pointers to other files, and almost nothing else.
- `CODING_STANDARDS.md` — read at **review** time, not implementation. If it passes
  ~1,000 lines, replace sections with navigation pointers to docs.
- `docs/` — reference material, reached by a pointer from another file. Look for an
  existing doc before writing a new one.
- **Skills** — for reference docs (a skill's description is the pointer) or for
  user-invoked commands. Follow `writing-for-agents`.

Every line added to an always-loaded file costs on every future turn. The bar for
adding one is therefore much higher than for adding a doc behind a pointer.

## Output

A short list of concrete, targeted changes — each naming the file to edit and the
problem it fixes. Prefer three real improvements to a broad critique.

## Verification

- [ ] Each finding cites a specific moment in the session that prompted it
- [ ] Existing checks and docs were read before proposing new ones
- [ ] Mechanical violations routed to a linter, not to prose
- [ ] Anything added to an always-loaded file is justified against its per-turn cost
