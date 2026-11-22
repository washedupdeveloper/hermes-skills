---
name: state-machine-audit
description: "Use when auditing state machines, retries or concurrency."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
category: software-development
metadata:
  hermes:
    tags: [state-machine, concurrency, retries, invariants, audit, transitions]
    related_skills: [defensive-patterns, systematic-debugging, verify-and-stop]
    source: distilled from a full CLI/run-engine state-machine audit
writes: [none]
side_effects: [none]
---

# State Machine Audit

Map the states a system can actually occupy, state the invariants, table the
transitions, then prove which invalid states are reachable. A document alone is
not the deliverable: confirmed bugs are fixed with regression tests and the map
is updated to the fixed shape.

## When to use

- The user asks for explicit and implicit state machines, invariants, transition
tables, or invalid reachable states.
- A bug involves retries, duplicate work, partial writes, cleanup, cancellation,
concurrency, or an output that can be left behind.
- A CLI or service has a lifecycle with “started”, “incomplete”, “kept”, “leased”,
“retried”, “cancelled” or “exported” states that only exist across several modules.
- Do not use for a single pure function; use `systematic-debugging` for one bug.

## Output contract: one file

Put the whole map in one file, normally `docs/STATE-MACHINES.md`. Do not scatter
state notes across issues, comments and a separate README.

For every machine record:

- **Owner** — the module/function that decides the transition.
- **States** — named states, including failure and cleanup states.
- **Invariants** — what must be true in every state; make each falsifiable.
- **Transition table** — `from | event | guard | to | side effect`.
- **Invalid transitions found** — reachable states that violate an invariant,
  with a code path and a test/probe as evidence.

Then add:

- **Issue table** — `id | priority | invalid transition | impact | fix/evidence |
  status`. Group related fixes; use stable ids such as `SM-01`.
- **Residual table** — races or unbounded inputs not fixed, with the reason and
  the missing primitive. Never omit a known residual.
- **Verification** — exact commands and any live probe result.
- **Update rule** — a state/guard change must update this file in the same commit.

Use `templates/STATE-MACHINES.md` as the skeleton.

## Procedure

1. **Inventory state owners.** Read the CLI/parser, orchestration, persistence,
   transport/subprocess, retry loop, cleanup, external integration and config
   modules. A machine is wherever a field/flag/file changes meaning; include
   implicit states such as “directory exists but verdict is absent”.
2. **Draft the map before fixing.** Put every machine in the one file with its
   states and invariants. This exposes contradictions that a per-bug reading
   hides.
3. **Enumerate transitions from code, not intent.** For each state ask: what
   events can arrive, what guards run, what side effect happens first, and what
   happens if the process dies between the side effect and the next transition.
4. **Hunt invalid states by class.** Use the checklist below; for each candidate,
   write the smallest reachable scenario and decide whether it is confirmed or
   only theoretical.
5. **Prove it.** Prefer a deterministic unit regression at the seam, then a
   black-box CLI probe for the real entry point. For concurrency, run two real
   processes, not two mock calls. For retries, use a counter-backed stub that
   fails once and then succeeds, and assert the recorded attempt count/failures.
6. **Prioritize and group.** P0 = corruption/loss/escape; P1 = crash or wrong
   verdict; P2 = hidden missing evidence or a hang; P3 = bad diagnostics/cleanup;
   P4 = residual race/DoS. Group fixes that share one state boundary.
7. **Fix the narrowest layer.** Claim/guard in the persistence or transport
   primitive, not in every caller. Every fix gets a regression test and a row in
   the issue table flipped to fixed.
8. **Re-run the map.** After the fix, re-read the transition tables. If a fixed
   guard moved, retarget any mutation-check pattern that pointed at the old one.

## Invalid-state checklist

### Ownership, persistence and concurrency

- Is a shared output directory **claimed exclusively** before the first write,
  or is there an existence check followed by `mkdir(exist_ok=True)`?
- Does a start failure before evidence remove the empty claim, while a failure
  after evidence keeps it?
- Does an export/keep step **merge** into an existing destination?
- Are writes atomic (temp + replace), or can a kill leave partial JSON?
- Can two processes share a run id, lease, cache key or output path?
- Is a path component checked and then used later (TOCTOU symlink swap)?
- Does verification of an external commit/input remain true until the work ends?

