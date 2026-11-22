---
name: hermes-kanban-orchestration
description: "Use when building a durable multi-agent kanban pipeline."
version: 1.0.0
author: Storm, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
category: autonomous-ai-agents
targets: [hermes]
metadata:
  hermes:
    tags: [hermes, kanban, swarm, durable, orchestration, multi-agent, dispatcher]
    related_skills: [hermes-wsl-backend, nix-flake-packaging, hermes-bot-authoring]
writes: [none]
---

# hermes-kanban-orchestration

Building a multi-agent pipeline as a **durable kanban graph** instead of a set of
spawned subprocesses. A spawned child is process-local: kill the parent, reboot, or
end the turn that started it, and the work is gone. A board card is re-claimable, so
the same pipeline survives and resumes.

The bundled `hermes-agent` skill summarises the board's verbs. This skill is the
authoring side: how to build a graph whose cards carry real instructions, and how to
prove the thing actually advances.

## When to Use

- Work that must outlive the process that started it — a long review, a batch, a
  multi-stage pipeline.
- A pipeline currently implemented as parallel subprocesses that dies partway.
- "The board is stuck" / a card sitting `ready` with nothing claiming it.
- Deciding whether a job belongs on the board or in a spawned child.

## Rules (always on)

**The board is the durability, not the process.** Nothing about a card requires a
particular parent to stay alive: the dispatcher reclaims a stale claim and re-runs the
card. So "survives a restart" means **the round completes**, not that no work is
done twice. State that to the user up front — a worker that genuinely dies is re-claimed,
and re-claiming repeats its work.

**A board does not advance itself. Run a dispatcher, and make the dispatcher durable.**
The board is durable *storage*, not a scheduler. A graph that is correct, complete and
sitting `ready` will not move a single card until something ticks the dispatcher, so
"durable" is only true once that ticker is itself installed, enabled and restarted on
failure. A dispatcher started by hand — or by the shell that created the graph — is the
same process-local arrangement the board was chosen to replace. Install it as a service
(`Restart=on-failure`, wanted by the default target, with linger so it outlives logout),
and verify it is `active` **and** `enabled`, not merely running.

**A dispatcher restart does not disturb work already in flight.** A spawned worker
detaches from the dispatcher's process group — its parent becomes the service manager,
not the dispatcher — so restarting the dispatcher leaves a running worker alone. That is
why a dispatcher upgrade mid-run is safe, and why the tick log reads `reclaimed=0` after
one. The re-claim path exists for a worker that actually died (reboot, OOM, an explicit
kill), not for a dispatcher restart; do not conflate the two when saying what a restart
costs.

**A card's body is its instruction, and the convenient CLI cannot set it.**
`kanban swarm --worker` takes `PROFILE:TITLE[:SKILL]` and the parser sets
`body = title`, so the worker's entire instruction is its own title; the verifier and
synthesizer bodies are hardcoded by the tool. Any graph whose instructions matter must
be built card by card with `kanban create --body-file --parent`, where every body is
yours.

**Never restate the pipeline's own prompt in a card body.** A body that repeats a
prompt, a schema or a scoring rule is a second definition of the work, free to drift
from the first. Have the card invoke the one implementation (a CLI verb that reads the
prompt from its single source), and keep the body to that command plus what to report.

**A verifier card must run the check, not judge.** A model asked to "verify the score"
will produce a plausible number; the deterministic check produces the actual one. Give
the verifier the exact command, tell it to report the result verbatim, and forbid it
from computing or adjusting a value itself. This is the same principle as a scoring
gate owning its own normalization.

