---
name: defensive-patterns
description: "Use when hardening code: input, subprocess, CLI, authz."
version: 1.2.0
author: user, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
category: software-development
metadata:
  hermes:
    tags: [review, lifecycle, concurrency, ownership, subprocess, migration, cli, errors]
    related_skills: [surgical-patch, verify-and-stop, deterministic-quality-gates, postmortem, agent-harness-design, state-machine-audit]
    source: DeepSeek Harness (deepseek-ai/deepseek-harness) docs/defensive-patterns, distilled
---

# defensive-patterns

Bug classes that ship and survive review, each stated as the rule that prevents its
recurrence. Adopted from DeepSeek Harness, where every rule is enforced in review, and
rewritten language-agnostic: the instances are TypeScript, the classes are not.

Read the section for the artifact you are about to change, **before** changing it.

## The rule format

Every rule here carries four parts, and a rule missing one of them is advice:

- **The rule** — what must hold, as an imperative sentence.
- **Prevents** — the defect that actually shipped or nearly shipped.
- **Check** — the condition a reviewer judges, stated so it can come out false.
- **Boundary** — where the rule stops applying, so a correct change is not rejected for
  its shape. A rule with no boundary gets applied to everything and then ignored.

Write your own rules in this shape. "Be careful with async" is unjudgeable; "each
independent outcome is readable without entering another condition's branch" is not.

## The five habits

1. **Make correctness explicit.** Named call points, explicit lifecycles, explicit
   conditions and types — not compensation afterwards with timing.
2. **One source of truth.** One read path per fact, one owner per shared state.
3. **Extend through the registered seam.** A new capability registers itself; an existing
   carrier stops taking new branches instead of growing one.
4. **The change face equals the review face.** A change carries only the lines its stated
   behaviour needs; a migration moves code rather than rewriting it; a
   performance-sensitive change carries its measurement.
5. **Require evidence.** A claim is falsifiable and recomputable — measured before and
   after, or checked by a gate — never kept in sync by hand.

## Reporting outcomes and state

**Report orthogonal outcomes independently.** A process can time out *and* exit 0 because
it trapped the signal. Surface each fact (`timedOut`, `signal`, `exitCode`) on its own;
never nest one flag's report inside another's branch.
*Check:* can each fact be true independently, and is each readable without entering
another condition's branch? *Boundary:* how the process is signalled or how long it is
given is a separate decision from how the result is reported.

**Async state is not synchronous state.** A shared "running" flag is not a per-item
completion. If an API defines no completion for the unit you care about, the caller states
its own interval and describes the output as interval-wide rather than causally attributed
to one message.
*Check:* does the code observe a completion the API does not define? *Boundary:* the
caller may own the interval — but a shared flag is never that statement. Handle the
"nothing to wait for" branch explicitly, or the wait hangs.

**Timing does not carry correctness.** A microtask, a `setTimeout(0)`, a "just after
render" effect — none of them decide whether work is correct. They hold under a light load
and fail silently under a busy one.
*Check:* does correctness depend on "that callback already ran" instead of a named call
point or a state machine? *Boundary:* a test's timeout budget waits for a failure and is
not this rule; a deliberate delay that only paces user-visible work is not this rule.

**One value states one fact.** Unknown, empty, and absent are three different facts and
take three representations. One `null`/`undefined` must not stand for several.
*Check:* does a single "no value" carry more than one semantic — not yet queried, queried
and empty, cannot be determined? Use a discriminated union or an explicit enum.

**Missing evidence is named in the decision, not only the artefact.** A failed
sample or unreviewed unit belongs in the verdict reason even when the verdict is
already FAIL; a failing result does not make missing evidence disappear. Agreement
is `null`/unknown whenever any sample in the set produced no output, never true from
the samples that happened to answer.
*Prevents:* a clean-looking FAIL hiding that half the evidence never arrived, and
an agreement flag computed from a filtered subset. *Check:* can a missing sample
be absent from the human reason or counted as agreement? *Boundary:* a sample that
ran and returned findings is evidence even when other samples failed.

**Optional inputs state both behaviours.** An optional parameter says what the callee does
when present *and* when absent, so a caller reads both from the contract. Accumulating
`?.` is the signal: each one substitutes for a decision about whether the field should
exist at all.
*Check:* does `?.` replace a determination that a field exists, rather than handling a
genuinely optional hop on a known value? *No exception:* a call site that cannot state
both behaviours is a review blocker, not a style preference.

