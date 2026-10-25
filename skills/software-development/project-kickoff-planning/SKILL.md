---
name: project-kickoff-planning
description: "Plan a new project from scratch: research and milestones."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
category: software-development
metadata:
  hermes:
    tags: [planning, kickoff, greenfield, research, milestones, interview, scaffold]
---

# Project Kickoff Planning

Take a user from "I want to set up a proper system for X" to a researched, interviewed, committed
milestone plan in a real project directory — before any build code is written.

## When to Use

Load this when the user asks to plan/scope/set up a new system or project from scratch, asks for a
"milestone plan", or says "research this and interview me about the decisions". Not for a single
feature or bug inside an existing codebase — this is the greenfield kickoff.

Also load it when an **existing** repo is asked what it is missing "to reach the milestone":
that question is a kickoff in reverse, and when no milestone exists anywhere it cannot be
answered at all until one is written. See "When the milestone does not exist yet".

## Procedure

1. **Recon before planning — in one batched turn.** Answer with tools what tools can answer:
   does the target dir exist, what toolchain is present (`git --version`, `python --version`,
   `node --version`), where does the product's own config/state live, and is there an installed
   skill covering the domain (`skills_list`). Never ask the user for a fact a command can produce.

2. **Fan out parallel research sub-agents** with `delegate_task`, one task per *independent*
   research question. Each task must be self-contained (children know nothing of the conversation):
   - a full `goal` + full `context` (constraints, environment, what the parent is building);
   - an instruction to write the FULL report to a scratch file and return a compact summary + path;
   - an `output_schema` (JSON ONLY — see pitfalls) with required fields like
     `summary`, `report_path`, and the finding lists you will actually read.
   Dispatch returns immediately; results re-enter between turns. While they run, do the work that
   does NOT depend on them (scaffold, interview), then end your turn so results can be delivered.
   Read the full reports before synthesising — summaries alone are not enough to plan from.

3. **Interview the user in ONE batched `clarify` call.** Put every open decision into a single
   `clarify` with up to 5 questions; the recommended option FIRST (the UI labels it). This user
   *wants* to be interviewed on the vital technical decisions — do not hand back an unconsulted
   plan. Never chain clarify calls one question at a time.

4. **Handle skipped questions explicitly.** Users skip items. If a *pivotal* question is skipped,
   re-ask it in a follow-up batch rather than silently guessing. For lower-stakes ones, state your
   default and move on so the user can veto. Record every default in the decisions log under
   "open / defaulted".

5. **Scaffold the repo.** `mkdir` under the user's projects dir, `git init`, and commit the
   scaffold before writing docs. Add `.gitattributes` for cross-platform hygiene:
   `* text=auto eol=lf`, `*.sh text eol=lf`, `*.py text eol=lf`, `*.bat text eol=crlf`,
   `*.ps1 text eol=crlf`. Add a `.gitignore`.

6. **Write the doc set** (see below), committing each phase with a descriptive message.

7. **Reconcile research → plan.** Every major plan decision traces to either a research finding or
   a user answer; keep a traceability table so the plan is auditable and not vibes.

## When the milestone does not exist yet (an existing repo)

"What is this missing, to reach the milestone?" has no referent until the target is written
down, and guessing one produces a plan nobody agreed to.

1. **Prove the absence first, with tools.** Grep the repo for `milestone`/`roadmap`, search
   past sessions, and read the repo's work list. A list of review findings is not a plan, and
   a documented target is a different task from an absent one -- the difference decides
   whether you interview or implement.
2. **Interview in batched rounds.** One `clarify` call per round, up to 5 questions, one
   decision per question, **your recommendation first** (the UI labels it), choices as
   pickable rows and never enumerated inside the question text. Two or three rounds is normal
   for a fleet- or product-scale target; stop when what is left is a hardware-time or
   later fact rather than a design choice.
3. **Take the decisions the user delegates.** "Undecided -- choose whatever coheres" is a
   decision handed to you: choose, state the choice and its reason in one line, and proceed.
   Never hand it back as an open question.
4. **Verify every mechanism you are about to name, in the pinned source, before writing it
   down.** A plan naming a seam that does not exist is worse than a vague plan: read the
   pinned upstream (the store path from the lock file) for option names, module paths,
   service interfaces, and whether an upstream helper is even usable at that call site -- and
   say which one you read.