**Resolve any command you emit from the artifact's own location.** A card body is
executed later, by the dispatcher, in *its* environment — not in your shell. Never emit
a bare `mycli subcommand` assuming `mycli` is on that `PATH`; emit the resolved form
(`nix run <root>#app`, or the running interpreter plus the script's path) and quote the
paths. See `nix-flake-packaging` for the deeper treatment.

**Put an idempotency key on the root card.** Re-running the same job at the same
revision is the same job, so a reclaimed or repeated dispatch must resume rather than
fork a duplicate graph.

**Ask what a tick would do before concluding the board is stuck.** This is a
preview, not an action:

```bash
hermes kanban dispatch --dry-run    # what a tick would reclaim/promote/spawn
hermes kanban dispatch              # run exactly one tick now
hermes kanban list                  # ready / todo / running / done per card
```

A card whose parents are unfinished sits `todo` and is *correctly* waiting. A `ready`
card nothing ever claims means no dispatcher is running.

**Find out which server hosts the dispatcher before assuming one is running.** The
dispatcher is hosted by the **messaging gateway**; a host running only the desktop
backend has none, and its board will sit idle indefinitely while looking healthy. The
standalone daemon is the fallback where no gateway exists — it refuses to start while it
believes a gateway owns dispatch, so it needs its explicit override flag, and the service
unit should carry the reason. If both ever run they race for the same claims: run one.
See `templates/kanban-dispatcher.service` for the unit shape.

## Procedure

1. **Fix the graph.** For a fan-out-then-collate shape: one **root** (sets the round's
goals, acts as the shared blackboard), N **workers** (one per unit of parallel work),
one **verifier** (depends on every worker), one **synthesizer** (depends on the
verifier).
2. **Write every body to a file and pass `--body-file`.** Bodies contain newlines and
flag-like lines; a body file is the only form that survives quoting intact.
3. **Create in topological order, capturing each id**, passing `--parent <id>` for every
dependency. A parent's id does not exist until its card does, so this cannot be one
batch.
4. **Assign a profile that is actually installed.** The dispatcher spawns the card's
`--assignee`; a missing profile fails the spawn and the card auto-blocks after the
failure limit.
5. **Confirm the dispatch path exists** (`dispatch --dry-run`), then create and watch
with `kanban show <id>` / `kanban tail <id>`.
6. **Judge progress by artifacts on disk**, not by the card's status alone — a worker
can be `running` while its output file already exists, and the next stage only needs
the file.

## Pitfalls

- **Scratch workspaces are ephemeral.** A card's default workspace is deleted when the
  card completes, so anything a later stage needs must be written to an **absolute path
  outside it** (pass it in the body). A worker that writes its result into its own
  workspace has thrown it away by the time the verifier looks.
- **Two dispatchers race for claims.** Running the gateway's dispatcher *and* a
  standalone daemon means both claim the same card. Run one.
- **A `todo` card is not a stalled card.** It has unmet parents. Check the graph before
  looking for a fault.
- **The stage after the fan-out must assemble it.** If each parallel unit writes its own
  output file, nothing has combined them — a downstream consumer that expects one
  assembled artifact finds nothing and reports an error, correctly. Give the graph an
  explicit assembly step between the fan-out and whatever consumes it, and make it
  deterministic. Put the assembly command in the **consuming card's body, ahead of the
  check it feeds**, so the order cannot be got wrong; a check run on an unassembled round
  returns a confident "no output found", which is the right answer to the wrong question.
- **A stage that re-implements the harness must write *all* the harness's artifacts, not
  just the obvious output.** When a card invokes one unit of work that the normal driver
  would run in-process, the driver usually writes more than the result — typically a
  metadata file recording the target, its revision and the stacks it detected. Omit it
  and the consumer does not fail: it falls back to a default context in which nothing is
  expected to have run, so any coverage-weighted term collapses to zero and the score
  moves silently by a large margin. Enumerate what the in-process path writes and
  reproduce each one.
- **A card body is not a shell script.** Keep it to the command, the working directory,
  and what to report back. Multi-step logic belongs in the command, where it is testable,
  not in prose a model re-interprets each run.

## Verification

```bash
hermes kanban list                  # every card reaches done
hermes kanban show <root-id>        # events: claimed → spawned → heartbeat → completed
```

Then confirm the pipeline's **own** output exists and is correct — the board going green
proves the cards ran, not that the work is right. Score or inspect the artifact the last
card produced.