## Ownership and lifecycle

**Shared state has one owner.** Hang it on a service or an instance whose lifetime is
auditable. A module-level cache, a singleton, a global `WeakMap`, or a `globalThis.__X__`
bypass hides the owner and outlives every teardown.
*Check:* name the owner. If no owner can be named, the owner is decided before the
implementation. *Boundary:* a field on a service may be read by any number of injected
consumers; crossing domains goes through the existing interface.

**A new global "active"/"current" singleton is refused.** A globally unique selection is a
design statement most codebases should not make: several views of one piece of data each
hold their own reference or key.
*Check:* does the change add a globally unique selected-state field? *Replacement:*
one piece of data, several views, each carrying its own reference.

**A business capability owns itself.** It lives in its own module and attaches through a
registration surface; the centre layer holds the registry structure and the disposal
lifecycle and forwards — it never hardcodes a table of business rows.
*Check:* does the capability declare and register itself, with the centre only managing
lifetime? *Boundary:* pure infrastructure — logging, transport, storage — does not attach
through a business registration surface. A new branch in a centre layer must explain why it
cannot live in the owning module.

**Split a capability by business boundary, not by caller count.** A new capability is its
own service or module; growing one large object a method at a time leaves it answering for
auth, data, transport and events at once, so every later change to one capability touches
all of them. A capability with a single caller today still gets its own service, and a
moved endpoint appears on its new owner rather than joining the object it is leaving.
*Check:* which object holds the new method. A new business line added to an object that
already owns another line is the defect. *Boundary:* a service whose methods all serve one
business boundary stays whole, and a new private helper of that capability belongs on it.
A single caller is not a reason to merge.

**Contain listener exceptions in the dispatcher.** Catch and report each listener's failure
without rejecting the dispatch or starving later listeners — and the listener's owner must
still handle the state it mutated. Catching is not recovery.
*Check:* can a throwing listener reject the dispatch promise or prevent later listeners?
*Boundary:* an error the dispatcher deliberately propagates to the operation that requested
it is not a containment failure.

**Disposal must reach quiescence, not just request it.** Await child exit after killing or
aborting. Optional notifications may stop early; resources and listeners needed for
completion or final persistence must survive until consumers settle.
*Check:* does teardown await actual quiescence? *Boundary:* a detached task with no owner to
await — anything the component started and can still observe must be awaited before it
reports completion.

## Processes, files, untrusted output

**Never hand untrusted output the ambient environment or a predictable path.** Spawn with a
scrubbed environment (drop `*KEY*`, `*SECRET*`, `*TOKEN*`, `*PASSWORD*`) so credentials
cannot leak into output, `env`, or spill files. Temp files use a private (0700) directory,
random names, and exclusive owner-only opens (`O_EXCL`, 0600): a predictable world-readable
path invites symlink races and disclosure.
*Check:* does a spawned process inherit the ambient environment, or write somewhere another
process can predict and replace? *Boundary:* trusted in-process code with no external input.

**Run commands that come from outside the program in a sandbox that fails closed.** When the
command is supplied by an untrusted source — a reviewer's proposed check, a plugin hook, a
generated script — wrap it in `bubblewrap`: network unshared, root read-only, a private `/tmp`
and `$HOME`, a cleared environment, and the repository it judges mounted as an overlay so the
writes it makes vanish with it. A missing sandbox binary is not a reason to spawn anyway: the
command is reported unrunnable, and never as a refutation of whatever it was meant to check.
*Check:* can the command reach the network, write outside its scratch space, or read ambient
credentials? Is there any path where an unavailable sandbox degrades to a plain spawn?
*Boundary:* code the program ships and controls, and an explicit opt-out the user configured —
never a silent fallback. Recipe, argv and the traps: `references/sandboxing-untrusted-commands.md`.

**Unlink link-shaped paths.** A path that may be a symlink or a Windows junction is removed
with `lstat().is_symlink()` then `unlink`: unlink deletes the link only and refuses a real
directory, so it never follows into the target. Windows `rmSync(link)` throws
`ERR_FS_EISDIR` on a junction, and recursive deletion may descend through one.
*Check:* can the removal primitive follow a link into its target? *Boundary:* a path the
code created itself in a directory it owns.

