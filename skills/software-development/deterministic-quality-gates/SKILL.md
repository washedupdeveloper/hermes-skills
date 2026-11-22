---
name: deterministic-quality-gates
description: "Use when building or calibrating a scoring gate."
version: 1.8.0
author: user, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
category: software-development
metadata:
  hermes:
    tags: [quality, scoring, calibration, gates, metrics, verification]
    related_skills: [requesting-code-review, systematic-debugging]
writes: [none]
side_effects: [none]
---

# deterministic-quality-gates

Building a gate that scores a codebase deterministically — normalized signals, a
weighted aggregate, a pass threshold — and calibrating its free parameters from
labelled evidence instead of intuition. Also covers the loop that drives the gate
and has to know when to stop.

This is the **principle** side: what a score must be made of, and how to calibrate it. The
operational commands belong to whichever implementation you are calibrating.

For the concrete failure patterns that make a check lie about itself — a filter that
skips the very file it names, a copy that aliases nested state, a payload past the
kernel's per-argument limit — see `references/silent-failure-patterns.md`.

For a suite that has to be correct under real CI concurrency — shared host ports, global
state, platform-owned semantics, timeout budgets, quiescent teardown, and the fixes that
mask a flake instead of closing it — see `references/test-reliability.md`. The CI half —
freezing the evidence, the classification, the smallest reproducing topology, and what a
diagnosis-only request authorizes — is `references/flake-diagnosis.md`.

For a verdict that has to rest on claims the gate can re-run — the closed proof vocabulary,
the per-claim control, the admission classes, the `unprovable` state, the determinism
checklist, and how to instruct a producer model to emit a usable proof — see
`references/proof-carrying-claims.md`.

For deriving a threshold once the score comes from admitted claims — the labelled corpus of
*reviewed* runs, matching seeded defects to confirmed claims, the five refusals, and the file
layout for two coexisting scales — see `references/calibrating-from-runs.md`.

## When to Use

- Designing or changing a scoring model, weight table, normalization curve, or
  pass threshold.
- A gate's threshold or curve parameters are hardcoded guesses.
- Turning analyzer output (findings lists, scalar metrics) into a bounded score.
- Building a fix-and-re-review loop that must decide when to stop and hand over.

## Rules (always on)

**Absence is not cleanliness.** An analyzer that did not run must report "did not
run", never zero findings. A missing tool recorded as `0` reads as a clean bill of
health, and that is the worst possible failure mode for a gate — it silently
converts *unmeasured* into *passed*. Carry the distinction in the data structure
(`ran: false`), and let a coverage fraction (how many expected analyzers actually
ran and parsed) carry that uncertainty into the final score rather than inventing
a value for it.

**An inapplicable check is a vacuous pass, not a missing tool.** The rule above has a mirror image. When a probe's *precondition* is absent — no CI workflows to cache, no manifest to pin — the property it asserts is vacuously true, so reporting `ran: false` counts it as missing and depresses coverage on an artifact that had nothing to fix. Measured: two new CI-hygiene probes reported "did not run" for a repository with zero files under `.github/`, which dropped the coverage fraction on the one clean member in the sample and pushed it below the threshold. Distinguish three states, not two: **ran**, **could not run** (a tool is absent — this is a gap), and **did not apply** (the input is absent — this is a pass with a reason). Collapsing the third into the second makes a clean artifact look under-measured.

**A rate with an empty denominator is `null` with a reason, not `0`.** The same rule one
step out, where the missing input is a person rather than a tool: a reported rate
(acceptance, addressed, usefulness) whose denominator is zero because nobody has supplied
the judgements is *unmeasured*, and `0.0` reads in a table exactly like "nothing was
accepted". Print `null`/`no data`, name the field and the values the reader must write to
fill it, and state coverage beside the rate so a 100% over one judged finding out of forty
does not read as a clean sweep. A supplied value outside the known set is a mistake to
report, never a category to coerce it into — coercion silently invents a measurement.

Before accepting "this metric needs a new signal", read the artifacts the pipeline already
writes: a per-finding status field or a per-round score list usually holds it, and the gap
is a missing computation rather than a missing input. Say which of the two it was.

**A verdict the gate does not compute is a verdict it cannot make.** Every claim must
be derived from the artifact on this run. A verdict written as a literal —
`claim("...", "PROVEN")` with no check behind it — is indistinguishable in the output
from a claim that was actually tested and held, so it awards the strongest possible
verdict for free and certifies nothing. This is the failure mode a gate exists to
prevent, committed by the gate itself, which is why it survives review: the report
looks like evidence. When a property genuinely cannot be read from the artifact, the
honest verdict is an explicit unknown with the reason — an honest gap is worth more
than a fabricated pass.