5. **Record deferrals as decisions, not open flags.** "At hardware time", "not chosen", "out
   of scope for this milestone", each with its reason. An unresolved flag is not a plan.

### The doc it produces

Name it for the repo's own conventions (`docs/milestone.md` where a docs tree exists) and make
it the plan, not a second work list:

- **The target**, stated as decisions with the constraints each imposes ("X is the transport",
  "Y is the always-on peer") and what each one forecloses -- not a wish list.
- **What is already in place**, so the gap is sized correctly and the plan does not read as a
  rewrite.
- **The gaps in dependency order**, each naming the file, option or input that has to change,
  and marked when it needs hardware in hand.
- **Deferred on purpose**, with the reason.
- **What "reached" means** -- an observable end state (the gate builds every machine; a deploy
  changed something remotely), never a restatement of the goal.
- **Point at the existing work list by number** (`recommendations.md` item N) rather than
  copying it: one home per fact (`writing-for-agents`), or the two drift apart.

Then register the doc where the repo indexes its documentation (a README map row is the usual
place) and run the repo's own gate before committing -- a docs tree with a lint hook will fail
on mechanical things a `write_file` call does not satisfy.

## Doc set (write all of these)

- **DECISIONS.md** — numbered *locked* choices (each with the choice and a one-clause why), a
  *resolved-by-research* table, and a *still-open* table where each row carries a working default.
- **ARCHITECTURE.md** — the layers, the data flow, the key technical reconciliations, the
  integration points, the target repo tree, and the hard limits inherited from the platform.
- **MILESTONES.md** — `M0..Mn`, each with **Goal / Research inputs / Deliverables / Acceptance
  criteria / Size / Depends**. Plus a dependency graph, the research→decision traceability table,
  and the open-decisions list. See `templates/milestone-plan.md`.
- **RESEARCH.md** — index of the reports, the findings that *changed the design*, and sources.
- **README.md** — status (planned/planned-not-built), what it is, hard requirements, doc index,
  target layout.

Acceptance criteria are the point of a milestone: every one must be checkable by a command or an
observable artifact ("two runs produce byte-identical output", "CI matrix green on all three OSes"),
never a restatement of the goal.

## Pitfalls

- **`delegate_task`'s `output_schema` validates JSON only** (the validator calls `json.loads`). A
  YAML return fails validation. Have children return JSON; if the human-facing artifact must be
  YAML, serialize JSON→YAML yourself in the parent.
- **A batch over `delegation.max_concurrent_children` (default 10) is refused, not truncated.**
  Size the fan-out to the cap and split larger research into waves.
- **`write_file` refuses to overwrite a file this session already wrote** unless the task holds a
  current *full* read; a paginated `read_file` may still not satisfy the guard. To replace such a
  file, `rm` it first and then `write_file`, or use `patch` for a targeted edit. (Bit twice while
  updating docs that had been written earlier in the same session.)
- **Don't let the plan restate the codebase map or tool parameter lists** — those belong in the
  repo's `AGENTS.md` and the tool schemas. The plan carries workflow, decisions, and pitfalls.
- **Cross-platform requirements are constraints, not preferences.** When the user says it must run
  on Windows + Unix + WSL2, that drives path handling (pass forward-slash native paths like
  `C:/...` to native tools; MSYS `/c/...` works only for bash builtins), line endings, and how
  subprocesses are invoked.
- **Don't build before the plan is agreed.** The deliverable of a kickoff is the committed plan
  and scaffold, not a half-built system.

## Working preferences (standing)

- Research thoroughly *before* planning; the user grants parallel research sub-agents freely.
- Interview the user on the vital decisions — batched questions with recommended options first.
- Deliver a milestone plan with checkable acceptance criteria, a decisions log, and the project
  scaffolded in a real directory under the user's projects folder.
- Treat stated hard requirements (platform coverage, stack constraints) as binding.

## Support files

- `references/hermes-multi-agent-design.md` — how to compose multi-agent orchestration natively in
  Hermes (the four primitives, `/goal` vs `/loop`, `delegate_task` contract, Bot Mode, kanban
  swarm, hard limits). Load it when the project being planned is a Hermes-native agent system.
- When the plan includes building the Bots themselves, the `hermes-bot-authoring` skill carries the
  hands-on mechanics: profile creation, per-profile config, capability restriction, persona schema.
- `templates/milestone-plan.md` — the milestone-plan skeleton to copy and fill.