**Validate every component between the trusted root and the write, not just the leaf.** A path
assembled as `root / state / sub / id` passes a separator check on `id` and still lands
outside the tree when a pre-existing `state` is a symlink: `mkdir(parents=True)` creates the
target's parents and the write follows the link. `lstat` each component that already exists
(`is_symlink()`) before creating anything, and refuse rather than resolving to the target.
*Prevents:* a repository under review carried `.tool-state -> /tmp/elsewhere`; the tool wrote its
run artefacts outside the checkout its own docstring promised never to leave.
*Check:* can any existing component of the destination path be a link, and does the code test
it before `mkdir`/`open`?
*Boundary:* a path whose parents the code created itself in a directory it owns, and a
deliberate redirect the operator configured — that is policy, not untrusted input.

**Claim a shared output directory exclusively.** Create the run/artifact directory
with `mkdir(exist_ok=False)` before the first sample or report. An existence check
followed by `mkdir(exist_ok=True)` is not a claim: two processes both pass the check
and write into one directory. On a start failure before evidence, remove the empty
claim; on a failure after evidence, keep it.
*Prevents:* two concurrent runs sharing one run id, mixing samples and writing a
verdict that describes neither. *Check:* can two processes both pass the guard and
write the same directory? *Boundary:* a directory the caller explicitly supplied
and owns, with its own locking.

**Copy evidence only into a new destination.** `copytree(..., dirs_exist_ok=True)`
merges two runs into one and silently overwrites the earlier verdict. Refuse an
existing target; leave the source evidence in place and name both paths.
*Prevents:* an export/`--keep` merging evidence. *Check:* can a copy overwrite or
merge an existing run? *Boundary:* an explicit append/merge operation with a
declared merge policy.

**Decode child output with replacement, not trust.** `text=True` decodes with strict
errors; a reviewer emitting one invalid byte raises `UnicodeDecodeError` out of the
transport. Use `errors="replace"` for stdout/stderr and let schema validation reject
the answer as a failed sample.
*Prevents:* invalid UTF-8 crashing the run instead of becoming evidence. *Check:*
can one non-UTF-8 byte escape as a traceback? *Boundary:* protocol bytes that must
be exact (binary frames, hashes) are read as bytes, not text.

**A missing working directory is not a missing executable.** A spawn given a `cwd` raises
`FileNotFoundError` for an absent directory exactly as it does for an absent program, so a handler
that maps that one exception to "tool not installed" reports a working binary as absent and sends
the reader to reinstall something already there. Validate the working directory before spawning and
raise a distinct error naming the path.
*Prevents:* a re-run pointed at a directory that did not exist reported every analyzer as not
installed; the operator's obvious next step could not have changed the result.
*Check:* can this code report a missing executable for a reason that is not the executable?
*Boundary:* one errno for both is the platform's contract; the rule binds the handler, not the call.

**A recompute that overwrites an artefact validates its inputs first.** A stage that re-runs a check
and replaces the previous result cannot tell "the input was bad" from "the answer changed": with a
missing input every check fails, the stage writes a vacuous report, and the good artefact it
replaced is gone. Refuse before writing when a precondition the checks depend on is absent.
*Prevents:* a re-adjudication pointed at a tree that did not exist wrote an all-failed report over a
round whose four claims were confirmed — the file was the run's only record of them.
*Check:* does the write path verify a precondition, or can any malformed invocation reach `write()`?
*Boundary:* a stage whose output derives only from files it just validated needs no extra gate; the
rule binds the case where an external argument — a path, a revision, a URL — can be wrong.

## Command-line and error boundaries

A CLI is a boundary with a cost on the other side: a model call, a write, a child
process. These rules decide what is refused before that cost is paid.

**Preflight every user value before the first write or spawn.** Validate run ids,
output parents, prompt and reviewer paths, base revisions and configuration before
creating a run directory or calling a model. A malformed request must fail with the
same code and message whether it arrives from the parser or a library caller.
*Prevents:* an invalid `--keep`/`--sarif` path discovered after the expensive call,
and a temp tree with no reader. *Check:* can any malformed argument reach the first
`mkdir`, `open(..., "w")` or `Popen`? *Boundary:* a value only knowable after I/O
(the diff, the resolved base) is validated where it is read, not in the parser.

