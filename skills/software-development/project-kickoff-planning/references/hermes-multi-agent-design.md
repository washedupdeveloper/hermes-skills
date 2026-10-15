# Designing Multi-Agent Orchestration Natively in Hermes

Companion depth for `project-kickoff-planning` when the system being planned is a Hermes-native
multi-agent pipeline. Facts below were verified against the Hermes source tree and docs; re-check
against `https://hermes-agent.nousresearch.com/docs/llms.txt` before relying on a detail, since the
product moves. The bundled `hermes-agent` skill is the general hub; this file is the design layer.

## The four orchestration primitives — pick by trigger, not by habit

| Need | Primitive |
|---|---|
| Iterate ONE objective in this chat until a definition of done | `/goal` (+ `/subgoal`) |
| Re-run a prompt on a cadence inside a session | `/loop` |
| Short reasoning fan-out whose result returns to the parent | `delegate_task` |
| Work that must survive restarts / cross profile / human-in-the-loop / audit | Kanban |
| Unattended wall-clock schedule | cron |

## `/goal` vs `/loop` — the decision that matters

- **`/goal` is judge-driven and supports deterministic quality gates that run BEFORE the judge.**
  Completion-contract fields: `outcome, verification, constraints, boundaries, stop_when`.
  `/goal gate add <cmd>` runs a shell command each turn; a failing gate short-circuits the judge and
  its bounded output tail becomes the continuation prompt. Budget: `goals.max_turns` (default 20).
  Judge model: `auxiliary.goal_judge.{provider,model,max_tokens,timeout}`.
- **`/loop` is timer-driven (or self-paced).** Syntax `/loop [interval] <prompt> [--times N]
  [--until <cond>]`. Its `--until` judge reuses the same `goal_judge` auxiliary task and is
  **fail-open** (any judge error → continue). `loops.max_ticks` (default 100) *pauses*, it does not
  stop. Self-paced backoff is 1→2→4→8→15m.
- **Rule:** for "iterate until a SCORE threshold is met", prefer `/goal` + a completion contract
  whose `verification` encodes the score + a deterministic gate. `/loop --until` is the literal
  cadence-driven equivalent but inherits the fail-open judge. They coexist: an active `/goal`
  defers `/loop` ticks, so a `/loop 10m /recap` heartbeat can run alongside a goal.

## `delegate_task` contract (the parts that bite)

- Input per task: `goal` (required), `context` (children know nothing of the conversation — pass
  everything), `output_schema` (JSON Schema, appended to the child as an OUTPUT CONTRACT),
  `images` (max 8).
- Output per task: `status`, `summary`, `exit_reason`, tokens, cost, and — when a schema is given —
  `schema_valid` plus `schema_errors` on failure. A schema miss does NOT fail the run; the child's
  raw text is still the `summary`. Validation does exactly one bounded correction retry.
- **`output_schema` is validated as JSON ONLY** (`json.loads`). YAML payloads fail. Design the
  canonical record as JSON Schema, have children return JSON, serialize to YAML yourself.
- `delegation.max_concurrent_children` default **10**, no ceiling; an oversized batch is refused,
  not truncated. `max_spawn_depth` default **1** (flat). Roles are depth-derived, not model-chosen;
  the `role` arg is legacy/ignored.
- **`delegation.oneshot_max_children` default 2 — a SEPARATE, cumulative per-session budget** for
  finite one-shot runs (`hermes chat -q`). A batch larger than it is refused with a **tool error**,
  so a well-behaved agent falls back to doing the work inline and may describe the run as if the
  children had executed. Set it to `0` (unlimited) for any orchestrator that fans out wider than 2;
  interactive sessions are not subject to it. This is the cap that silently breaks a 5-specialist
  batch, and it is NOT the same knob as `max_concurrent_children`.
- **Children are NOT durable execution.** A process restart records the attempt `unknown` and never
  resumes; `/stop` or session close kills the whole tree. Background *completion delivery* is
  at-least-once but that is not durable execution. Use cron or kanban for restart-safe work.
- Leaf children cannot call `delegate_task`, `clarify`, `memory`, `send_message`, or `cronjob`.

## Bot Mode (persistent specialist personas)

- A Bot **is** a profile: `~/.hermes/profiles/<name>/` with its own config, `.env`, `SOUL.md`,
  skills, memory, sessions. `hermes -p <name> chat` opens the same agent from the CLI.