**A verdict is one rung, not a certificate: publish the ladder and block the claims above
it.** "Satisfied" answers a question about one artifact, and a reader extends it to the
adjacent ones — published, CI-passed, merge-ready — that the run never observed. Project the
run's own files into an ordered ladder (recorded → measured → recomputed → calibrated → CI
observed → merge-ready → published), each rung allowed only when evidence exists and otherwise
BLOCKED with the reason and what would open it; then *generate* the outward-facing text — PR
comment, report, badge — from that projection, so a claim the evidence does not support cannot
appear in prose at all. Two clauses keep it honest: a rung opens on a **receipt keyed to the
artifact's identity** (a CI result for a different commit is not evidence for this one), and a
blocked rung that needs two things names both ("merge-ready needs a satisfied verdict AND an
observed CI result") — `blocked` alone sends the reader to the wrong problem. A rung that does
not apply is `not_applicable`, never silently open.

**A false alarm is a defect in the gate, not a finding about the artifact.** A gate
that exits non-zero on a valid input teaches its reader to ignore it, and an ignored
gate is worse than no gate because it still consumes attention. Check the checker
against a known-good input before trusting a red result: a relative-link check that
tests the raw target reports every anchored link broken, because the fragment is not
part of the path. When a check fails, the first hypothesis is the check.

**Bound everything the gate executes.** A gate with an unbounded child process hangs
forever, and a hung gate is indistinguishable from a slow one — the run never reports
at all. Pass an explicit timeout to every subprocess a gate spawns. When the cap fires
the producer returns **nothing**, and the gate's only honest answer is the same one a
missing analyzer gets: no verdict, said out loud — never a pass.

**Bound the assembled input, not only each part.** Per-file skips and a per-reference
cap leave the total prompt unbounded: a diff plus its function context can assemble to
tens of kilobytes, and a producer that will not answer that size burns the full per-call
timeout on every retry — measured, one 900 s timeout plus its retry turned a single
sample into half an hour with no output and no error. Compute the assembled size before
the call and refuse over a named limit, printing the size and the narrowing to apply (a
smaller `--base`), so the failure is immediate and explainable instead of a silent stall.

**A per-call timeout does not bound a RUN; bound the run, and make what it never reached a
recorded non-pass.** Slicing a large input multiplies calls, so `N units x (timeout + retry)`
is hours even when every call is bounded. Add a run-level budget in **seconds** (machine speed
varies; a unit count does not bound wall time), check it before starting each unit, and let the
unit in flight finish rather than cutting a sample mid-answer. Record every unit never started
with its own reason, and make the verdict non-PASS; when another finding already made it
`INCOMPLETE` or `FAIL`, append the unreviewed units to the reason as well — a summary that
names only the first cause hides the missing coverage, and the reason is what a reader acts on.
Probe the instrument before the run (a one-line prompt with its own timeout; required binaries
fail, a missing sandbox warns and names which proof kinds become `UNRUNNABLE`): a producer that
answers a 20 s probe may still never answer a 5 KB review prompt, so the probe measures
liveness, not capacity. Before trusting a newly selected profile or reasoning level, plant
a defect it must find: an empty answer from an unvalidated instrument is unproven, not
clean. `references/bounded-runs.md`.

**A producer that ran out of time leaves artifacts on disk anyway — re-run COLLECTION
before re-running the producers.** A gate cannot score what its producers never wrote,
but "never wrote" is often "wrote after the collector ran": the collection step is
deterministic and cheap, the producers are slow and paid for, and the two race. Measured
on a five-sample review run: five reviewer samples hit a 1800 s per-turn cap (`rc=124`, distinct from
the `143` a lifecycle kill leaves and the `126` an argv overrun leaves), the merge that
runs at round end read 0 of them and wrote no dimension files, so the gate reported it
could evaluate nothing — and re-running the *merge verb alone* recovered 4 of 5 samples
into a real verdict. Reach for the deterministic half first, widen the producer's own
`--timeout` for the next round, then read the gate's exit code rather than the summary.

**Where the gate runs decides who may trigger it — never the guards inside the trigger's
file.** A gate that executes on your own hardware must not be reachable by a ref an
outsider can write. `pull_request` runs the workflow file **from the PR's merge commit**,
so on a fork-controlled PR the file is attacker-authored: an `if:` that skips forks is
deleted by the fork that edits it, along with every other control written inside it
(github/docs, "Securely using pull_request_target"). A public repository makes that
reachable by anyone who can open a pull request, and the payload runs as that job's user
on a machine that is not disposable. The trust boundary is therefore the **trigger set**:
the self-hosted job takes `push` to the protected branch plus manual dispatch, and any
PR-triggered job runs on hosted infrastructure instead. A read-only token, a commit-pinned
checkout, `persist-credentials: false` and refusing flake-supplied substituters all
constrain honest runs only; a repository fork-approval policy is a real control but the
tree cannot assert it, so name it as a precondition rather than implying the workflow
enforces it. Verify the exposure claim before writing the boundary into a comment —
`curl -s https://api.github.com/repos/<owner>/<repo> | jq -r .private`.

**Mock the boundary, never the pipeline.** Mock only the expensive or non-deterministic
edge — the model adapter, the network, the clock — and keep the registry, the persistence and
the dispatch path real. A hand-rolled stand-in proves the bridge moves bytes, not that the
shipping tool behaves as asserted, and the fixture it needs becomes a second definition of
the system that must be updated with every real change. For a gate that shells out to a host
binary a distribution cannot ship — a browser, a cloud CLI — pin the invocation as a function
the test can call (`argv(driver, url, out)`) and drive a stub implementing that same contract:
the logic is then gated on machines where the binary is absent, and the stub cannot drift from
the real call because both are built by one function.

**Every acceptance rule needs a negative control.** A check that cannot fail is not a
gate: a predicate that silently matches everything passes its own test, and that pass
looks identical to a real one. For each rule, drive one deliberately invalid input
through the **same** code the gate calls and assert it is rejected — plus the valid case
beside it, so a predicate stuck on `false` fails too. Exercise the boundary rather than
inferring it: a length rule is tested at the limit and one past it, because a `>=` written
for `>` rejects the last value that fits, and no real artifact sits on the boundary. A
copy of the predicate written for the test proves nothing about the gate — extract it, so
the test and the gate call one function.

**Every parameter that changes the verdict must be operator-settable and recorded.** A threshold, weight, floor,
freshness bound or cost divisor buried in code is an unversioned policy: the user cannot vary it, the run cannot
record what it used, and a later comparison silently mixes two policies. Expose it as a flag, config key or
environment variable, echo the effective value into the run artifact (`policy` block), and test that a non-default
value changes the result. Guards that do not express a decision — a minimum row count that refuses a truncated
page, a unit-sanity cap, display formatting — stay fixed but must be named and documented as guards.

**An exemption needs two controls, not one.** A control proving something is *allowed*
(`scripts/*.sh` is a glob, not a dead pointer) passes just as well when the rule has stopped
firing entirely, so alone it is vacuous. Pair it with a positive control through the same
entry point — a concrete dead path that must still be rejected — and drive both through the
entry point production uses. Measured: two exemption controls called a single-file helper that
never ran the tree-level pointer rule, so both passed for a rule that was not executing; the
paired positive control returned an empty violation list and named the mistake.
**Count defects, not (rule, defect) pairs.** Two rules can catch one fault — a per-file check
and a tree sweep both see the same CRLF file — and an undeduplicated report sends a fixer
chasing a count that is one file. Dedupe on the reported line, not on the rule.

**A finding is prose; a claim is a proof the gate re-runs. Demand one per blocking claim.**
Nothing in a sentence about the code can be executed, so a gate that accepts a prose finding is
accepting an opinion with a location attached. Require each claim to name a check from a **closed
vocabulary the gate owns** — kinds declared in one data file, each with typed parameters, each
executed by the gate itself — returning exactly `supported`, `refuted` or `unrunnable`. Three
things must hold before any of it is trusted. `unrunnable` is a third outcome and never folds into
`refuted`: no browser, no server, no toolchain proves nothing about the code, and treating it as
"false" lets a missing tool certify the artifact. A parameter outside the declared set is
`unrunnable`, not ignored — an executable off the project's toolchain, a URL off loopback —
because otherwise the proof quietly becomes "run something arbitrary and report success". And the
contract is data, with a test asserting the executor registry and the contract agree in **both**
directions, so a kind cannot exist in one and not the other. Apply the same both-directions test
to every closed vocabulary the contract shares — severity included: measured, three copies of the
severity list existed (domain, parser, differential tool) and no test compared any pair, which is
exactly the duplication the proof kinds were already guarded against. A **blocking** claim additionally
needs a control the gate requires to be **refuted** — the claim-level form of the rule above: a
pattern matching nothing anywhere supports both "this symbol is unused" and "this symbol is
everywhere". Admit three classes and no more: `proven` (may lower a score and block a merge),
`unproven` (may not lower a score and must not be reported as a defect — but it **does** stop
certification: an unproven blocking claim makes the verdict **`unprovable`**, neither satisfied nor
failed, naming the claim that stopped it), `refuted` (drop the claim and charge the producer). The
asymmetry is the point and it is worth stating plainly: only `refuted` clears a blocking finding, so
a claim is outstanding until its proof fails, and a confirmed defect and an unsettled claim stop a
merge for opposite reasons — one is a thing to fix, the other a thing to settle. A prose
`falsifiable_check` the producer supplied is preserved as the candidate for a proof, never counted
as one. An empty proof list is the same distinction one step in: with no outcome at all the
finding is `unsettled`, never `refuted` — nothing contradicted it, and a fall-through `else`
that maps an empty list to the negative branch certifies a claim nobody checked.

**Derive the control when the producer does not supply one.** A control the producer writes about
its own check is a promise, and a producer often writes none at all — so the orchestrator builds it
from the proof. Two shapes, because there are two kinds of check: a **tree-reading** proof
(`absent`, `present`, `command`, `json`) is controlled by running the same check against the **base
revision** (it holds here and not there), while a **runtime** proof (`dom`, `http`) cannot be
re-run against a tree and is controlled by the same observation with the opposite expectation; a
`diff` proof by the same line with the opposite mode. Two mechanics decide whether it works: rebase
every absolute path under the root into the base root, or the control executes the *defective*
tree's own script and proves nothing; and materialise the base with `git archive` rather than a
worktree, because a base tree carrying `.git` answers `git` questions about the wrong repository.
Never replace a control the producer did supply — fill the gap, record which happened
(`control_source`), and leave a control-less claim `uncontrolled` when no base revision is given,
because the absence of a control is not a control.

**A proof of the right thing in the wrong place is not evidence.** Every proof names a subject — a
path, a URL, a diff line — and every claim names a location. Compare them before accepting the
proof: measured, a claim about a committed credential at `src/svc/__init__.py:4` was proven by a
`present` check over `src/svc/client.py:9`, and because the check passed and its control failed,
adjudication confirmed it and it blocked a merge. Nothing in the proof machinery compared the two, so
any true statement about the repository could be attached to any finding. Demote a mislocated proof
to `unsettled` rather than refuting it — the claim may still be true, it is simply not what was
proven — and leave proofs that name no path (`command`, run over the tree) to their control, which
is the rule that catches a check that cannot fail. Normalise the path by removing a leading `./` and
nothing else: `lstrip("./")` strips **characters**, so `../a.py` becomes `a.py` and a proof from
outside the tree is accepted as being about a file inside it.

**A proof's REACH decides whether it can see the claim at all — check the range before the path.**
`present`/`absent` often name no path at all; they carry `include` and `exclude` patterns, and an
absence proof whose `exclude` names the claimed file establishes something about the *other* files,
not about that one, while an `include` list that does not cover it never looked there. Compare the
claim's path against both lists and demote to `unsettled` with the exclusion named in the reason.
Measured: six passes reported a seeded complexity defect 6/6, and three of the six were confirmed by
`absent` proofs whose exclude listed the very file claimed — with the reach check the honest count
was 3/6, and the rest are reported rather than certified. One level deeper, and worth stating
explicitly: evidence can reach the right file and still not observe the property claimed — an
absence proof over other files says nothing about complexity. When the chosen kind cannot observe
the class of claim, the state is `unsettled`, and the durable fix is upstream in the producer: say
in the prompt which kind measures which property (`ruff --select C901` for structure), because a
producer that guesses will keep choosing a proof that cannot work.

**A score derived from what the producer admitted rewards silence — check it against an
independent observation.** Once the number comes from evidence the producer supplied (admitted
claims rather than its own self-assessment), a producer that reports nothing scores perfectly and
nothing blocks, because there is no claim to block on. The analyzer ran and found a committed
credential; the reviewer said nothing; the aggregate is 100 and the run looks clean. Cross-check
the producer against the toolchain's own record: if the analyzers observed a defect and the run
settled **no** claim at all, the verdict is `unprovable` — not satisfied, and not failed. Leave the
number at 100 (it is honest about what it measured) and let the verdict carry the gap, so the
score keeps its meaning and the run cannot be certified on a silence.

**Scope that cross-check to findings that could block.** "The probes saw a defect" is too broad a
predicate when any finding counts: a clean tree still yields low-severity nits (an unused lambda, a
missing architecture doc), so a producer that correctly stays silent about them is scored
`unprovable` and its rung is discarded from the corpus. Measured: two `low` probe findings turned a
clean rung into `unprovable` with an aggregate of 100, cost a six-run corpus one of its three clean
members, and the derivation refused. Count only findings at a severity that could block
(`high`/`critical`), and treat an **unlabelled** finding as blocking — a probe that names no
severity is not evidence the producer was entitled to ignore it. Measured before the rule
existed: probes found two defects, the reviewer settled none, aggregate 100.0, verdict clean.
**Partial silence is the same failure attenuated, and the score rewards it.** Caps and penalties
attach only to claims that were **confirmed**, so a producer that finds a fraction of the planted
defects keeps the rest of its score: measured on one corpus, a rung with 2 of 16 defects detected
scored 58.79 while a rung with 4 of 4 scored 53.56 — missing twelve defects was worth five points.
Guard the calibration set with a **minimum detection rate per member**, refuse to derive from a
member below it, and make any exclusion explicit and recorded in the manifest's provenance rather
than silently dropped — otherwise the producer's blind spots become the threshold's policy.

**Severity is a property of what was detected, not of the producer's description of it.** When one
defect is labelled `critical`, `critical`, then `medium` across three passes of a single tree, every
cap that hangs off severity turns that disagreement into a score swing — and no amount of repetition
removes it. Derive severity from the evidence instead, in one declared rule table (keyed on a tool,
or on the content that was matched) where each rule states *why*: a committed credential is critical
because it is an access grant, not because of how the finding reads. Three clauses decide whether this works. **Authority depends on how much the rule knows.** A rule
that names the defect class — a cited credential literal, a quoted `SyntaxError` — is **exact**: it
settles severity in both directions, because the class is not a matter of taste. A rule that only
knows *which tool ran* is a **floor**: it may raise the producer's label and must never lower it,
because over-stating makes the gate stricter while under-stating lets a real defect through. Both
halves are measured. Applied as a plain override everywhere, evidence downgraded a `critical` claim
to `low` because that claim's proof happened to invoke a lint tool. Applied as a floor everywhere,
one syntax error proved *through a linter* kept the producer's label — `critical`, `critical`, `high`
on one line — because the tool's own `low` could not lower it and no rule named the class. And evidence is **content as well as tool**: a `present` proof
that cites the credential's own value is evidence even though it names no executable, so a table
keyed only on tool names leaves that proof with the producer's label and reintroduces the very flip
the table exists to remove. Where no rule covers the evidence the producer's label stands, and the
disagreement it then shows is a real finding — report it rather than inventing a rule to silence it.
**Scope each rule to the artifact it is about, and let corroboration govern the CAP rather than the
block.** Two ways this table goes wrong, both measured. A content rule keyed on a pattern fires on
a *command's stdout* as readily as on a citation: `ruff format --check` echoed the credential it was
reformatting, so a formatting finding was stamped `critical` by the credential rule and produced the
corpus's lowest score. Content rules apply only to proofs that **cite a line** (`present`/`absent`,
or params carrying one) — a citation has a subject, a tool's output is whatever it printed. And
authority over severity is not authority over the verdict: keep **blocking** on the asserted
severity, because a block that should not have been raised is visible and arguable while one that
was never raised is invisible, and let **corroboration** govern the **cap**, holding an
uncorroborated `critical` at `high` so an opinion cannot set the numeric ceiling. Measured: that
single split moved the outlier pass from 52.49 to 58.72 and the six-pass spread from 15.59 to 9.36.