**A start failure has its own exit code.** Keep "nothing ran" (3) distinct from
"ran and failed" (1) and "ran, evidence missing" (2). A missing executable or an
unreadable instrument is a start failure, never a retried sample or an
`INCOMPLETE` verdict. *Check:* can a missing binary be reported as a negative
result? *Boundary:* a sample that ran and failed is evidence and stays recorded as
a failed sample.

**A run id is one portable path segment.** Reject `.`/`..`, both separators,
Cc/Cf/Cs/Zl/Zp (control, bidi/zero-width, surrogate, line separators),
Windows-reserved characters and overlong names before joining, then assert the
joined path is under its root. `root / "/tmp/x"` discards the root.
*Prevents:* `--run-id ../escape` writing outside the checkout, or a bidi id
spoofing the path a reviewer reads. *Check:* can the joined path escape, become a
device, or render as a different name? *Boundary:* a constant the code owns.

**An output destination is a boundary, not a path string.** Before opening a
report or keep destination, require the parent to exist and be writable and the
leaf to be a regular file or a directory as the flag demands; a FIFO or device can
block a write forever, and a symlink can write outside. The component-chain rule
above applies to the parent too. *Check:* can `write_text` follow a link or block
on a FIFO? *Boundary:* an operator-configured redirect is policy, but a tool-owned
artefact still refuses a link.

**A read path is also a boundary.** Check `is_file()`/`lstat` before reading a
proof, config, prompt or reference path; `is_file()` false does not stop `open()`
on a FIFO, and reading it can block forever. A non-regular target is a typed
`UNRUNNABLE`/config error, not an open.
*Check:* can a read block on a FIFO or follow a link? *Boundary:* a stream the
caller explicitly supplies as a stream, with its own timeout.

**Malformed external data becomes a typed outcome, not a traceback.** Wrap the
parser's own exception (`TOMLDecodeError`, `JSONDecodeError`, `UnicodeDecodeError`)
and a custom error that inherits the wrong base; name the path or field. A proof or
validator that raises is `UNRUNNABLE`, not a crashed run. *Check:* can malformed
data produce a traceback or an affirmative result? *Boundary:* programmer errors in
code the program owns should still surface.

**Human output is sanitized; machine output is exact.** Strip Cc/Cf/Cs/Zl/Zp from
model text and paths before printing, or a claim can emit ANSI/bidi controls and
newlines. Keep `verdict.json`/SARIF byte-exact. *Check:* can a finding drive the
terminal? *Boundary:* structured outputs are evidence, not display.

**Test the real entry point, not only the helper.** A probe matrix invokes the CLI
with invalid argv, asserts the exit code, asserts no side effect, and fails on the
word `Traceback`. Unit tests of a validation helper do not prove the parser reached
it. Recipe and matrix: `references/cli-error-hardening.md`.

## Boundaries and pure logic

