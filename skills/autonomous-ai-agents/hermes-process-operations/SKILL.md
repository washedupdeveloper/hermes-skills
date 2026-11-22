---
name: hermes-process-operations
description: "Use when spawning background jobs or Hermes subprocesses."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
category: autonomous-ai-agents
targets: [hermes]
metadata:
  hermes:
    tags: [hermes, subprocess, spawning, background, provenance, argv, diagnosis]
    related_skills: [hermes-agent, hermes-terminal-backend]
writes: [none]
side_effects: [none]
---

# Hermes process operations

Running `hermes` as a child process — from a harness, a script, or a shell — and
working out afterwards which session or process did something. The bundled
`hermes-agent` skill covers the CLI surface; this skill covers the failure modes that
appear only when another program drives it.

## When to Use

- A harness renders a prompt and shells out to `hermes` (a review harness, an ablation
  runner, a benchmark, a batch job).
- **You are about to launch any long-running script in the background** — not only one that
  spawns an agent. The `127` (written the same turn as the launch), `143` (killed with the
  turn), and "read the artifact, not the live process" rules below apply to every such job.
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

**Select the reasoning level per call; the profile's default can make a review-shaped
call look hung — but a timeout is not proof that a level is broken.** `hermes chat` takes
`--reasoning LEVEL` (`none` … `ultra`), and the profile's `reasoning_effort` applies when
the flag is absent. A high level is invisible on a one-line probe and can be slow on a
long-output prompt. Measured on one 7,954-byte review prompt: the profile default (`ultra`)
timed out at 90 s twice, yet the same level later answered in 84 s plain and 69 s streamed,
and a two-sample `ultra` review completed in 239 s; `low` answered in 206 s; `none` in 21 s.
Usage showed one API call, ~4.5k reasoning tokens at `ultra` and ~5.2k at `none`: the
provider's effort labels do not map cleanly to work done, and the timeouts were
provider/gateway stalls, not a reasoning overrun. Pass the level explicitly from the
harness, record it with the result, and hash it into the instrument digest — the same
prompt at two levels is two different instruments. Validate a cheap level before trusting
an empty answer: on a tree with a planted credential, `none` returned a `critical` finding
in 11 s; a level that misses a planted defect is not a reviewer, it is a producer that
stopped reading. Before blaming the level, repeat the call once with `--usage-file` (did it
make one call and finish?) and once with `--format stream-json` (does it emit events?) — if
the same level later answers, the level was not the variable.

**Read the answer as a stream and kill silence, do not wait out the sample timeout.** A
non-streaming child is invisible until it ends, so a stalled provider holds the caller for
the full timeout. Pass `--format stream-json` and take the final `result.text` (or the
concatenated `text` events); a stream that ends without an answer, or a `result` with a
non-zero `exit_code`, is an `OSError` for the caller to retry. A review model can think for
about a minute before its first text event (62 s observed), so an idle watchdog must sit
above that gap — 120 s works — and kill on silence, not only on the overall deadline. Kill
the **process group**, not the direct child: a wrapper's child inherits stdout and keeps the
pipe open after the parent dies, and the reader waits forever for an EOF that never comes.
Start the child in its own session on POSIX (`start_new_session=True`) and use
`os.killpg(os.getpgid(pid), SIGKILL)`. See `references/streaming-subprocess.md` for the
working reader and its tests.

**A child that must not write to the host runs under bwrap, with its inputs rebound after the private `/tmp`.** `bwrap --ro-bind / / --dev /dev --proc /proc --tmpfs /tmp --overlay-src "$HOME" --tmp-overlay "$HOME" --chdir / -- <argv>` gives the child a read-only root, a private `/tmp` and a tmpfs overlay of `$HOME`: it can read the host and reach the network, but every write to `$HOME` or `/tmp` dies with the process. The private `/tmp` also hides the prompt file and the binary, so bind each back read-only **after** the `--tmpfs` (`--ro-bind <prompt-dir> <prompt-dir>`, `--ro-bind <binary> <binary>`), and set `--chdir /` because the caller's cwd may itself be under `/tmp`. `--overlay-src` + `--tmp-overlay` is the two-argument form; `--overlay` takes three (`RWSRC WORKDIR DEST`) and is not interchangeable. Record the choice in the result (`reviewer_sandbox: true|false`), default it on when `bwrap` is on `PATH`, and make the strict flag fail rather than silently run unsandboxed. See `references/bwrap-sandbox.md` for the working invocation and the write-leak test.

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