**A measurement that reports a miss is a claim about your matcher until the producer's own output
says otherwise.** A seeded defect is a **block** of lines, and a producer may cite the offending
line inside it rather than the block's first line; comparing a point against a point records a real
detection as a blind spot. Record the span from the same template that plants the text (one home,
so the manifest cannot drift from the tree), compare the two ranges for overlap, and backfill
manifests that stored only a start. Then, before writing "the producer never found it", open its raw
artefact for that location: measured, three passes had each reported the defect at the seeded
block's second line, and the corpus had scored all three as misses — the blind spot was the
measurement's, and three passes of evidence said so the whole time.

**The verdict artifact is a function of the tree: no clock, and no caller-supplied result.**
Recompute the gate even when the caller hands you its verdict — a ladder that trusts the caller's
arithmetic can be opened by passing the right dict — and report the **recomputed** numbers, not
the ones you were given; echoing the caller's dict while judging the recomputed one is the subtle
version, where the summary agrees with a verdict nothing enforced. Three mechanical traps in the
same family: candidate ordering must be **numeric** (`round-10` sorts before `round-2` as text, so
the newest attempt is silently skipped, and a string sort fails quietly rather than loudly); a
caller may point at any level of the run, so resolve the root by walking to the marker file
instead of trusting the argument's depth; and two builds over one tree must be **byte-identical**
— the single test that covers clock use, set-iteration order, and every input you forgot to pin.

**Wire a new artifact in as a stage, not a stamp.** The cheapest integration reads the new file at
the end and copies a field into the output: no failure path, so a missing or malformed artifact
yields an output that looks complete and is indistinguishable from a computed one. Give it what
every other stage has — separate outcomes for **absent**, **unreadable** and **empty** (three
different facts, and "empty" is the one most often read as clean), a value that is recomputed
rather than passed through, and a test that drives the degraded case. Name the field for what it
is: a `snapshot` of a later-recomputable quantity, never a `verdict`, or the next recomputation
reads as a contradiction instead of as a second measurement.

**A stage that does not decide anything must say so in its own artifact.** Landing the computation
before the wiring is the right order — it keeps the diff readable and measureable — but the output
then sits in a directory beside files that *do* decide, in the shape of a verdict, and a reader will
take it for one. Write the mode into the artifact and into the human summary (`enforced: false`,
"this report does not change the verdict"), so nobody reads "nothing is unsettled" as "the gate
passed", and so the eventual flip is a visible change in the output rather than an invisible change
in meaning.

**Filtering a blocking list is not the same as deciding with it.** When a stage splits findings
into `still_blocking` and `unresolved`, every predicate that used to read the whole list now reads
a subset — and the subset is empty in exactly the case that matters, because a run whose only
blocking claims are unsettled looks identical to a run with no blocking claims. Measured: the
first wiring moved unsettled claims out of `blocking`, recomputed `satisfied` from what remained,
and **certified** a round carrying two unsettled critical claims; the unresolved list was recorded,
printed, and consulted by nothing. After any such split, re-read every consumer of the old list and
make the new one fail satisfaction in its own right.

**Record the enforcement mode where every consumer that recomputes can read it.** A verdict is
recomputed by the gate, by the claim ladder and by any manual re-run. If the mode travels only on
the invocation, a re-run silently recomputes with the default and disagrees with the run it is
auditing — and the ladder reports that as a mismatch rather than as the mode difference it is.
Write it into the run's own metadata beside the other facts the harness owns, and have all three
read it back.

**The strict verdict is the default; laxity is the opt-out, named after its effect.** A default that
needs a flag to be strict *is* a lax default, and a verdict must not change meaning depending on an
argument nobody remembers. So ship enforcement on (`--allow-unproven` to reproduce an old score,
never `--require-proof` to be honest), name the opt-out for what it does rather than what it skips,
and record the mode in the run's metadata beside the other facts the harness owns. Do not price a
correctness property in tokens: the marginal cost of demanding a proof is a prompt section plus
seconds of subprocess when the producer was already running the analyzer. What costs is unprovable
runs — and that is the signal, not the fee.

**Flipping a default is a migration through every consumer, not one boolean.** Inverting a flag
leaves every caller that builds argv from the old name broken, and the break arrives as a
*downstream* error: argparse rejects the unknown flag, the child exits 2 with empty stdout, and the
parent reports "could not evaluate the run" — a message pointing at the input, not the argument.
Grep the old flag name across the tree in the same change; then re-read each consumer of the value
it controls, because a boolean flip does not touch them and they do not fail loudly: the renderer
that prints "2 blocking claims" and lists none (it still read the pre-split list), the claim ladder
that recomputes, the packaged copies of the module, and the fixtures. Triage the failing tests
explicitly — a fixture asserting the pre-flip behaviour gets an in-place opt-out *with the reason it
is testing something else*, a genuine behavioural gap gets fixed, and at least one new test asserts
the new default or the flip is untested at exactly the point it changed.

