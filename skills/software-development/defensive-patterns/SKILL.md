---
name: defensive-patterns
description: "Use when reviewing or hardening a change."
version: 1.0.0
author: user, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
category: software-development
metadata:
  hermes:
    tags: [review, lifecycle, concurrency, ownership, subprocess, migration]
    related_skills: [surgical-patch, verify-and-stop, deterministic-quality-gates, postmortem, agent-harness-design]
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

**Unlink link-shaped paths.** A path that may be a symlink or a Windows junction is removed
with `lstat().is_symlink()` then `unlink`: unlink deletes the link only and refuses a real
directory, so it never follows into the target. Windows `rmSync(link)` throws
`ERR_FS_EISDIR` on a junction, and recursive deletion may descend through one.
*Check:* can the removal primitive follow a link into its target? *Boundary:* a path the
code created itself in a directory it owns.

## Boundaries and pure logic

**Validate at the boundary, trust inside.** Parse untrusted input once, at the edge (CLI args,
config, network, files, another program's output), into domain types. Inside the system, pass
typed data and propagate errors; do not re-validate.
*Check:* is a value validated twice, on both sides of a typed boundary? *Boundary:* a seam that
hands back raw bytes, or an untrusted update, is itself a boundary and must parse again.

**Keep the decision pure, the effects at the shell.** A decision function takes plain values,
returns a value, and touches no clock, network, randomness or mutable state. The thin shell
reads, calls, and writes.
*Check:* can the decision be called in a test with literal inputs, no fixture and no server?
*Boundary:* orchestration code has effects by definition; the rule binds the decision inside it,
not the orchestration.

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
