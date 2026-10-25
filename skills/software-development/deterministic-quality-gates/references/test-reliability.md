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

Prefer an observation that holds everywhere; exclude explicitly where one cannot.

## Budget timeouts against the lane

A per-test timeout **overrides** the runner's default instead of yielding to it, so a value
below the lane budget lowers what CI already granted — and the same literal reads as a
widening on a host whose default is smaller. A suite bound by process creation takes the
lane budget; a tighter value carries the reason. Raise hook budgets with test budgets: setup
and teardown pay the same contention, so lifting only the case budget moves the failure into
teardown.

Where a timeout is the subject, keep the outer wait far larger than the timeout under test,
or load decides which deadline reports first.

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

## Evidence to report

- global mutation → restoration evidence;
- lifecycle or subprocess work → quiescent-teardown evidence;
- ports, sockets, shared paths → concurrent independent-process evidence;
- a new guard → a negative control.

Report the exact commands and what they returned. A retry, a skip, or a pending CI run is
not a pass.
