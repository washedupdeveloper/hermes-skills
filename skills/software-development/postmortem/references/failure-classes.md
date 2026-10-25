# Failure classes

Six ways a defect reaches production while every check is green. Each is a class, not an
instance: the mechanism is what recurs. Distilled from DeepSeek Harness's postmortems,
where each one cost a shipped feature.

Use this while investigating — the class tells you what to instrument — and while writing
the guardrail, which should close the class rather than the instance.

## The test validated a path the product never takes

A test that builds the object by hand — passing the dependency list, mounting the module
directly, constructing the config itself — cannot reproduce what the loader does with the
real module. Measured: a stray default export made the loader discard the plugin's declared
dependencies; every unit test supplied them manually, so 178 green tests and 100% line
coverage certified a bridge that could not create a single session.

**Detection:** one test per entry point that goes through the real loader, the real binary,
or the real subprocess, asserting a model-visible or user-visible effect.
**Guard that closes the class:** boot the shipped artifact in a smoke test, and prove it
fails when the defect is reintroduced.

## A config value is accepted where it is not evaluated

A syntactically valid configuration key is not necessarily read at the location you assume.
Measured: a conditional expression written in an entry's metadata was parsed, never
interpolated — only one nested field was — so the entry stayed disabled in every mode, with
no diagnostic. Seven scenarios then called tools that were not registered, and the snapshot
suite passed because both the transcript and the fixture had been regenerated from the same
broken run.

**Detection:** for every key you set, name the code that reads it, and assert the effect
(not the presence of the key).
**Guard that closes the class:** reject expression nodes in metadata fields at parse time,
and assert a semantic property of the artifact — the tool is registered — independently of
the expected output.

## Acceptance substituted its target

The agent changed the source, then proved a *different* thing: an HTTP 200 from a bare dev
server (blank page — the boot manifest was injected only by the full host), then a
replacement server on a new port, while the user's page on the original port had already
picked the change up. Every individual observation was true and none was evidence.

**Detection:** name the exact origin, port, process, unit, or file the user is looking at,
and observe the change *there*. Readiness is not liveness: transport answered, application
did not start.
**Guard that closes the class:** publish the canonical target as a model-visible fact, and
require external observation at that target for acceptance.

## Attribution by shared prefix, not by conjunction

A diagnostic namespace carried two different meanings — a benign "partial enforcement"
notice and a fatal launcher failure — and the consumer treated the shared prefix plus any
non-zero exit as infrastructure failure. A child's ordinary exit code (a search tool's
"no matches" is exit 1) was then blamed on the sandbox.

**Detection:** for each classification, list the independent facts that must *all* hold, and
the exact lines that are informational rather than fatal. Unknown fatal lines stay
fail-closed.
**Guard that closes the class:** classify on a conjunction (status code + fatal line +
exact exclusions), and test the benign-line-plus-nonzero-child case explicitly.

## An adapter replaced a structured error with its own category

A layer caught a typed failure from below and substituted its nearest generic error, so the
caller lost the discriminant it needed to distinguish "sandbox unavailable" from "search
failed". Nothing errored; the diagnosis was simply wrong from that layer up.

**Detection:** follow a failure from its origin to the report, and check the discriminant
survives every hop.
**Guard that closes the class:** an adapter preserves the structured failures owned by the
seam below it, or wraps them without discarding the cause; test the structured case, not
only the raw one.

## A stale build satisfied the resolution

The test ran against a previously built artifact, because module resolution from a
temporary working directory fell back to the build output instead of the source. The old
code passed; the new code was never executed. The same shape appears as a dev runner masking
what the shipped binary does — settle races, module resolution, swallowed load failures.

**Detection:** assert *which* artifact the run loaded (a version marker, a path, a hash), and
run the published entry point under the plain runtime at least once.
**Guard that closes the class:** pin resolution explicitly for test subprocesses, and keep a
built-artifact smoke test green.

## A scenario inherits the composition it is not about

**Detection:** name the composition each scenario boots and where any pin or header came
from. A pin inherited from another composition tests the wrong wiring.
**Guard that closes the class:** boot the composition from its own definition, and make the
pin an explicit input of that composition.

## A control acts on a layer that does not decide the outcome

**Detection:** trace the decision to the layer that *reads* the control. A flag, an env
var or a guard that acts elsewhere changes nothing but the reading of the test.
**Guard that closes the class:** assert at the deciding layer, or change the composition —
widening the reading of the control is not a fix.

## A boundary fake covers only the happy grammar

**Detection:** list the protocol's own enumeration — line kind by status — and diff it
against the fake. The state the real host reaches only on legacy paths is the one missing.
**Guard that closes the class:** the fake's matrix is derived from the protocol's
enumeration rather than hand-picked, including the ambiguous state.

## Evidence delivered on the untrusted party's channel is replayable by it

**Detection:** for each piece of inbound evidence, ask who could produce the same bytes.
A tighter conjunction stops collisions; it never authenticates the writer.
**Guard that closes the class:** authenticate the writer (origin, keys, a nonce the peer
cannot choose) rather than pattern-matching the payload.

## A during-run property is sampled after the run

**Detection:** name the instrumentation point. A property asserted after the process exits
cannot distinguish the transition that matters from the state it left behind.
**Guard that closes the class:** instrument the boundary itself, so a guard's failure is
attributable to exactly one transition.

## One symbol, two export homes

**Detection:** after the module loads, assert the *consumed descriptor's* fields are
non-empty — not that the import resolved. A default export sitting beside a named namespace
made an unwrap step return the bare function and drop everything the consumer read from it.
**Guard that closes the class:** one export home per symbol; reject `default` beside a
namespace, and test through the real load path rather than a hand-built context.

## A lookup that branches on the caller's context

**Detection:** for each early return, name the production caller that takes the shortcut
*and* the test that runs inside the real context. An ancestor-only walk that throws in
production never ran, because the test's fixture mounted flat.
**Guard that closes the class:** run the test in the product's context, or delete the branch;
a bootstrap entry point that legitimately takes the shortcut is named as such.

## Using these in the write-up

The class belongs in "why the tests missed it", and the guardrail closes the class rather
than the instance. When a postmortem names an instance only — one file, one line — the next
occurrence arrives through a different file and the document has taught nothing.