### Retries and evidence

- Is a non-retryable failure (missing binary, bad credential, invalid config)
  inside a generic retry loop?
- Is every failed attempt retained, including the last raw answer?
- Can a failed sample produce `PASS`?
- Is missing evidence named in the **reason** even when the verdict is already
  FAIL/INCOMPLETE?
- Is agreement/confidence `null` when any sample has no output, rather than true
  from the subset that answered?
- Does a retry re-use the same idempotency key, or create duplicate side effects?

### Transport and decoding

- Does `text=True` decode child output with strict errors? One invalid byte must
  become a failed sample, not a traceback.
- Does a final/result event with empty text discard usable earlier text events?
- Can a silent child hold the stdout pipe after the parent is killed? Kill the
  process group, not only the parent.
- Is the timeout per attempt or only per whole run? Is the watchdog reading a
  last-event timestamp shared safely with the reader?

### Paths and inputs

- Are run ids one portable segment: no separators, `.`/`..`, Cc/Cf/Cs/Zl/Zp,
  Windows-reserved characters, surrogates or overlong names?
- Is a path proof/config/prompt required to be a **regular file** before read?
  `is_file()` false does not stop `open()` from blocking on a FIFO.
- Is a read path resolved inside its root, and is each pre-existing component
  checked for symlinks?
- Are malformed TOML/JSON/UTF-8 converted to typed errors at the boundary?
- Does a JSON Pointer array index accept only `0` or `[1-9][0-9]*`? `int("-1")`
  indexes from the end and `int("01")` indexes zero.

### CLI and output

- Does every user value get preflighted before the first `mkdir`, write or spawn?
- Are empty paths rejected, or does `Path("")` silently mean `.`?
- Is a plan/dry-run prohibited from writing, and are output flags it cannot honor
  refused instead of ignored?
- Does a failed output write still run cleanup and return the start-failure code?
- Is human output stripped of Cc/Cf/Cs/Zl/Zp while machine output stays exact?

## Pitfalls

- **An existence check is not a claim.** Two processes can both pass it; use
  `mkdir(exist_ok=False)` and treat `FileExistsError` as an existing run.
- **`copytree(dirs_exist_ok=True)` is a merge.** For evidence export, refuse an
  existing target; a silent merge loses the earlier verdict.
- **`text=True` is not “valid text”.** Pass `errors="replace"` for process output
  and let schema validation mark the sample failed.
- **A FIFO passes `exists()` and fails `is_file()`; opening it still blocks.**
  Check the file type before reading, not after a hang.
- **A failed sample can be hidden by a failing verdict.** The `FAIL` branch must
  still append missing samples/units to the reason.
- **Filtering `None` keys can manufacture agreement.** If any sample has no output,
  agreement is unknown; do not compute it from the survivors.
- **An empty result event is not always the answer.** Fall back to accumulated
  text events when the final text is empty.
- **Do not document and stop.** A confirmed invalid transition with a reachable
  path is a bug; fix it with a regression test or put it in the residual table
  with the missing primitive named.
- **Do not claim a race is fixed by a test of the helper alone.** Exercise the
  real entry point; for concurrency, two processes.

## Verification

```sh
# focused regressions
python -m pytest tests/test_<machine>.py -q

# full gate; substitute the project's runner/verifier if these names differ
nix develop -c python -m pytest -q
nix develop -c mypy src
nix flake check
./bin/<verifier> --check docs/CLAIMS.md
```

A finished audit has: every machine in the one file, every confirmed issue with
an id/priority/evidence, every fix with a regression test, every residual named,
and a green gate. For the hardening rules behind the fixes, load
`defensive-patterns`; for the probe recipes, read
`references/concurrency-and-retry-probes.md`.

## Reporting the result

Keep the final report short and let the document carry the detail. State: the
document path, the number of machines, confirmed issues grouped by priority
(P0/P1/P2/P3), which ones are fixed with which regressions, which are residual,
and the exact gate commands/results. Name any remote/tracker action you did not
take; do not imply issues were filed or a branch was pushed when they were not.