**A summarising stage reads the set the gate scores, not every file that looks like findings.** A
round directory holds both the raw producer outputs and the merged files the gate reads; a stage
that globs for anything with a `findings` key adjudicates every claim twice — measured, 30 records
for 25 findings — and every count downstream of it is inflated while the run looks healthy. Prefer
the merged set when present, fall back to the raw inputs only when it is not, and say which set the
stage used in its own artefact.

**A stage that preserves N inputs must not be followed by one that reports the first.** A merge
keeps every sample's wording so a reader can see the disagreement; a later stage that projects
`claims[0]` into the final finding — and the artefact that copies that field — silently drops the
rest, so the merge's guarantee holds only for an intermediate object nobody reads. Carry the full
tuple into the report (or join it), and assert the final artefact contains every wording the merge
kept. The general shape: whatever a stage promises to preserve, a test reads the LAST artefact,
not the stage's own output.

**A test whose expectation was copied from the code's output pins the bug.** An assertion
written by running the code and pasting what it returned certifies the implementation, not
the contract — so an off-by-one, a mangled path or a wrong axis survives a green suite
forever. Derive the expected value from the *fixture* (the line the token is on, the bytes
in the file) and state the convention it encodes; when a test and the docstring beside it
disagree, the test is the thing that lied. Same rule as the negative control one step out:
a test that cannot disagree with the code is not a test.

**A gate can own the copy-vs-source invariant.** When a repository ships a copy of
another tree, compare the copy against its source byte for byte, resolving the source
from the repository's own location rather than a machine path. A copy drifts silently
and the drift is invisible until something fails at runtime; the comparison turns a
latent divergence into a red gate on the run that introduced it. Report the differing
names, and treat a file present in the copy with no source as a second class of drift,
not as a pass. **When the gate reports drift and the copy is the better version, promote
the copy into the source and re-sync** — an unattended writer can patch a deployed mirror
in place, and both wrong reactions are silent: editing the copy leaves the source stale,
and re-syncing discards the work. Establish that the reported difference is the only one
(so the promotion is a faithful copy), move it to the source, re-sync, and confirm the
gate now reports clean. A mirror is never the place to fix anything.

**Density, not raw counts.** Normalize findings by size, per KLOC. Absolute counts
punish large repos: a 100-line file with 5 findings and a 10,000-line repo with 5
are not equivalent, and a count-based curve scores them identically. When the size
is unknown, fall back explicitly and say so in the output — never normalize by a
number you did not measure.

**A calibration ladder must vary the one thing you are calibrating, or it measures the other
thing.** Rungs that add files to raise the defect count also raise tool coverage, so the
deterministic half moves for a reason unrelated to the defects: measured, `det` rose 6.8–13.7
points per dimension between the clean rung and the sixteen-defect rung, and the defective rung
**outscored** the clean one (43.52 against 42.36) — no threshold can separate that. Seed defects
*into* the base's existing files so file count, stacks and coverage are identical across rungs;
with that change the same corpus separated by 21.6 points. The corollary is mechanical: when a
guard or floor divides by a quantity, apply it to **every** term that divides by it — a size floor
given to the claims term but not to `det` left a 56-line tree judged denser than a 16-defect tree,
and extending the same floor to both moved the separation margin from +7.8 to +20.4.

**A corpus records the question and the draw, or its points are not comparable.** Two mechanics,
both cheap and both easy to leave out. A **harness digest** — a hash over the prompt template, the
profile, the producer's reasoning effort, the dimensions, the default goals and the **proof vocabulary** (severities and kinds),
written into every run's metadata — so a prompt edit or a contract change invalidates the old
points *visibly*: pooling runs made by two different instruments averages answers to
two different questions, and every number looks fine while it happens. (Assert the digest is stable
across identical runs **and** that it changes with the profile, or an invariant digest makes two
different producers look identical.) And a **repeat id per member** — `level-<N>-run-<k>` — with one
tree built per rung and *shared* by its repeats, so what varies between them is the producer and not
the ladder. A manifest that cannot express a repeat cannot produce n>1, and one draw per class makes
every interval a point dressed as a range.

**A corpus member reviewed as a diff needs history, and a sweep must resume.** A one-commit tree
has no base revision, so the run refuses and the member reads as a broken corpus: commit a
scaffold first, then the change under test. Sampling must survive a failure without discarding the
members already paid for — skip a member that has a verdict, write the results file after each
one, and rename rather than delete a run made under the previous instrument, so the old result
stays as evidence that the fix was needed.

**A pinned fixture is re-pinned by reading its diff, not by accepting it.** The suite going red
after a deliberate change is the suite working; `--update` on reflex is exactly the failure the pins
exist to catch, and refusing to update is the other one, because a test that fails forever gets
ignored. So print the diff first and confirm **every** moved field is one the change should have
moved — a scoring change that moves only `det` and the scores fed by it, with no weight, threshold
or calibration rows, is the change you made; a stray row is a second change you did not intend. Then
re-pin in the same commit, and say in the change description which fields moved and why, so the next
reader can tell an intended re-pin from a regenerated expectation.

**Evidence that lives outside the tree is not evidence.** A calibration corpus written under a temp
directory is gone at the next cleanup, and with it the only record of what the numbers meant —
measured: a twelve-run corpus behind a twelve-for-twelve verdict survived one afternoon, and the
committed manifest kept the scores but not the runs behind them. Freeze the reference *before* a
rewrite or a recalibration: record the tag, its commit and a sha256 per fixture in one file,
generate that file from a maintainer script that is the only writer, and make the acceptance a test
that recomputes every hash and replays the pinned output — plus one mutation that corrupts a
recorded hash to prove the freeze can go red.

**One layer owns normalization.** The component that computes the score owns the
curves, the weights and the threshold; a per-dimension rubric emits findings and a
judgement score, nothing more. When a rubric restates its own formula (a Hill
curve, a within-category weight table), the gate's real parameters override it
silently — so the rubric is instructing its reader to compute a number nothing
reads, and the two drift. State the ownership once, in the gate, and delete the
copies. The same applies to any spec the implementation does not enforce: an
unenforced instruction is not a soft requirement, it is a false one.

**Report two independent requirements independently.** A score threshold and a "no
open blocking findings" gate are separate conditions; a run can clear one and fail
the other. Never render a value that is *above* its minimum as "below the minimum"
because a different gate blocked it — that sends the reader to the wrong problem.
State each requirement against its own evidence.

**Reserve an exit code for "could not start", and make every start failure reach it.** A gate that
exits 1 for a proven defect, 2 for missing evidence and 1 again for a typo in its own arguments
tells CI the tree is broken when the tool was. Keep the verdict codes exclusive (0 pass, 1 fail,
2 incomplete) and give startup its own (3): a bad run id, a missing config, a path outside a git
repository, an unreadable claim registry. A library error that escapes as a traceback exits 1 by
accident, so wrap the boundary (`except ValueError: raise ReviewError(...)`) and probe the bad
inputs — `--run-id ../x`, `--samples 0`, a missing registry — asserting the code and that the
output is one line rather than a stack.

**A pooled parameter must exclude degenerate members.** When deriving one shared
constant from many components (a median density across analyzers, a typical scale
factor), members sitting at a floor or sentinel value drag the pooled statistic to
that floor and collapse every score. Exclude them from the pool while keeping their
per-component value for per-component scoring.

**A curve must be anchored on the population it scores.** A scale parameter (`d*`, a
half-point, a typical density) derived from one producer and applied to another's output is
two different measurements sharing a name. Measured on one repository: the analyzers reported
under 2 findings/KLOC while the agent reviewer reported 4.4 at one sample and 57 at five, so
the curve returned **1.66** where a correctly anchored one returns ~50. The term was
penalising the reviewer *for finding things*, and it dragged every dimension into the 30s, so
no member of any class could reach the threshold. Derive each parameter from the same producer
whose output it scores — and when that producer is an agent, the labelled set must be **agent
runs at the shipped configuration**, not analyzer runs and not a synthetic defect ladder. The
diagnostic signature is unmistakable and worth memorising: **every member of every class
scores far below the threshold at once**, and lowering the threshold does not help because
the whole population is compressed. Reach for the anchor before the threshold.

**A fallback that borrows another population's anchor must be reported, never applied
silently.** An uncalibrated parameter needs a default so the tool still runs, but a default
that is really a different measurement makes the output wrong in a way nothing announces —
and "no anchor yet" then reads exactly like "measured, and it scored 61". Fall back *and*
append the gap to the same channel an analyzer uses when it did not run, so it surfaces
wherever the score is printed. Ship the fallback inert (no anchor written ⇒ behaviour
unchanged) so existing fixtures keep their pinned verdicts until a real anchor exists.

**A "known-good lands mid-scale" anchoring rule is a discrimination rule, not an absolute
one.** It pins that member's contribution at **50 by construction**, which in a weighted
composite caps a pristine member near 81 — so nothing can clear a higher threshold and every
score drops together. Before adopting such a rule, compute what a pristine member scores under
it: if it is not near the top of the scale, the rule belongs only in the separating
comparison. A rule that drops every member and passes none is a rescaling, not a calibration.
See `references/calibration-evidence.md`.

