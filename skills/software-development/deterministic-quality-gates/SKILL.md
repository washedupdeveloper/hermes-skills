---
name: deterministic-quality-gates
description: "Use when building or calibrating a scoring gate."
version: 1.4.0
author: user, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
category: software-development
metadata:
  hermes:
    tags: [quality, scoring, calibration, gates, metrics, verification]
    related_skills: [requesting-code-review, systematic-debugging]
---

# deterministic-quality-gates

Building a gate that scores a codebase deterministically — normalized signals, a
weighted aggregate, a pass threshold — and calibrating its free parameters from
labelled evidence instead of intuition. Also covers the loop that drives the gate
and has to know when to stop.

This is the **principle** side. For a worked implementation of these ideas, see
the `council` skill — its operational commands, paths and flags live there, not here.

For the concrete failure patterns that make a check lie about itself — a filter that
skips the very file it names, a copy that aliases nested state, a payload past the
kernel's per-argument limit — see `references/silent-failure-patterns.md`.

For a suite that has to be correct under real CI concurrency — shared host ports, global
state, platform-owned semantics, timeout budgets, quiescent teardown, and the fixes that
mask a flake instead of closing it — see `references/test-reliability.md`. The CI half —
freezing the evidence, the classification, the smallest reproducing topology, and what a
diagnosis-only request authorizes — is `references/flake-diagnosis.md`.

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

**A producer that ran out of time leaves artifacts on disk anyway — re-run COLLECTION
before re-running the producers.** A gate cannot score what its producers never wrote,
but "never wrote" is often "wrote after the collector ran": the collection step is
deterministic and cheap, the producers are slow and paid for, and the two race. Measured
on the council: five reviewer samples hit a 1800 s per-turn cap (`rc=124`, distinct from
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
the system that must be updated with every real change.

**Every acceptance rule needs a negative control.** A check that cannot fail is not a
gate: a predicate that silently matches everything passes its own test, and that pass
looks identical to a real one. For each rule, drive one deliberately invalid input
through the **same** code the gate calls and assert it is rejected — plus the valid case
beside it, so a predicate stuck on `false` fails too. Exercise the boundary rather than
inferring it: a length rule is tested at the limit and one past it, because a `>=` written
for `>` rejects the last value that fits, and no real artifact sits on the boundary. A
copy of the predicate written for the test proves nothing about the gate — extract it, so
the test and the gate call one function.

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
measured with beta = 1 is still reviewer variance, not measurement error.

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
compares two empty results and passes.
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
  coverage of the case that skipped.
- **A collection error read as "0 failures".** A suite that aborts at collection
  reports nothing, and nothing looks like a pass in a summary line. Treat a collection
  error as zero coverage, not as a clean run — the code that ships is validated by
  exactly the tests that actually executed.
