---
name: deterministic-quality-gates
description: "Use when building or calibrating a scoring gate."
version: 1.1.0
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
at all. Pass an explicit timeout to every subprocess a gate spawns.

**A gate can own the copy-vs-source invariant.** When a repository ships a copy of
another tree, compare the copy against its source byte for byte, resolving the source
from the repository's own location rather than a machine path. A copy drifts silently
and the drift is invisible until something fails at runtime; the comparison turns a
latent divergence into a red gate on the run that introduced it. Report the differing
names, and treat a file present in the copy with no source as a second class of drift,
not as a pass.

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

**Derive a classification threshold from the labels, not from the sweep.** Sweeping
for the value that best separates the two classes is the mistake that looks correct
and is not.

**Calibrate from labelled evidence and record the result in a file.** An
unrecorded calibration is a guess with extra steps: the moment the manifest is
missing the gate silently reverts to defaults. Ship the parameters alongside the
code, and document that deleting the file restores uncalibrated behaviour.

## Procedure

1. **Decide the input shapes** — findings lists vs scalar metrics — and write down
   how each is normalized and bounded.
2. **Build a labelled set before tuning anything.** A graded ladder works well: the
   known-good revision is rung 0, and each higher rung seeds a known number of
   defects drawn deterministically from a seed, so ground truth is known by
   construction rather than by inspection. Build it with a script, not by hand.
3. **Measure every rung with the real tooling.** Never hand-compute a score you
   could run; the whole point is that the number is reproducible.
4. **Derive curve parameters from the known-good baseline**, then select the
   threshold against the labels.
5. **Record** the parameters, the measured points, and the caveats in the manifest.
   Include the caveats — a calibration that overstates its coverage is worse than none.
6. **Re-verify after any model change.** Changing weights or a curve silently moves
   every historical score; re-run the labelled set and confirm the classes still
   separate before trusting the new numbers.

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
- **Write a handover plan on every termination**, satisfied or not: what is
  required, then what is desirable ranked by how much score each item can move,
  then the exact command to resume. When a run stops early, that plan is the
  deliverable — present it rather than reporting a failure.

Rank the desirable work by a **computed number** (weight × headroom), never by
prose, so the ordering is defensible — and feed the same ranking to the fix step,
so an in-flight fix targets the highest-value items instead of whatever the text
happened to mention first.

## Pitfalls

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
- **A collection error read as "0 failures".** A suite that aborts at collection
  reports nothing, and nothing looks like a pass in a summary line. Treat a collection
  error as zero coverage, not as a clean run — the code that ships is validated by
  exactly the tests that actually executed.