- Bot-to-bot messaging is `message_agent(target, message)` — a **plain string, fire-and-forget**
  (`status: queued` means durably admitted, not delivered). There is **no typed payload field**;
  structured content must be embedded (e.g. a fenced YAML block) and parsed by the receiver. For a
  machine-checkable protocol, prefer a **file bus** (messages on disk, git-versioned) over chat.
- Enabling the protocol needs `agent.bot_mode_protocol: true`, a session titled exactly `Bot Chat`,
  and a profile carrying `ui_meta: {hermes-bots: {}}`. Headless installs must set these by hand.

## Kanban (the durable multi-worker path)

- Durable SQLite board; the dispatcher runs inside the gateway and spawns the assigned profile as a
  worker with the `kanban_*` toolset. Every handoff is a durable row.
- `hermes kanban swarm "<root>" --workers a,b,c --verifier v --synthesizer s` atomically builds a
  root + N parallel workers + a verifier (gated on all workers) + a synthesizer (gated on the
  verifier). `--goal` cards run the same Ralph engine inside the worker for iterate-until-done.
- Kanban is single-host by design; cross-machine needs `hermes peer` / the api server.

## Composing a scored, iterative review-style pipeline

1. **Orchestrator** = a session running `/goal` with a completion contract whose `verification` is
   the score predicate, plus `/goal gate add scripts/<score>.py` as the deterministic gate.
2. **Specialists** = ONE `delegate_task` batch, one task per specialist, each with a uniform JSON
   `output_schema`.
3. **Scoring** = a *hybrid* per-category score: `score = β·deterministic + (1−β)·rubric`, where
   **β is MEASURED** (`tools_ran_and_parsed / tools_expected`), never declared. A missing toolchain
   drives β toward 0 — the run continues on judgement alone and must say so. Combine within a
   category with a **weighted geometric mean** so one failing tool is not diluted by passing ones;
   caps/gates are multiplicative and absolute, never averaged. Write the result to a file; the gate
   checks that file and its output drives the next iteration.
4. **Durability** = swap the in-session loop for a Kanban swarm when it must survive restarts.

### Anti-gaming (learned from the literature, apply by default)

- **A lone score threshold is trivially gameable, and iterating agents will game it** (self-play
  has driven a judge's pass rate to 0.94 while true accuracy stayed 0.20). Hold the rubric/ground
  truth OUT of the iterating agents' context; prefer execution-based checks (tests/build) they
  cannot fake; keep a signal-to-noise term in the score so "flag everything" cannot raise it; cap
  findings per iteration; detect oscillation (score regression/flip → stop and escalate).
- **Aggregate with an evidence matrix, not voting.** Dedupe findings; tri-state
  `AGREE | DISAGREE | DID_NOT_EXAMINE` where **silence is never agreement**; union the verified
  facts (no voting); a blind judge only consolidates, never averages findings away.
- **Terminate on a composed condition**, not one number: no new verified finding for k rounds AND
  score ≥ threshold AND no unresolved P0/P1 AND diminishing returns AND within round/token caps AND
  score stable across repeated judge runs. Convergence is typically ~3–5 rounds.
- Keep SNR / usefulness first-class, and never use BLEU/ROUGE-style reference matching for review
  quality.

## Running the loop (operational pitfalls)

- **If the fan-out is refused, report the error and stop.** Never run the specialists' passes inline
  and present the result as a council — that is one model's opinion repeated, not independent
  corroboration, and it must not be described as if the children had executed.
- **A long orchestrator run dies when the agent's turn closes.** A `terminal(background=True)`
  process is killed at turn end (`exit_code -15`, `termination_source: agent_close`) unless started
  with `persist_on_release`. Waiting in-turn is clamped, so a run longer than the wait window cannot
  be fully awaited in one turn — persist it, or poll across turns.
- **Never assert a tool ran.** When the deterministic toolchain is absent, label the work
  static-only and mark unmeasured claims `AMBIGUOUS`; do not claim a command's output you do not have.
- **Record deviations in the result.** A blocked fan-out, a missing gate script, an uncalibrated
  threshold — state them; an omitted deviation reads as a clean run.

## Hard limits to design around (do not fight them)

1. `/goal` and `/loop` are session-bound; one of each per session.
2. `delegate_task` children are non-durable.
3. `output_schema` validates JSON only.
4. Leaf children cannot re-delegate (nested orchestration needs `max_spawn_depth ≥ 2`).
5. The goal / `--until` judge is fail-open; the deterministic gate + turn budget are the real
   backstops.
6. Bot `message_agent` is string-based and fire-and-forget.
7. Cron cannot recursively schedule by default; kanban is single-host.