**A foreground `timeout` arrives at the child as SIGINT, and its log then accuses the code.** A
foreground tool call's timeout is a deadline the harness enforces, not a limit the job respects:
when it fires the child is interrupted (`rc=-2`, signal 2) mid-write, and what lands on disk reads
like an application fault — a `KeyboardInterrupt` raised inside a `queue.wait()`, a stdio read, or a
thread join, under a traceback that names the program you were testing. Decide from the budget
before the first run: anything that may outlast the foreground cap goes `background=True` with
`notify=True` from the start, and a result you read from `notify` costs one turn instead of a
re-run. If you already have such a traceback, re-run it backgrounded before diagnosing anything —
the job was stopped, not broken, and the partial artifact set is the evidence of that.

**A child that dies before starting leaves no trace in the agent.** The caller's
summary carries only `rc=126` (not executable), `rc=127` (no such file) or an empty result. Write a log per child and keep it
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
- **Leaving the reasoning level to the profile default.** A profile set to `ultra` can read
  as a hang on a long-output prompt while its one-line probe answers; select the level
  explicitly, record it, and validate the chosen level against a planted defect before
  trusting an empty result.
- **Concluding a level is broken from one timeout.** The same level and prompt can time out
  once and answer in 69–84 s later; repeat with `--usage-file` and `--format stream-json`
  before changing the level, and record the level with the verdict rather than guessing.
- **Killing the parent and waiting for EOF.** A wrapper's child inherits stdout, so
  `proc.kill()` leaves the pipe open and the reader blocks forever. Start the child in its
  own session and kill the process group; close `proc.stdout` in the reader's `finally`.
- **Setting the idle watchdog below the model's thinking gap.** A review model can spend ~60 s
  before its first text event; an idle timeout shorter than that kills healthy runs. Use 120 s
  as the working default and expose it as a parameter.
- **Feeding a plain-output stub to a streaming reader.** `--format stream-json` expects JSON
  events; a stub that prints the review as plain text ends with "stream ended without an
  answer". Pass `--no-stream` for plain stubs, or make the stub emit `text`/`result` events.
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
- **Reading a child's `KeyboardInterrupt` traceback as a defect in the child.** It is the
  harness's foreground timeout arriving as `SIGINT` (`rc=-2`), and the traceback points at a
  blocking read rather than at the logic. Same family as `143`: the job was stopped, so re-run it
  backgrounded and read the artifact — do not open a debugging session on a process nobody let
  finish.
- **Launching a background job in the same turn that writes its script.** Writing the script and
  starting it are two tool calls, and the launch can be dispatched before the file exists — the
  child then exits `127` with `No such file or directory` naming the script, which reads like a
  broken path rather than a race, and the job silently never ran. Write the file, then launch it in
  a **separate** call; when a background job exits `127`, check that the script exists before
  checking anything about the command inside it.
- **Letting the child inherit the caller's identity implicitly.** Per-profile
  credentials are not inherited, so a spawned `hermes` must be given the profile it
  should run as (and that profile set up), or it authenticates as the wrong identity.
- **Binding the prompt or binary before `--tmpfs /tmp`.** The tmpfs is mounted after the
  bind and hides it, so the child starts with `No such file or directory` for a file that
  exists on the host. Bind inputs after the tmpfs, and set `--chdir /` for the same reason.
- **Using `--overlay` with two arguments.** `--overlay` is `RWSRC WORKDIR DEST`; the simple
  home overlay is `--overlay-src "$HOME" --tmp-overlay "$HOME"`. A two-argument `--overlay`
  is parsed as a different mount and fails or mounts the wrong thing.
- **Testing a sandbox with a binary that only prints.** A print-only stub proves the child
  starts, not that writes are contained. Have the fake write to `$HOME` and `/tmp`, then
  assert both host paths are absent; skip the test only when `bwrap` is genuinely
  unavailable, and assert the test ran in the gate.