**Derive a classification threshold from the labels, not from the sweep.** Sweeping
for the value that best separates the two classes is the mistake that looks correct
and is not.

**Calibrate on the scale the gate enforces, not on an intermediate one.** A calibration
that measures an intermediate quantity (`score_from_densities`) while the gate compares a
*hybrid* aggregate against the threshold derives a number for a scale nothing checks. The
two look interchangeable — both are called "the score" — and they are not. Confirm which
expression the gate actually evaluates before deriving anything, then derive on that one;
otherwise the threshold and its evidence are two different measurements sharing a name.

**Changing what a number is derived from invalidates the threshold derived from the old
derivation — record the scale and refuse the comparison.** A threshold is a statement about a
distribution; swap the score's source (a producer's self-assessment for a count of proven
defects) and the same number means something else, while the threshold looks unchanged and the
comparison still runs. Carry the scale in the calibration manifest (`"scale": "deterministic"`),
carry the run's own source in its result (`score_source`), and give the mismatch its own verdict
state (`uncalibrated`) instead of letting it fall through to pass or fail: the score is still
reported, nothing is certified, and the reason names the command that would fix it. A run that
cannot be compared is a different answer from a run that failed, and collapsing the two hides
which one happened.

**When the labelled classes overlap, derive the equivalence band — not a gap.** A
*separating* threshold exists only if the worst known-good member scores above the best
known-bad one; measure both before deriving anything. When they overlap, the max-margin
line falls between two members of one population and the verdict turns on noise, so no
point estimate is recoverable — and that is normal, not a defect in the model: real
repositories are not defect-free, so "known-good" and "known-bad" differ in *density*,
not in kind, and any weighted mean of quality tracks density. But "no threshold is
derivable" overstates it, and leaving it there makes the parameter look unjustified when
it is not. A threshold needs the set of values that yield **identical verdicts on every
sample**, and that set is computable: `(max(defective), min(clean))`. Report the interval,
its width, and where the shipped value sits inside it — the distance to each edge. Every
value in the band is then a defensible policy, so the choice is a decision whose
consequence is *measured* (none, on that evidence) rather than an open question. Do not
quietly lower the threshold to make more members pass — that replaces a stated policy with
an unstated one, which is what the write-up exists to prevent. **The band is provisional
until you have tested its weakest input** — a member landing outside it reopens the
question, and so does the member nearest the line turning out to move more between runs
than its distance to it; the next two rules are that test, and they are not optional before
the word "proven" is written down.

**A band is only as tight as the class that fails on the thing you are calibrating.** A member
that fails on a separate criterion — an open blocking finding, a check that did not run —
carries no information about where the threshold belongs: it fails at every value, including
one below its own score. When most of the failing class fails that way, adding members cannot
narrow the interval, and the honest report is the **one-sided bound you have** (an upper bound
from the cleanest member, no floor) plus the population ratio. The stronger claim is worth
stating: if the aggregate is load-bearing only for members with no blocking findings, the
threshold **cannot be calibrated by collecting more repositories at all**. Worked numbers and
the screening procedure: `references/calibration-evidence.md`.

**When the clean class is empty, stop measuring and change what the parameter is for.** A
sample of eight respected real projects, scored at the shipped configuration, produced
**one** clean member: the other seven each carried
3–54 confirmed blocking findings — an action pinned to a mutable tag inside a job holding a
cache write token, a privileged trigger with no author guard, a fetch whose integrity hash was
optional. That distribution is a property of common practice, not of the sample, so further
candidates reproduce it. The decision that follows is not "lower the threshold": it is that
the numeric threshold was never able to be absolute, and the binary criterion already is.
Keep the number as a **regression detector** against each member's own history (a baseline
mode usually already exists) and say plainly, in the docs and in the tool's own output, that
the binary gate carries the absolute judgement — a reader who assumes a passing score is a
clean bill of health will otherwise treat a compressed scale as a verdict.
**Count only members you actually scored.** A candidate that was pre-screened for the
dominant failure class and then never measured belongs in the population description as a
separate line, never folded into "N reviewed": the same figure restated in the doc, the
manifest and the run record drifts in exactly that direction, and the run record -- which
says `not reviewed` beside that member -- is the authority when the three disagree. The
overstated count is not cosmetic: it is the denominator a reader quotes back, and it can
contradict the very conclusion drawn two paragraphs later.
**When one count appears with two values across copies, suspect two populations before
arithmetic.** The copies disagree because they describe different sets that were never
named: a ratio attributed to "eight repositories" in four places while the document that
lists them names nine, and the ninth is a member the other analysis does not contain. The
fix is not to pick the number the majority of copies carry — it is to name the set inline
wherever the figure is printed, so the two figures stop being comparable and start being
what they are. A count without its population is the shape that lets this happen twice.

**A check that lives only in the test cannot prevent the drift it detects.** A policy test
that greps prose for a stale version reports the drift *after* the operation that causes it,
and the operation cannot consult a pattern it does not own — so every release needs a manual
fix that the enforcing check could never have prevented. Put the definition in the code path
that both validates and mutates: one function the checker calls to report and the mutator
calls to rewrite, so the two cannot disagree. A copy of the pattern in the test is a third
definition to keep in step; have the test call the production function instead of restating
it. The general form: when a check and the operation that violates it are separate code, the
operation must own the definition, or the check is a report rather than a gate.

**Probe a band edge with the real gate, never from a printed score.** The comparison is
exact (`aggregate >= threshold`) while the printed score is rounded, so a member displayed
at 89.23 can carry an aggregate of 89.2299… and *fail* `--threshold 89.23`. Both ends of
the interval are open for that reason. Run the shipped gate at the edge and one epsilon
either side, and read the exit codes; taking an edge from the displayed number puts the
boundary a rounding step off, and the error is invisible because the numbers look equal.

**A band built from one observation per member is only as wide as the noise — and the noise
must be measured at the configuration users run.** Each score in the interval is a single
run. If the member nearest the line can move more between runs than its distance to the
line, the interval is not a band and the threshold is a coin flip. Measure repeat-run
spread on that member before calling the band settled, and always quote the distance from
the shipped value to the nearest edge — a member two points above the line sits inside the
noise floor of any LLM-scored gate. Measure those repeats at the **shipped default**, not
at a cheaper one: a calibration taken at `--samples 1` against a shipped default of 5
measures a different gate, and the band it produces describes a configuration nobody runs.

**When the measured noise exceeds the class margin, stop thresholding the aggregate and gate on the
set that does not move.** Repeat-run spread on one identical member can be wider than the gap
between the classes — measured: six passes over one tree spanned 15.59 points against a 10.29
margin, and members landed on both sides of every cutoff inside the band. Repeats do not narrow
that: the spread is not sampling error but the producer reporting a different number of unseeded
findings each time (1, 2, 3, 3, 3, 4 confirmed on the same tree), so more draws widen the observed
range rather than shrinking it. The move that survives is to make the verdict read a **discrete,
reproducible** quantity — the set of confirmed blocking claims — and publish the aggregate as a
trend that no verdict depends on. Two clauses keep it honest: record the basis that produced the
verdict (`certification_basis: claims | threshold`) so a reader can tell a blocking-set pass from a
numeric one, and keep the numeric scale's own guard out of the discrete one — a verdict that no
longer compares a number must not report that it cannot compare one. The acceptance is a command
that prints each member's verdict against its label and exits non-zero on any disagreement, plus
plus two mutations proving it can fail: relabel a clean member, and drop a member's verdict entirely.

**A comparative verdict answers "is this better" where a score answers nothing — prefer it unless the
scoring rules are strict and published.** A number out of 100 asserts a scale, and the only thing
justifying that scale is a derived cutoff; if you cannot state what raises a point, by how much, and
why, then the honest output is a comparison against a **named baseline**. Record each run as what it
established — confirmed findings keyed by path, span and dimension, plus each probe's ran flag and
defect count — then classify the difference and cite the evidence for every entry: **worse** when a
confirmed finding at a severity that would block is new, or a probe that reported none now reports
defects; **better** when such a finding is gone or a probe went quiet; **incomparable** when an
analyzer ran in the baseline and did not run now, because a missing tool finds nothing and "nothing"
must not read as an improvement. Two mechanical clauses make it a gate rather than a report: exit
codes carry the verdict (0 better/same, 1 worse, 2 incomparable) so CI can branch on it, and a test
asserts the module holds no threshold constant at all — the change is only real if no number
decides. Keep any score as a trend nobody gates on.

