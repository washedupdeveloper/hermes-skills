---
name: hermes-process-operations
description: "Use when spawning or auditing Hermes agent subprocesses."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
category: autonomous-ai-agents
metadata:
  hermes:
    tags: [hermes, subprocess, spawning, background, provenance, argv, diagnosis]
    related_skills: [hermes-agent, council, hermes-terminal-backend]
---

# Hermes process operations

Running `hermes` as a child process — from a harness, a script, or a shell — and
working out afterwards which session or process did something. The bundled
`hermes-agent` skill covers the CLI surface; this skill covers the failure modes that
appear only when another program drives it.

## When to Use

- A harness renders a prompt and shells out to `hermes` (the council, an ablation
  runner, a benchmark, a batch job).
- A spawned agent produced no output, or exited non-zero with no explanation.
- You need to know which session, task or job started a process, wrote a file, or
  created a run directory.
- A background process finished and you cannot tell what launched it.

## Rules (always on)

**Long prompts go in a file, never in `-q`.** `-q` delivers the prompt as a single
argv element, and the kernel caps one argument at `MAX_ARG_STRLEN` (65536 bytes on
Linux). Past that the child never starts: the spawn dies with
`[Errno 7] Argument list too long`, and the caller sees only a non-zero exit and a
missing output file — no message from the agent, because the agent never ran. Use
`hermes chat --query-file PATH` (mutually exclusive with `-q`): no such limit, and not
shell-interpreted, so quotes, `$(...)` and backticks survive verbatim. Any prompt
built from repository data — probe JSON, a diff, a file tree — reaches this size, and
a small fixture passes while every real input fails, so size the test input to the
real artifact before trusting a green run.

**A scratch file derived from a shared base is shared by every concurrent worker.** A
harness that runs N children in one pool and writes each child's input to a path built
from a common base — the run log, the output directory — hands all N the *same* file.
The children then overwrite each other's input and read back whichever write landed
last, so the field that decides where each child writes its output belongs to another
child. Every worker runs, one artifact comes back, and the batch still reports the
worker count it intended — a self-report that cannot detect its own failure. Derive
per-worker scratch paths from something unique to the worker (`os.getpid()` plus
`threading.get_ident()` is enough, and is the right scope: sequential calls in one
thread may share, concurrent ones must not), and assert N distinct artifacts exist
after the batch.

**A long child dies with the turn that started it, and the exit code says so.** A run
of several minutes is past any foreground timeout, so it gets started as a background
process — and that process is sent `SIGTERM` when the turn that started it ends. The
run dies mid-work with exit `143` (`128 + 15`) and leaves a partial artifact set and no
verdict. Start it so it survives the turn (`persist_on_release`, or a detached
session), and read the result from the artifacts the job writes rather than from a live
process. `143` is the tell: it is the signal, not the job's own failure, and a partial
set of outputs is what it leaves behind.

**A child that dies before starting leaves no trace in the agent.** The caller's
summary carries only `rc=126` or an empty result. Write a log per child and keep it
beside the output file — a harness that reports "no file produced" and discards the
child's stderr has thrown away the only evidence. Distinguish "the child ran and found
nothing" from "the child never ran": a missing output file plus a non-zero exit is
the second, and no amount of reading the rubric or the input will explain it.

**Read the provenance record before attributing work to another session.** Every
background terminal process writes `~/.hermes/logs/process-results/<proc_id>.json`
(under `$HERMES_HOME`, so each profile has its own) carrying `command`, `cwd`,
`started_at`, `exit_code`, the captured `output`, and the owning session: `task_id`,
`owner_task_id`, `session_key`, `parent_session_id`. If `task_id` names the current
session, you launched it — including from a part of the conversation that was
compacted away. A compaction summary is a paraphrase of your own work, not evidence
about who else is running.

**Check the live registries before concluding something is running.** `delegate_task`
with `action='list'` (subagents), `cronjob_manage` with `action='list'` (scheduled
jobs), kanban activity for today, and a process-table grep for a cwd inside the
project. All empty means nothing is running on your behalf.

**Do not offer a global gate as the remedy for a concurrency problem you have not
confirmed.** A setting like `write_approval: true` restricts the user's own writes
too, so proposing it against a phantom costs them autonomy and fixes nothing. Confirm
the problem, then propose the narrowest thing that addresses it.

## Pitfalls

- **Passing the prompt as an argument because it works in testing.** A fixture-sized
  prompt hides the argv cap completely; only the real payload size exposes it.
- **Reading the caller's exit code as the child's diagnosis.** An exit code carries no
  message. Log the child's stdout and stderr to files and read those.
- **Inferring a concurrent actor from an unexplained artifact.** An unexplained run
  directory or repo write has an owner, and the provenance record names it. Check
  before reporting a phantom.
- **Proposing a config change to fix a hypothesis you have not tested.** It outlives
  the conversation and becomes folklore; a wrong diagnosis with a config change
  attached is worse than no diagnosis.
- **Deriving a worker's scratch path from a shared base.** The path looks unique
  because it carries a name or an index; it is not, if the base is shared. Give each
  concurrent worker a token unique to it and check the artifact count.
- **Reading `143` as the job's failure.** It is `SIGTERM` from the lifecycle, so the
  job's own logs will be truncated rather than reporting a fault. Re-run it detached
  instead of debugging the work.
- **Letting the child inherit the caller's identity implicitly.** Per-profile
  credentials are not inherited, so a spawned `hermes` must be given the profile it
  should run as (and that profile set up), or it authenticates as the wrong identity.
