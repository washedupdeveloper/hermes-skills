# Calibration evidence: what a measurement can and cannot support

Depth for the rules in SKILL.md about deriving a threshold from labelled evidence.
Read this when a threshold or curve parameter is being justified by measurements,
especially measurements of real repositories rather than a synthetic ladder.

## 1. A band is only as tight as the class that fails on the thing you calibrate

A member can fail the gate for a reason other than the threshold:

- an open blocking finding
- a required check that did not run
- a missing credential or tool

Such a member carries **no information about where the threshold belongs**. It fails at
every value, including one *below* its own score. Verified directly: a repository scoring
75.06 with 22 blocking findings failed at `--threshold 75.05`, because the blocking
condition alone decided the verdict.

**Consequence for the band.** If most of the failing class fails on a separate criterion,
adding members cannot narrow the interval. The honest report is the **one-sided bound you
actually have**:

- an upper bound, from the cleanest member (`threshold <= 90.22`)
- no floor, because no member exists that is clean of blocking findings yet *should* fail
  on aggregate

An interval presented as `(a, b)` when its lower edge `a` came from a member the threshold
never governed is a fabrication of the same kind as a threshold pulled from intuition.

**The stronger corollary.** If the aggregate is load-bearing only for members with no
blocking findings, and few such members exist, then **the threshold cannot be calibrated by
collecting more repositories at all**. Say that in the write-up. It is a finding about the
population, not a gap in the effort, and it is the honest close.

**Measuring the population is itself a result.** Across nine well-regarded repositories in
one ecosystem, one was clean of blocking findings and eight were not: unpinned actions,
`pull_request_target` with write scope, tracked encrypted state files. A gate that finds
real defects in respected projects is working; the same fact means the clean class barely
exists, which is why a threshold derived from "known-good repositories" has almost nothing
to derive from. Record the ratio — it reframes the open question permanently.

## 2. Pre-screen candidates; a screen that reports zero may be broken

A full review costs minutes per candidate. The dominant blocking class is usually
detectable in seconds. Screen first, then measure only the survivors.

A screen is a check, so the rule about checks applies: **a screen returning nothing looks
exactly like a clean population.** Print the raw distribution beside the count, so a zero
is evidence rather than silence, and validate the screen against one candidate whose answer
you already know.

Screens fail on *shape*, not logic. Every one of these returns zero for every input:

| failure | mechanism |
|---|---|
| indexed an object field on a top-level array | the JSON tool emits `[...]`, not `{"findings": [...]}` |
| compared against lowercase | the enum's values are capitalised (`High`) |
| prefix pattern too loose | `^\.env` also matches `.envrc`, a direnv config |

A screen reporting the same answer for every input is the first hypothesis, not the last.
The cost of missing this is a full measurement spent to learn what the screen should have
said.

## 3. "Known-good lands mid-scale" is a discrimination rule, not an absolute one

A rule of the form *derive the half-point so a known-good member scores 50* comes from
ranking material: it makes the curve steep enough to separate classes. It also **pins that
member's contribution at 50 by construction**.

In a weighted composite such as `0.7 * analyzer_signals + 0.3 * density_term`, a pristine
member's ceiling is then near `0.7 * 95 + 0.3 * 50 = 81`. Applied to an absolute pass/fail
threshold, no member of any class can clear a threshold above that, and every score drops
together. Measured: adopting the rule dropped every repository and nothing passed.

**Test before adopting.** Compute what a *pristine* member scores under the candidate rule.
If the answer is not near the top of the scale, the rule is the wrong shape for an absolute
gate and belongs only in the separating comparison.

**Test the rule against the whole labelled set before shipping it.** A rule that drops every
member and passes none is not a calibration, it is a rescaling.

## 4. Order of operations for a contested threshold

1. Confirm which expression the gate compares (not an intermediate quantity).
2. Measure every member at the **shipped default** configuration.
3. Classify each member: does it reach the threshold comparison, or fail on a separate
   criterion? Discard the latter from threshold reasoning and say so.
4. If clean and defective members are both present and governed by the threshold, compute
   the interval `(max(defective), min(clean))` and probe both edges with the real gate.
5. If the clean class is empty or the members fail on other criteria, report the one-sided
   bound and the population ratio instead of an interval.
6. Record the configuration beside every number.