**Validate at the boundary, trust inside.** Parse untrusted input once, at the edge (CLI args,
config, network, files, another program's output), into domain types. Inside the system, pass
typed data and propagate errors; do not re-validate.
*Check:* is a value validated twice, on both sides of a typed boundary — or only in a wrapper
the real caller bypasses? *Boundary:* a seam that hands back raw bytes, or an untrusted
update, is itself a boundary and must parse again. *Where the check sits:* in the function
that performs the I/O, not only in the argument parser that calls it; a library caller never
runs the parser, so a scheme, host or path check one frame up guards the wrong surface.

**Keep the decision pure, the effects at the shell.** A decision function takes plain values,
returns a value, and touches no clock, network, randomness or mutable state. The thin shell
reads, calls, and writes.
*Check:* can the decision be called in a test with literal inputs, no fixture and no server?
*Boundary:* orchestration code has effects by definition; the rule binds the decision inside it,
not the orchestration.
*Enforcement:* name the pure modules in one list and let a test parse them — no `subprocess`,
`urllib`, `os`, `time` or `sys`, and no `open`, `write_text`, `mkdir` or `run`. Read the
**imported** module's file (`importlib.import_module(...).__file__`), never a hardcoded `src/`
path: a scan of the checkout keeps inspecting the unmutated tree when the suite runs against a
copy.

**An operation converges under retry.** Every command, lifecycle step and loop is idempotent:
interrupted and re-run, it reaches the same end state. Create-or-update rather than create; a
named target rather than an append.
*Check:* run it twice. The second run changes nothing and exits 0. *Boundary:* append-only logs
and event streams are not this rule; they declare their own idempotency key.

**Minimize reader load, not line count.** Count the layers between the question and the answer,
and the state a reader must hold. Collapse wrappers with one caller and adapters with no second
implementation; prefer returns over mutation, locals over fields, module state over globals.
*Check:* can a new reader say where a value comes from and what changes it without following
three hops? *Boundary:* a layer that hides a real decision stays, even if it is a wrapper.

## Surfaces, identity, read paths

**A published name is additive.** A migration never renames or removes a name clients
already call; a rename is its own change, confirmed by the owner.
*Check:* does the diff touch a name already exposed on the call surface? *Boundary:* names
never published, and internals, are free.

**One read path per derived value.** Consumers read the published value; a second fetch of
the same fact drifts from it.
*Check:* does a consumer fetch where a registered read path exists? *Boundary:* reshaping is
free; local state is not a read path.

**An outcome's representations normalize at the public API.** A consumer can name a
failure's source from the contract alone instead of guessing which layer raised it.
*Check:* can a consumer name a failure's source from the public API? *Boundary:* internal
helpers may throw freely; only the crossed boundary is bound.

**No await at module scope.** Async work lives in an explicit entry that owns its rejection;
an importer must not wait on, or die with, module evaluation.
*Check:* `await` / `for await` at module scope? *Boundary:* executables, declared as such.

**A package entry exports only its loader contract.** A test asserting internals does not
earn them a public name; a test-only export freezes into published API.
*Check:* do entry exports exceed the contract, or does a test import an internal? *Boundary:*
internal helpers stay exportable — the entry is the surface.

**A shared key vocabulary stays closed.** One documented meaning per key across the repo; a
locally invented key is a dialect nobody can read.
*Check:* a key outside the documented set, or one formalized without its owning document?

**Release is one predicate.** `refs == 0` and nothing in flight; holders are explicit, and no
enumeration of business states may stand in for it.
*Check:* is release a conjunction of resource facts rather than a list of states? *Boundary:*
a single hand-checked trigger is fine; the enumeration is the defect.

## Change discipline

**Migrations preserve behaviour, item by item.** Error codes, diagnostics, data-flow order
and UI timing are compared before and after. Moving code beats deleting and rewriting it; a
rewrite suits code whose semantics are changing anyway, and then it lists the differences.
*Check:* the item-by-item comparison. Where equality is impossible, state the differing
items and how each is verified. A defect found during a migration is fixed as its own change.

**A performance-sensitive change carries its measurement.** Runtime, peak memory and
steady-state memory on the changed path, one environment, one input — and the baseline is
the same path *without* the change, normally the native implementation that carries no
measurement hook. Comparing old and new with the same hook attached dilutes the difference
until it disappears.
*Check:* under one environment and input, is any of the three worse on the changed path?
*Boundary:* a comment, a doc, or test-only code needs no measurement. "Nothing got slower
overall" is not evidence, and an improvement elsewhere does not excuse a regression here.

**The change face is the review face.** A change carries only the lines its stated behaviour
change needs. An unrelated fix, a speculative option, or a defensive copy with no consumer
belongs in its own change, where it can be reviewed and reverted on its own.

**A comment states a non-obvious why.** No phase narration (`// Phase 1: add cards`) and no
restatement of the code; the assertion or log string documents the step. A comment a reader
could derive from the line is noise the change should not carry.

## Using it in review

1. Map the changed files to the sections above; read those sections **before** reading the
   diff. Judging a diff against memory of the rules is how a violation passes review.
2. For each rule that applies, answer its **Check** as a yes/no. A "probably" is a no.
3. State the defect, the location, the impact, and the evidence. Separate blockers from
   suggestions, and omit anything a green gate already enforces.
4. When you receive a review, verify each claim and fix or rebut it on technical grounds —
   no performative agreement, and no fix for a finding you could not reproduce.

## Verification

- [ ] Every rule you cited applies to an artifact the diff actually touches
- [ ] Each finding names the Check that came out false, not a general worry
- [ ] No rule was applied past its boundary (a rejected change that the boundary allows)
- [ ] A rule enforced only by prose here is labelled as judgement, not as a gate