**A verdict that no longer compares a number must not consult one anywhere — including in the
sentence it prints.** This flips both ways and each looks defensible alone: first the gate printed
`aggregate X >= Y` while never testing the inequality, then a later edit tested it. Both let a
number decide. On a blocking-set verdict, remove the comparison from the computation *and* from the
reason, and pin it with a test that puts a clean blocking set below a deliberately impossible
threshold and asserts the verdict is still certified and its reason does not mention a threshold.

**A recall parameter under-measured biases the score upward, in one direction.** More
samples find more distinct findings; findings feed a density term; higher density scores
lower. So a single-sample baseline is not a noisy estimate of the multi-sample score — it
is a systematically *higher* one. A member that looks clean and passes at one sample can
fail at five while gaining a real blocking finding the cheap run never surfaced. Before a
repository or revision joins the **clean** class, measure it at the configuration the gate
ships; otherwise the clean set is a set of under-sampled runs and every interval derived
from it is an interval over inflated numbers. When the shipped default changes, every
class membership established under the old one is unverified.

**A coverage fraction of 1 is not determinism.** `score = beta*det + (1-beta)*llm` at
beta = 1 removes only the LLM's *self-assigned* score. If `det` is computed from findings
the reviewer produced — a density term, a severity-weighted count — then the "deterministic"
half is a deterministic *formula over a non-deterministic input*, and the number still moves
between runs on the same commit and toolchain. Document what beta actually covers ("the
LLM's score does not enter") rather than "the score is deterministic"; the second sentence
is false and it is the one a reader will quote back when a repeat run disagrees. A spread
A spread measured with beta = 1 is still reviewer variance, not measurement error.

**A term in a weighted blend can be multiplied by zero — measure the weight before claiming the
term has effect.** `score = beta*det + (1-beta)*llm` at beta = 1 makes the second term identically
zero, so changing *what that term is computed from* moves nothing: measured on a real round, a
producer's own 0.00 and a claims-derived 33.06 both landed in a zero-weighted term and the
aggregate was 89.73 either way. Tests that assert the term's own value pass throughout, because
the term is computed correctly and then discarded. Before shipping a new input to a blend, print
the weight's distribution over real runs; if it saturates, the input needs a route that cannot be
diluted — a cap, a floor, a separate blocking condition — and the test that proves it asserts the
**aggregate** moved, not the term.

**Two bands that disagree are usually two samples, not a contradiction.** A stored
manifest derives its interval from the labelled set it was fitted on; an independent
evaluation set derives a different interval from different members, and both can be
correct at once. Before reporting an inconsistency between a recorded parameter and a
documented interval, identify the sample behind each — count the members, name the
extremes — and check whether the shipped value sits inside **both**. If it does, the two
numbers are two measurements of different populations, and the only real defect is a
document that does not say which set produced its figures; state that, and do not "fix"
a number that was never wrong. The reverse also holds: a figure quoted without its sample
is not comparable to anything, so name the set whenever you print an interval.

**A new check is not trusted until you have watched it fail.** For each thing a check
guards, break exactly that thing, confirm the check fails and names the break, then
restore and confirm it passes. A check that cannot fail is indistinguishable from a
passing one in a green run, so this failure mode is silent by construction. Where a check
derives its expectation by extraction — parsing a list out of another file, grepping a
manifest — assert the extraction is non-empty first (`test -s`), or a broken pattern
compares two empty results and passes. **Read the child's status before you pipe it.**
`cmd | tail` leaves `$?` holding *tail's* status, so a check that exits 1 reports 0 and the
mutation you just made looks like it changed nothing — measured twice in one session, once
nearly dismissing a working check as vacuous and once hiding a CLI exit code behind a
`| tail -1`. Capture `rc=$?` on the line after the bare command, or redirect to a file and
read the exit code from the file, and never from a pipeline.
**A check body with several commands has the same mask without a pipe.** `run-a; run-b;
touch $out` exits 0 when `run-a` fails, because the *last* command succeeded, and a build
system that judges the check by the derivation's exit code sees a pass. Start every check
script with `set -e` and put **each command on its own line** — never join them with `&&`.
`set -e` does not fire for a non-final command in an AND-OR list, so `a && b` followed by
`touch $out` exits 0 when `a` fails: the same false pass one layer in. Measured, a claims
check written as `verify && verify --check` reported `73/74 claims hold` and the derivation
still succeeded. When one interpolated string must carry several commands, wrap it in a
subshell — `( ${command} )` — so the list's status is the subshell's and `set -e` sees it.
Prove the whole check can fail by breaking its *first* command, not its last: a check wrapper
ending in `touch $out` passed a failing suite, and every check in the repository had to be
re-run after `set -e` went in.
**When the fix has redundant layers, the mutation has to remove all of them.** A guard
built from two independent filters -- a directory name and a file suffix -- still fires
when only one is deleted, so the test passes and reads as "no teeth" when the truth is
that the mutation was too small. Delete every layer, or mutate the one the test actually
names, and confirm the failure you get is the one you predicted: a mutation that leaves
the code working is evidence about the mutation, not about the test.

**A claim that also lives in code has to change in the code.** Correcting a documented
statement is not one edit: CLI output, wizard text, a generated config comment and the
calibration manifest's own caveats each restate it, and each is a separate copy. Grep the
source for the sentence, not just the docs. A tool that contradicts its own documentation
is worse than either being wrong alone, because the reader cannot tell which to trust.

**Generate the page a claim lives on; do not maintain it.** A document that restates what the
code asserts drifts the first time either moves, and diffing it is a second implementation.
Keep one registry (`id`, one-sentence `text`, the `check` command), render the page from it,
and run `--check <page>` in the gate beside the checks themselves, so a claim with no check
cannot appear and a page row cannot outlive its registry entry.

**Make the mutation a check, not a ceremony.** Watching a test fail once does not survive a
refactor; a table of one-rule breakages run by the gate does. Each entry names a file, an exact
snippet and its replacement; the tool runs the suite against a writable copy and fails if any
survives. A survivor is a decorative test; a stale pattern is reported as a failure, never
skipped, because a mutation that no longer applies proves nothing. **A refactor that moves a
guarded snippet must retarget its mutation in the same commit, and the mutation gate must be
re-run after it.** The mutation table is coupled to source text, so a renamed function, an
extracted helper or a moved computation turns a working mutation into a no-op without anyone
touching the table; the gate only discovers this when it runs, and a green suite in between
certifies nothing. Parse the failure as what it is — the pattern is stale, not the claim — and
retarget the snippet rather than deleting the mutation. A structural check that
reads a source path rather than the running module cannot see a mutation at all:
`Path("src/...")` keeps inspecting the unmutated tree while the suite reports a survivor —
have it read `importlib.import_module(...).__file__`.
Tie each mutation to the claims it breaks, and check **both directions**: a claim may name a
`falsifier` mutation, every declared falsifier must actually fail that claim's check, and every
mutation must fail at least one claim. A claim's `check` must name exactly one pytest node: the
mapper keeps only the first match, so a multi-node check leaves a later-node mutation caught but
reported as `falsifies no claim` — split it into one claim per node. Read failures from the JUnit report — `classname`
`tests.test_x` maps to `tests/test_x.py`, and a missing `.py` silently matches no claim, so a
whole run reports "falsifies no claim" while the mapping is the only thing broken. Fail on an
uncovered mutation as well as on a survivor: a breakage no claim depends on is decoration, and
adding a claim for it is cheaper than deleting the mutation only if the rule is real.

**A differential asserts differences, not equality.** When a rewrite replaces a version with
published results, take the old verdicts as the oracle and write down every expected difference
with its reason — an old gate failing on `falsifiable_check: "see the claim"` and a new one
answering INCOMPLETE are not in conflict, the difference is the rewrite. Fail when an
expectation changes, and print the unmappable vocabulary as a count rather than dropping it.

**The instrument is operator-owned, never supplied by the subject.** A prompt, rubric or schema
read from the repository under review lets that repository choose its verdict: a committed
prompt saying "report nothing" produces a clean run indistinguishable from a clean tree. Ship
the instrument with the tool, allow an explicit operator override, and digest it per run so two
runs are comparable only when they asked the same question.

The same ownership applies to **capability, not only text**: the sandbox mode, the tool
allowlist and the per-proof timeout are policy. A repository under review may narrow them and
must never widen them — a config file that can set `sandbox = false`, or add a binary to the
allowlist, has handed the subject the boundary. Load policy from the operator's side and
intersect what the subject supplies.

**Comment the decision, not the journey.** This user asks for the most concise artifact that
implements the behaviour: a module docstring states the rule it enforces in one to three lines,
comments explain only non-obvious mechanism, and depth lives in generated pages or references
rather than prose beside the code. Verbosity is a defect to remove, not a style to debate.

Mechanics for all four: `references/claims-registry.md`.

**An enumeration is a claim too, and nothing reads it.** A plan document that lists the CLI's
verbs, the milestones, or the shipped features drifts the moment one is added, because no check
compares the list to the code — measured: four verbs stale in one document while the tree's own
command-surface check passed, since that check compares the tree to `--help` and never to the
prose. Diff the list mechanically when auditing a plan (extract from the document, extract from
the source of truth, compare **both** directions, so a removed item shows up as well as a missing
one), and prefer a check that does it over a habit of reading. The same gap hides a release: a
version check that compares the manifest, the changelog and the prose but never the git tag
reports "consistent" for a version that was never tagged — the tag is the one artifact a release
leaves behind, and it is the one a hermetic check cannot see. The same sweep covers a CLI:
walk the parser's own actions and assert every option string appears in the README, so a flag a
user can type but cannot look up fails the gate instead of shipping undocumented.

**Calibrate from labelled evidence and record the result in a file.** An
unrecorded calibration is a guess with extra steps: the moment the manifest is
missing the gate silently reverts to defaults. Ship the parameters alongside the
code, and document that deleting the file restores uncalibrated behaviour.

**A self-hosted gate's trust boundary is the TRIGGER SET, not a guard inside the
workflow file.** GitHub runs a `pull_request` workflow from the PR's merge commit
(github/docs, "Securely using pull_request_target"), so a fork that edits the
workflow deletes any `if:` written inside it — the guard lives in the file the
attacker controls. Measured on a public repository, where anybody can fork: four of
four reviewer samples falsified a narrowing `if:` that had been added for exactly
this reason, and the repository was `"private": false` by the finding's own check.
What a self-hosted runner then executes is attacker-authored YAML plus
attacker-authored builders, on a host with the maintainer's filesystem, network and
persistent `/nix/store`. Hold the boundary in the layers the tree owns: triggers that
never fire on a fork-controllable ref (push to the default branch,
`workflow_dispatch`), `permissions: contents: read`, a checkout pinned to a commit
with `persist-credentials: false` — and **not** `--accept-flake-config`, which makes
nix trust the `nixConfig` of the tree under test, so a PR can add its own
substituters and signing keys and land arbitrary paths in that store. Fork-safe PR CI
needs the repository's fork-approval policy set to require approval for ALL external
contributors first; that is a repository setting no file can assert, so name it as
the prerequisite rather than claiming the workflow closes it.

- **An uncovered line is dead code until its author says otherwise, not a test to bolt
  on.** Coverage is necessary and never sufficient — it proves lines ran, not that the
  feature works as shipped — so the fix for an uncovered line is deleting or explaining
  the code, and the lane that gates is the coverage run, not the unit run. Per-file 100%
  stays refused as a bar; this is what survives without it.

## Procedure

1. **Decide the input shapes** — findings lists vs scalar metrics — and write down
   how each is normalized and bounded.
2. **Build a labelled set before tuning anything.** A graded ladder works well: the
   known-good revision is rung 0, and each higher rung seeds a known number of
   defects drawn deterministically from a seed, so ground truth is known by
   construction rather than by inspection. Build it with a script, not by hand.
   **Pre-screen real-world candidates** for the dominant failure class with a cheap check
   before spending a full measurement on each — and print that screen's raw distribution, per
   the pitfall below. A graded ladder tells you where a defect sits on the scale; real
   repositories tell you whether the scale means anything on code that was not built for it.
3. **Measure every rung with the real tooling.** Never hand-compute a score you
   could run; the whole point is that the number is reproducible.
4. **Derive curve parameters from the known-good baseline of the population that curve
   scores** — an analyzer's baseline for a curve over analyzer output, known-good *agent
   runs* for a curve over agent output, measured at the shipped configuration — then select
   the threshold against the labels.
5. **Record** the parameters, the measured points, and the caveats in the manifest.
   Include the caveats — a calibration that overstates its coverage is worse than none.
6. **Re-verify after any model change.** Changing weights or a curve silently moves
   every historical score; re-run the labelled set and confirm every member still lands
   on its labelled side of the threshold — that the *verdicts* are unchanged. Whether the
   classes separate is a different question, and the answer may legitimately be no.

## Driving the gate: the adaptive loop

A gate returns pass/fail; a driver decides when to stop. Treat the threshold as the
**minimum requirement, not the target** — everything above it is desirable but not
required.

- Keep going while the score is still gaining ground; stop when the gain drops
  below a floor, the time budget is spent, or a hard round cap is hit.
- Attempt a minimum number of rounds first so one unlucky round cannot end the run
  — but let hard limits (cap, budget) **outrank** that floor, or the floor can
  overrun them.
- When a specific reason and a generic one both apply, report the **specific** one:
  "oscillation" tells the next iteration what to change, "round cap reached" does
  not. The stop decision is the same either way; only the reason differs.
- Hitting a cap is not a failure if the requirement was already met. Report the
  outcome against the requirement, not against the mechanism that ended the run.
- **A report-only mode's non-zero exit is the mode, not a failure.** A run that applies no fix
  cannot satisfy the gate, so an advisory mode escalates by design and exits non-zero. Read its
  outcome and its score, and name the mode your numbers came from — calling that exit code a
  broken run hides the only measurement the run produced.
- **Compare a delta, not an absolute score, when the arms are different trees.** A threshold
  calibrated on real projects scores a scratch repository in the 50s, so 52.96 against 50.07 is
  evidence about the two arms and nothing about either tree's quality. Report the delta beside
  the shared threshold and population; where no common calibration exists, say the absolute
  numbers are not comparable rather than ranking them.
- **Write a handover plan on every termination**, satisfied or not: what is
  required, then what is desirable ranked by how much score each item can move,
  then the exact command to resume. When a run stops early, that plan is the
  deliverable — present it rather than reporting a failure.

Rank the desirable work by a **computed number** (weight × headroom), never by
prose, so the ordering is defensible — and feed the same ranking to the fix step,
so an in-flight fix targets the highest-value items instead of whatever the text
happened to mention first.

## Pitfalls

- **Changing an input where it is READ when the run recorded it.** A run bakes its inputs into metadata — detected stacks, sample count, scope — and the scorer treats the recorded value as authoritative, correctly, because a re-score must reproduce the run it describes. So a fix applied only in the reader has **no effect on any existing run**, and re-scoring stored runs cannot measure it: the change has to land where the value is *written*. The trap is that re-scoring then shows a real movement caused by a *different* change in the same commit (a new expected tool lowers coverage, and a lower coverage fraction pulls a hybrid score toward the reviewer's more generous number), and the delta is easy to attribute to the fix that did nothing. Before crediting a movement to a change, confirm the changed code is on the path the measurement exercises; if the input is recorded, re-run end to end.
- **A missing analyzer scoring as clean.** The highest-cost bug in this class.
  Assert on a fixture with a known defect that each probe still reports it — a
  probe that silently returns zero findings passes every test you would think to write.
- **A coverage fraction parsed from human-written text under-counts silently.**
  `beta` was measured by resolving each reported command string to a tool name, and
  the resolver stripped everything before the last `/` in the WHOLE string — so
  `python3 -m pytest tests/ -q` resolved to `-q`, `ruff check scripts/ tests/` to
  `(all`, and `python3 -m py_compile scripts/*.py` to `*.py`. The reviewers had run
  all three, and the gate reported beta 0.60; the run's own plan then advised
  installing tools that were already installed and already run. The parser IS part
  of the measurement, so: path-strip the EXECUTABLE only, never the whole command,
  because a command's arguments are its own (and skip a leading `NAME=value`
  prefix, since `PATH=/x/bin:$PATH ruff check` runs ruff); test the resolver against
  command strings a real agent actually produced, not tidy fixtures — a fixture with
  no path arguments cannot catch this; and treat a coverage number that never
  reaches 1.0 on a repo where every expected tool is installed as a parser bug until
  proven otherwise.
- **Advice that names an action the measuring layer cannot verify.** The same run
  printed `install ruff, mypy` for a `tools_missing` list that means "expected, not
  reported as run" — a different fact from "absent", and the one the gate can
  actually see. Whether a tool is installed is the environment's answer, so the
  wording belongs to whatever can check the environment (`doctor`), or to a neutral
  statement of what was observed. An instruction that contradicts the machine it is
  printed on costs the reader a round trip and teaches them to distrust the plan.
- **Reusing a calibration measured at a non-default configuration.** A manifest records
  numbers but not always the flags behind them, so a calibration taken at one sample count,
  one scope or one mode stands in silently for a default it never measured — and the same
  threshold evaluated at a different recall setting is a different gate. Record the
  configuration beside the parameters, and re-derive when the shipped default differs from
  the one calibrated. The tell that this has already happened: a baseline whose members
  cluster suspiciously high, or one whose lowest clean member sits within a couple of
  points of the threshold.
- **A gate's coverage depends on the environment it runs in.** A coverage fraction that
  depends on which analyzers are on `PATH` scores the same commit differently under a
  devshell and outside one — measured, β 1.0 against 0.33, and the lower number silently
  hands the deterministic half back to the producer's own opinion, which makes the two
  scores incomparable. Invoke the gate the way its pinned toolchain is exposed whenever
  the number will be compared against another run, and say which invocation produced any
  number you quote.
- **Retracting a published measurement without retracting its dependents.** When a
  baseline turns out to be under-sampled or misclassified, the number is the smallest part
  of the correction: the derived interval, the class membership of every member, the
  manifest caveat, the wizard text, the generated config comment and the README each restate
  it. Grep for the figure and for the *claim* it supported, and mark the old record as a
  record rather than deleting it — a superseded measurement that stays visible, labelled,
  is what stops the next session re-deriving it.
- **A pre-screen that reports zero is indistinguishable from one that is broken.** A cheap
  screen for the dominant failure class saves most of a per-candidate measurement cost — but a
  check that returns nothing looks exactly like a clean population. Print the **raw
  distribution beside the count**, and validate the screen against one candidate whose answer
  you know. Real screens fail on *shape*, not logic, and each such failure returns zero for
  every input: a JSON tool emitting a **top-level array** where the query indexed an object
  field; an enum whose values are **capitalised** (`High`) compared against lowercase; a
  **prefix pattern that also matches a config file** (`.env` matching `.envrc`). Shapes and
  the screening recipe: `references/calibration-evidence.md`.
- **Reading a plateau off the sweep.** A sweep over observed scores cannot see the
  interior of the gap between classes; the plateau it reports is an artifact of
  rounding. Compute the separating interval from the labels.
- **A baseline from a single timing sample.** Cold-start outliers can be 3× the
  warm value. Take several samples and use the median; the mean is dragged by
  exactly the outliers you are trying to exclude.
- **Deriving `d*` (or any "50-point" scale) from the bad sample.** It must come
  from the known-good baseline, or the curve is anchored to the wrong end.
- **Letting one unbuildable dependency fail a whole tool set.** A join or list
  fails entirely if one member fails, and the error names only the join. Remove the
  offender and record why: an absent analyzer lowers coverage, a broken one blocks
  everything.
- **Extracting decision logic without pinning its precedence.** When splitting a
  long driver into named predicates, write the ordering down and test each rule in
  isolation. A precedence change is invisible in a diff and changes behaviour.
- **Measuring a corpus that is still being written to.** An A/B is a comparison only
  if the measured set holds still: a write to any measured artifact between the two
  arms moves the baseline as well as the treatment, and the resulting delta is
  uninterpretable in a direction you cannot see. Freeze or snapshot the corpus for the
  duration of both arms, and re-run the baseline if anything changed. The likeliest
  contamination is the measurer's own writes — when the same agent edits the files it
  is scoring, those edits are invisible in the result and read as a real effect.
- **Dead code inside a gate.** A helper defined and never called still draws the
  analyzer's findings and tells a reader the gate shells out when it does not. In a gate
  an unreferenced function is not harmless tidiness debt: it makes the gate's own report
  misleading and buries the findings that do matter.
- **A parser that shells out to its input cannot be property-tested; extract it, and when it
  disagrees suspect the model first.** The pure half is where generated cases can reach: pull the
  text-to-facts function out of the function that runs the command, so hundreds of synthetic inputs
  can be checked against a model built while the input is emitted. This is not ceremony — a diff
  parser that kept only its last hunk's answer survived a large example-based suite, because no
  fixture happened to contain two hunks. Two rules when the generated cases fail: a model built by
  the same person who wrote the parser can carry the mirror of the same mistake (a diff generator
  that advanced the line cursor for additions and deletions but not for context lines, which
  occupy a line on both sides), so re-derive the expected value from the format's specification
  before touching the parser; and state the convention in the model with a sentence, so the next
  reader does not "fix" the correction back out. **Parse the diff structurally, not by line
  prefixes.** The hunk header's declared line counts decide where a hunk ends, so content that
  looks like a header is content: a removed line beginning `-- ` renders as `--- ` and an added
  `++ ` as `+++ `, and prefix dispatch reads both as file headers. A `/dev/null` target marks a
  deleted file — carry the old path from the `---` line, or every removal in that file is
  silently dropped and a proof about it is `unsettled` for no stated reason.
- **A refresh that regenerates the expectation certifies the regression.** Regenerating
  expected output is fixture production, not correctness review: run against a broken tree,
  it rewrites the fixtures to match the break, and the suite then passes on a regression it
  now documents. Measured: a configuration key that was parsed but never evaluated left every
  filesystem tool unregistered, seven scenarios returned structured `UNKNOWN_TOOL` results,
  and the refresh step recorded them as the expected output. Semantic impossibilities — a
  tool that is not in the registry, a model turn with no assistant message — need an
  assertion independent of the expected output, and every refreshed diff gets read as a
  behaviour change.
- **A spec that passes only when run alone is a test defect.** Flakiness attributed to the
  runner is usually shared state the spec never owned: a fixed port, a predictable temp path,
  a global left dirty by an earlier file. Own every acquired resource through teardown and
  the spec passes in any order; a suite that reports "unstable runner" has not found the
  leak.
- **A skipped test is unmeasured, not passing.** A suite that self-skips without its key,
  kernel or tool keeps keyless CI green — a policy, and a good one — but the skipped case
  contributes nothing to the verdict. Count skips beside passes, and never quote the run as
  coverage of the case that skipped. **The same shape governs a tool's own self-test**, and there
  it has cost a shipped image: a `--self-test` that counted a skipped lane as `ok` printed
  `10/10 passed` inside a container whose browser was aborting on a missing `/dev/null`, so the
  green summary carried no information about the lane that mattered. Give it three exit codes —
  `0` every lane exercised and passing, `3` **incomplete** naming the lanes never exercised, `1` a
  lane ran and failed — and make a lane that *is* present but fails a `1`, not a `3`: "could not
  run here" and "ran and broke" are different facts, and the second is the one being hidden.
- **A collection error read as "0 failures".** A suite that aborts at collection
  reports nothing, and nothing looks like a pass in a summary line. Treat a collection
  error as zero coverage, not as a clean run — the code that ships is validated by
  exactly the tests that actually executed.
- **A receipt compared by equality is evidence for the empty string.**
  `receipt.get("id") == meta.get("id")` passes when BOTH sides are missing — `None == None`,
  and `""` is falsy, so a payload with no identity field reads as a match. Validate identity
  where it is **written** (a full lowercase hex commit id, an exact ref) and refuse anything else
  at write time, so an unkeyable receipt cannot be stored at all; at read time require the field
  to be present before comparing, and give "names no commit" its own blocked reason rather than
  reporting a mismatch — the reader needs to know which of the two things happened.
- **A bounded scan that truncates converts "did not look" into "found nothing".** A file walk or
  probe loop that stops at N results and reports what it collected has the missing-analyzer
  failure one layer down: an empty result is indistinguishable from a clean tree. Refuse instead
  — exceed the budget, return `unrunnable` naming the limit and the narrowing to apply — and keep
  keep the order deterministic (sort the paths) so two runs report the same first hits.

  **A producer run that failed must record why, or the corpus cannot tell "never attempted" from
  "refused four times".** Have the producer write a status beside its artefact — exit code, whether the
  artefact exists, whether it parsed, and a classified reason (`provider_refused`, `rate_limited`,
  `auth`, `timeout`, `connection`, `unparseable`, `unknown`) — and let the corpus run its own retries,
  recording every attempt in the manifest. A retry loop in a shell script beside the tool loses both
  facts, and its own `exit=$?` taken after a pipeline reports the tail's status, so a refusal is
  logged as success. A run that wrote valid JSON and then exited nonzero keeps its sample: the
  artefact is the evidence, the exit code is not.

  **A score computed from a run that could not be certified must not enter a calibration set.**
  Measured: a tree holding one README produced a probe finding, no claim from the reviewer, an
  aggregate of **100.00** and certification `unprovable`; adopting that number would have fitted the
  threshold to a run that examined nothing. Record the aggregate *and* the certification, and refuse
  the member. Refuse one scored on a different scale than the corpus declares for the same reason: a
  threshold derived on one scale means nothing on the other, and the mismatch looks like a normal
  member while it silently shifts the fit.

  **Validate the precondition before recomputing into place.** A stage that rewrites a run's own
  artefact must refuse when its input is absent, because the degraded result lands on top of the good
  one: measured, a path argument that did not exist produced an all-`unrunnable` report that replaced
  a round carrying four confirmed claims. Check the root is a directory and exit before opening the
  output. Same mechanic, adjacent symptom: `subprocess` raises `FileNotFoundError` for a missing
  **working directory** exactly as it does for a missing executable, so that handler reported a
  present, working analyzer as "not installed" — test the root first and name it in the message.
