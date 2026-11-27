# Test reliability under real CI

A test that passes alone on a quiet workstation and fails in CI is not flaky — it is
unowned. This is the set of resources a test can share without meaning to, and the rule for
each. From DeepSeek Harness's `dsh-ci-test-reliability`, which exists because its runners
share one host and one volume across jobs.

## Model the topology before the test

Assume these can overlap unless the active configuration proves otherwise:

1. tests in one file;
2. separate files or worker processes;
3. independent processes in one job (a gate beside the suite);
4. different CI jobs on runners that share a host.

Process isolation does not isolate **host ports, predictable filesystem paths, external
services, databases, sockets, or inherited child processes**. For every acquired resource,
name its owner, its atomic allocation, its readiness signal, its cleanup registration, and
its completion signal.

Do not serialise a whole suite because one fixture lacks isolation. A sequential block
cannot protect a host resource from another file, process or job.

## Allocate atomically

Use the owner's allocator; never check availability and claim it later.

- **Ports:** bind `127.0.0.1:0`, read the assigned port **after** the server reports
  listening. Never scan for a free port and bind it later — the gap is the race.
- **Temp paths:** `mkdtemp`, not a predictable shared name. A path the code must not
  already hold is created with `O_EXCL` / exclusive create.
- **Namespaces:** shared databases, sockets and output locations get a unique name per test.
- **Recorded vs live:** keep stable recorded identifiers separate from ephemeral transport
  addresses, and translate inside the fixture rather than forcing the live resource to use
  the recorded value.

A literal path or URL used only as a parser input or an expected value is not an acquired
resource — do not rewrite it because it looks fixed.

## Contain process-global state

`env`, `cwd`, fake timers, locale and timezone, module mocks, registries, console hooks,
`globalThis`, and global network interception are **exclusive mutable resources**. Prefer an
injected dependency or an instance-local adapter. When mutation is required:

- record whether the original value was absent or present, and restore *that*;
- register restoration immediately, and keep an `afterEach` fallback;
- wrap the smallest possible scope in `try/finally`;
- intercept the narrowest exact call the fixture owns.

## Respect platform-owned semantics

- **A write-back is not always lossless.** Restoring an `mtime` to prove a fingerprint
  invalidates holds everywhere; restoring it to prove a record stays valid assumes a
  round-trip NTFS's 100 ns ticks do not give. When the assertion depends on the restoration,
  take the expected value from a fresh read.
- **Windows matches environment variable names case-insensitively**, so `http_proxy` and
  `HTTP_PROXY` seeded as two keys are one entry there.
- **Windows releases file handles asynchronously**, so a rename or removal that is instant on
  POSIX needs a bounded retry sized to observed contention.
- **No POSIX permission or signal semantics.** A case that needs them takes an explicit
  platform skip naming the reason, rather than an assertion weakened on every platform.

Prefer an observation that holds everywhere; exclude explicitly where one cannot. The wider
platform matrix — paths, temp roots, modes, short names, and how to reproduce a host condition
locally — is `cross-platform-test-portability`, which owns it.

## Budget timeouts against the lane

A per-test timeout **overrides** the runner's default instead of yielding to it, so a value
below the lane budget lowers what CI already granted — and the same literal reads as a
widening on a host whose default is smaller. A suite bound by process creation takes the
lane budget; a tighter value carries the reason. Raise hook budgets with test budgets: setup
and teardown pay the same contention, so lifting only the case budget moves the failure into
teardown.

Where a timeout is the subject, keep the outer wait far larger than the timeout under test,
or load decides which deadline reports first.

## Count the work, not the wall clock

A test's cost is **process spawns and real waits**, not its local duration. Timing it on a quiet
workstation measures the workstation.

- **Size a timeout by counting spawns**, not by timing them. A fixture that shells out for version
  control or a package manager can make dozens of process events per case; multiply by a per-spawn
  cost measured on the slowest CI leg, then compare with the budget.
- **Start independent children together.** A loop of sequential spawns is the commonest way a suite
  becomes slow in one commit.
- **Test parsing and validation in-process**; keep one or two real subprocess tests per file for
  exit codes, signals and stdio.
- **Never assert wall-clock speed.** An `elapsed < 500ms` assertion fails at 510 ms on a loaded
  runner. Count operations instead, or choose an input where a regression is catastrophic and let
  the test timeout catch it. A ratio of two timings still fails on a load spike; where one stays,
  use a generous factor and label it timing-sensitive.
- **Advance a fake clock to the next timer** (`advanceTimersToNextTimer`, `runOnlyPendingTimers`),
  never in fixed 10 ms steps: a fuzz case under step-wise advancement becomes hundreds of thousands
  of event-loop turns.
- **Do not reach for `--isolate` or bare `--parallel` to fix one test.** Isolation buys correctness
  with a multiple on suite wall time. The leak is the bug — a module mock, a global hook, a shared
  registry a test left behind. Keep files independent instead, and make a runner-level decision
  separately, measured on every OS leg.

## Synchronise on state

A fixed sleep is not evidence that setup finished or cleanup settled.

- Wait for an explicit readiness event, handshake, state transition, or owned promise.
- Use barriers/deferreds to place a race at a deterministic point and prove the operations
  overlap. **Repeated execution alone is not a race test.**
- A timeout bounds a wait; it never makes an assertion correct.
- When time is the subject, inject or fake the clock — and always restore real timers.

## Dispose to quiescence

Register cleanup immediately after acquisition so an assertion failure also releases.
Cleanup stops new callbacks, detaches listeners, restores global hooks, terminates owned
work, and **awaits** child exit, server close, or the equivalent completion signal. Calling
`abort()`, `close()` or `kill()` without awaiting is incomplete teardown. Where late
completion is possible, prove disposal stops it mutating another test.

## Reject flake-masking fixes

None of these is a root-cause fix for a deterministic local test:

- raising a timeout without naming the awaited state;
- adding retries;
- making every file serial;
- swallowing an error or an unhandled rejection;
- weakening an assertion;
- normalising away the unstable behaviour;
- adding a sleep before cleanup or an assertion.

Retries stay valid for documented transient external-provider tests, at that boundary only.

**Restoring a budget is not masking.** Raising a suite to the lane budget it already had, or
sizing a bounded retry to contention actually measured on the runner, names the awaited work
and returns what the lane granted. Neither invents headroom around an unexamined wait.

## Verify the world, not the self-report

An assertion may never read the subject's own account of itself. An end-to-end check
re-runs the command or re-reads the artifact externally, and a file the change did not touch
is compared byte-identical before and after; a test that greps the output text for "done"
passes for a subject that only narrated success.

**Only a run with real credentials proves a model-facing path; a test without them proves
plumbing.** Live-provider calls are the top of the evidence ladder rather than a luxury to
ration, and a case that self-skips without its key is unmeasured, not green.

## Two consecutive runs, and a leak census

One green run proves little: eventual consistency, a retry that leaks a resource, another process
deploying the same name, and an API that sometimes ignores a write all show up in only some runs.

- **Run the suite twice, and treat the second run as part of the first one's evidence.**
- **Census what the run left behind** — accounts, temp roots, child processes, containers, ports,
  queue entries, uploaded artifacts. A suite is stable when two consecutive full runs pass *and*
  the census after each is empty.
- **A diagnosis-only request stays read-only**: report the cause and the evidence, and stop.

## Evidence to report

- global mutation → restoration evidence;
- lifecycle or subprocess work → quiescent-teardown evidence;
- ports, sockets, shared paths → concurrent independent-process evidence;
- a new guard → a negative control.

Report the exact commands and what they returned. A retry, a skip, or a pending CI run is
not a pass.
