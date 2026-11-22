---
name: failure-semantics
description: "Use when designing error types, codes or recovery."
version: 1.0.0
author: "DeepSeek Harness (deepseek-harness, dsh-error-handling), adapted for Hermes"
license: MIT
platforms: [linux, macos, windows]
category: software-development
metadata:
  hermes:
    tags: [errors, exit-codes, retries, recovery, catch, contracts]
    source: deepseek-harness@39163dd30f703a79079e2d2446545cff3c453738 (.agents/skills/dsh-error-handling)
    related_skills: [defensive-patterns, agent-harness-design, postmortem]
writes: [none]
---

# Failure semantics

Define the failure, its owner, and what is still true after it. An error is a contract with
two audiences — the caller that must branch on it, and the person who reads it at 03:00 —
and a message string serves neither.

`defensive-patterns` owns the boundary checks that *produce* a typed failure (argv, paths,
malformed input, exit codes). `agent-harness-design` owns the attempt lifecycle. This skill
owns the failure's shape: what type it is, what it carries, who catches it, and what a
retry would have to be true.

## When to Use

- Designing or reviewing error classes, codes, or a return type that can fail.
- A `catch` that logs, ignores, or swallows; a retry that has no owner.
- A failure that reported success, or a success that hid a partial write.
- Writing the text a user or a model sees when something fails.
- Don't use for: argument validation and path safety (`defensive-patterns`); an incident
  write-up (`postmortem`).

## Typed, structured failures

- **One class per owning domain, not per failure site.** A separate class is justified only
  when a caller catches it *by type*, or when it carries structured fields of its own (a
  list of violations, the offending field, the retry-after).
- **A machine code is a stable discriminant.** Declare the codes as constants or a union
  beside the class; name the failure class a consumer acts on, not the call site. Reuse
  never: a second meaning under one code is a branch that silently changes behaviour.
- **Never route handling by parsing the message.** If a caller has to read prose to decide
  what happened, the failure has no type.
- **Display text is separate from identity.** The code and the class name travel; the
  message is for a human.
- **Preserve the cause.** Convert a foreign failure at the boundary where the dependency is
  owned — errno, a vendor SDK, a protocol reply — and keep the original as the cause. A
  foreign numeric or vendor code belongs in the message, not in your code field.
- **Never re-wrap your own error in a plain one**, or store only its message for a later
  rethrow. That is how a code becomes a string.
- **A process, worker or wire boundary transports the name and the code**, and the
  receiving side reconstructs the typed error. A traceback or a JSON island of prose is not
  a reconstruction.

## Catching

- **A catch limits propagation, not mutation.** Only the owner of the affected state can
  establish safe continuation. If the work that failed had already changed something,
  catching is not recovery — stop dependent work, discard the invalid state, or escalate.
- **Logging is not recovery.** A logged failure that leaves invalid state behind is a
  silent corruption with a receipt.
- **Catch the narrowest type you can act on.** A blanket catch in a boundary that must fail
  closed turns a defect into a passing run.

### An empty catch

Legitimate only when *every* failure the `try` can raise leaves the owner's state valid and
no caller could act on it. Four conditions:

1. **The `try` holds one statement.** One syntactic statement, however many lines. With
   three statements, the reason covers one expected failure while the clause also discards
   the others — including a defect in an early one, which then skips the rest while the
   caller sees success. Need two tolerant operations: two `try` blocks, two reasons.
2. **The binding names the expected failure.** `catch (_cleanupFailed)`, not `catch {}` or
   `catch (_)`.
3. **A comment states why the state stays valid.** Inside the block, or trailing the closing
   brace. `// ignore` restates the empty block; say which failure is expected and why
   nothing reads the result.
4. **When only some failures are safe, test and rethrow.** Check the code for the one you
   tolerate and rethrow everything else.

## Retry, or stop

A retry is sound only when all four hold, and each has a name attached:

- **Safe repetition** — running the work twice cannot produce a second effect.
- **Cancellation** — the caller can stop it, and the stop reaches the work.
- **An owner** — one component decides, and it is the same component that knows the budget.
- **A budget** — a finite operation gets a deadline or a count; continuing supervision gets
  a lifecycle owner and an observable degradation signal.

A retry does not fix a cause that has not changed. When two attempts failed on the same
premise, the third is a hypothesis about the premise, not another retry. The attempt
lifecycle and its bookkeeping are `agent-harness-design`'s.

## Success-shaped failure

Two outcomes are easy to confuse, and the distinction is a design decision, not a style
preference:

- A failure the caller **must not treat as success** is an error result — even when it is
  expected.
- A **successful** operation in a non-ideal state (a non-zero child exit that was allowed, a
  search that legitimately matched nothing) stays a success *value*.

A success-shaped failure value is permitted only when the output schema documents it. When
in doubt, prefer the error result: a caller that ignores an error is visible, a caller that
reads `ok: true` is not.

## What the report says

Every final failure report carries three things, and nothing it cannot back:

1. A readable summary of what failed.
2. The affected operation — which request, which file, which unit.
3. The safe next action.

- **Untrusted state or an unknown outcome must be visible** — the impact, the uncertainty,
  the system's disposition, and the next step. A persistent invalid state needs persistent
  visibility, not one log line at the time it happened.
- **Never claim success, rollback, or a safe retry without the guarantee.** "Rolled back"
  is a claim about durable state, not about the code path taken.
- **Keep sensitive internals out of user-facing text.** Paths, tokens and stack frames are
  for the log.
- **Reporting itself can fail.** It needs an independent fallback — an exit code, a file, a
  supervisor — or the failure disappears exactly when it matters.

## Pitfalls

1. **A code reused for a second meaning.** The branch that handled the first now handles the
   second, silently.
2. **A class per throw site.** The caller's `except` list grows and nobody catches the new
   one.
3. **A partial write behind a caught exception.** The catch makes it look atomic.
4. **`retry` as the fix for a flake.** It hides the cause and doubles the effect when the
   operation was not safe to repeat.
5. **The message as the API.** One wording change breaks a downstream branch.
6. **An unknown outcome rendered as an error.** "Failed" invites a retry that the unknown
   state cannot support; say it is unknown.

## Verification

- [ ] Every expected failure has a declared type and a stable code
- [ ] No caller branches on message text (`grep` for the message fragments)
- [ ] Each empty catch has one statement, a named binding, and a reason that can be false
- [ ] Every retry names its safety argument, its owner and its budget
- [ ] A partial or unknown outcome is a distinct outcome, not a success and not a plain error
- [ ] A test asserts the error's `name` and `code` on each expected path, not only the text