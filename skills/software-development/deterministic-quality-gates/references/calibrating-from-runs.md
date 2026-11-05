# Calibrating a threshold whose score comes from admitted claims

A threshold is a claim that a number separates defective code from clean code. When that number is
computed from what a producer *proved*, the claim can only be checked against runs whose ground
truth is known — and the producer is stochastic, so one run per sample is a point, not a
distribution.

## The unit

One **adjudicated run directory**, plus its label from the manifest:

| file | why the derivation needs it |
|---|---|
| `<dimension>.json` × N | the deterministic half and the coverage fraction β |
| `probes.json` | what the toolchain saw, independent of the producer |
| `proofs.json` | which findings are `confirmed` — the claims score and any cap |
| `meta.json` | stacks, target revision, the enforcement mode |
| label, rung, repeat | ground truth, from the manifest |

A corpus without proofs is a producer's opinion with a label attached, and it calibrates nothing.

## Reuse the ladder generator; review it this time

A graded defect ladder (rung 0 = the base untouched, each higher rung seeding a known number of
defects from a fixed seed) already gives ground truth by construction. Feed it to the **real review
loop**, not only to the probes: on this scale the number moves only when a defect is found *and*
proved, so the ladder has to be adjudicated to produce points.

**Record detection, not just the score.** Match each seeded defect against the confirmed claims —
and match on the **line**, not on the file. A path-level match ("some claim sits in the file that
holds the seeded defect") scores a producer as having found a planted credential when it reported
an unrelated style issue three functions away, so the detection column becomes an upper bound with
no error bar and a blind spot can only appear in a file the producer never mentioned at all.
Require the claim's line range to overlap the seeded defect's own line range, report the unmatched
seeds by name, and do not let a path-only match count.

**A seed is a range, and its span comes from the text that planted it.** Recording only the first
line of a seeded block turns a detection into a reported miss: an `eval` seed writes `def …:` and
`return eval(…)` on consecutive lines, a producer naturally cites the second, and a point-against-
point comparison scores three passes as having missed a defect every one of them reported. Derive
the span from the same template that generates the seed text (count the lines it plants, minus the
leading blank lines), write `line_end` into the manifest, and backfill older manifests from the
seed's `kind` so a corpus collected before the fix stays readable. Then read the primary source
before recording any blind spot: open the pass's raw artefact, pull the findings for the seeded
path, and print their line ranges. A measurement that says "never found" is a hypothesis about the
matcher until that file has been read. Without the column at all, the derivation cannot tell "the
reviewer found everything" from "the reviewer found nothing and scored 100".

## Prove rung 0 is clean, and sample inside the toolchain

Two environment faults make every point wrong while each individual run looks healthy. Check both
before paying for the corpus.

**A "clean" base is a hypothesis until the gate's own probes agree.** Rung 0 is the base untouched,
which is not the same as clean: a fixture whose `flake.nix` does not evaluate fails `nix flake check`,
so the probe records `critical` findings and the rung can never certify — the derivation then refuses
and reads like a scorer bug. Run the gate on the base once, and accept it only when it comes back
clean at the probes' own hands, before any producer time is spent. Measured: a golden fixture was
used as rung 0 on the strength of its name, every clean run failed `nix flake check`, and the corpus
had to be rebuilt on a two-file base that actually evaluates.

**Sample inside the pinned toolchain, or detection reads as zero.** The producer emits proofs, but
`collect` is what *executes* them: run it where the analyzers are absent and every proof comes back
`unrunnable`, which the claims scale reads as a defect the producer missed. Measured on a six-run
ladder sampled from a bare shell: `detected 0/1` on all three defective rungs, with the note naming
the unrunnable proofs. The same runs, re-adjudicated inside the devshell, confirmed two critical
findings including the planted credential. Run the sampler and `collect` under the same toolchain
invocation the gate documents, and treat "undetected" with unrunnable proofs as an environment
finding rather than a producer one — the two lead to opposite repairs.

## Shape the ladder before you spend a run on it

A ladder that raises the defect count by **adding files** also raises what the deterministic half
can measure, so each rung differs from the last in two ways at once. Measured on a real corpus:
`det` rose 6.8–13.7 points per dimension between rung 0 and rung 16 — the bigger tree was judged
*better* per tool — and the sixteen-defect rung outscored the clean one, 43.52 against 42.36.
No threshold separates that, and the failure looks like a scoring bug rather than a ladder bug.

Seed defects **into the base's existing files** (append a hardcoded credential, an `eval`, a
nesting blob, a syntax break, each recorded with its line) so file count, detected stacks and tool
coverage are identical at every rung. The only variable left is the defect count. Same corpus, same
scoring, after the change: rungs 0/1/4/16 scored 85.96 / 64.38 / 53.56 / 58.79 and separated by
21.6 points.

Two mechanical consequences:

- **A floor belongs on every term that divides by the same quantity.** The claims term was floored
  at a minimum size (`MIN_KLOC`) while `det` still divided by the raw 0.056 KLOC, so a 56-line
  tree was scored as if every line were defective. Extending the same floor to both moved the
  separation margin from +7.81 to +20.41 and shrank the detection inversion from 17.8 to 3.3
  points — measure the margin before and after, because a half-applied guard looks like a fix.
- **Verify the shape, not the intent.** Count the files per rung and assert they are equal; a
  ladder that drifts by one file per rung is invisible in a manifest that only records
  `defects_seeded`.

## Repeats: measure what varies before designing a fix

A spread is not one phenomenon. Three passes over the same tree can differ because the producer
reports different **locations**, because it assigns different **severities** to one location, or
because a seeded defect is invisible to it at every draw. Only the first two improve by repeating,
so know which one you have before choosing a remedy.

| measured | on one nine-run corpus | the remedy it implies |
|---|---|---|
| agreement — distinct locations per pass | 10 of 16 locations on the *defect-free* rung appeared in exactly one of three passes | none until this is small: the score is noise |
| severity for a fixed location | one committed credential: `critical`, `critical`, `medium` | derive severity from the observed evidence, not the label |
| seeded defects no pass reported | a complexity defect missed in 3 of 3 | a blind spot; repetition cannot surface it |

Build the numbers from the run directories the corpus already wrote — no extra producer calls:

- **stable** (n/n), **majority** (2 of 3), **one-off** (1 of 3), counting a location once per pass
  even when that pass reports it twice, or a chatty run looks steadier than a quiet one.
- **severity disagreements**: group by location, list the distinct values.
- **blind spots**: seeded defects whose line range no pass flagged.

The decision these feed: an unstable producer is fixed by removing the instability, not by voting.
A k-of-n consensus raises the cost by n and *hides* the variance — it does not remove it, and it
still needs a separate rule for the severity flip, which is a second policy invented on top of the
first. Keep it as the fallback, and record it as on, the way any other relaxation is recorded.

## When the spread will not narrow, the parameter is the wrong one

Repeating is the reflex, and it only helps when the variation is sampling noise. Split the variance
before buying more runs. For every pass, count the confirmed claims that **match a seeded defect**
and the ones that do not:

| one identical level-1 tree, six passes | values | spread |
|---|---|---|
| seeded defects detected | 1, 1, 1, 1, 1, 1 | **0** |
| incidental confirmed findings | 3, 3, 3, 1, 2, 4 | 3 |
| aggregate score | 52.49 … 68.08 | 15.59 |

Detection was constant and severity agreed; the score moved because the producer reports a
different number of *other* findings each time, and a severity cap turns one of those into a
10-point swing. More repeats cannot narrow that — each new draw widens the observed range — because
the variation lives in the producer, not in the sample. Two consequences, and the second resolves it:

- **Refuse on the right spread.** Compare the margin (worst clean − best dirty) against the
  **within-rung repeat spread**, never against the spread *across a class*. The class spread
  contains the genuine difference between one defect and four, so treating it as noise refuses
  thresholds that are fine and, worse, hides which member was actually unstable. A margin narrower
  than the widest single-rung spread is refused outright: it would not survive another draw. And
  when a margin clears by a fraction of a point, treat that as unproven — measured, 13.02 against
  12.86 became 10.29 against 15.59 the moment three more passes arrived.
- **When the number cannot separate, stop thresholding it.** The verdict can rest on the quantity
  that did hold — the set of confirmed claims at the severities that block. On twelve runs the
  aggregate overlapped (clean 78.37–88.81, dirty 58.72–68.08) while the blocking-set verdict
  classified 12 of 12. Record which quantity decided (`certification_basis: "claims" |
  "threshold"`) so a reader knows whether the number or the claim set was consulted, and score the
  separation itself: a report that prints each member's verdict against its label and exits non-zero
  on any disagreement. Prove it can fail — relabel a clean member `bad`, drop one member's verdict —
  before quoting the total.
- **Switching the basis is a migration.** A verdict that now rests on the claim set must stop
  consulting the calibration it no longer needs, or every clean member reports `uncalibrated` and
  the separation reads as a failure of the class rather than of the leftover check.

## The refusals, and the reason each exists

| refuse when | because |
|---|---|
| a rung has no scored run | a threshold fitted to whatever finished first is fitted to the schedule, not the code |
| the points mix scoring scales | aggregates from two regimes are two rulers; the mean of them is neither |
| a bad rung's seeded defects went undetected | that is a producer failure. Including it teaches the threshold that a defective artifact passes |
| a bad rung's detection is **below a floor** (partial, not zero) | caps attach only to confirmed claims, so a rung where most defects were missed keeps its score high — measured, 2/16 detected scored 58.79 against 4/4 at 53.56. Excluding it must be deliberate and recorded (`excluded: [16]`), never silent |
| fewer than ~3 runs per class | one draw of a stochastic producer is a point. Record `provisional: true` if you write it anyway |
| the classes do not separate | no threshold is both precise and complete; the score lacks the signal, so the next move is the scorer, not the cutoff |

Each refusal should name what to do next — re-run the rung, repeat it, or fix detection. A number
that cannot be defended is worse than no number, because it looks like one.

## The distribution is bimodal, so state what the threshold means

With nothing confirmed the score is the maximum; confirmed defects then move it through a density
term and a severity cap. So the threshold is not cleanly separating "good" from "bad" — it is a
**policy** statement about how much *proven* defect is tolerated, chosen at the max-margin point
between rung 0 and the lightest rung that is reliably detected. Write that sentence into the
manifest; a reader who assumes a clean/bad separator will misread every later number.

## Two scales coexist

Keep one manifest per scale (`calibration.json`, `calibration.claims.json`) and load by the run's
own source. A single file lets a corpus run overwrite the threshold the other scale still depends
on — and because both files carry the same field names, the swap is invisible. A run whose scale
has no manifest is `uncalibrated`: score reported, nothing certified, reason naming the command.

## Cost, measured rather than assumed

Time **one** complete round before planning a corpus: a producer turn, times the number of
dimensions, plus merge and adjudication. Two or three repeats per rung multiply it again. State
the estimate with its basis, and parallelise across sandboxes rather than shortening the run — a
corpus measured at a cheaper configuration than the one that ships describes a different gate.

## Pitfalls

- **Dropping an undetected bad rung silently.** The manifest then contains only the rungs the
  producer happened to handle, which is a threshold fitted to the producer's strengths.
- **A derived threshold written beside the installed module never lands.** The default
destination is the module's own directory, which in a packaged build is a read-only store path:
the derivation succeeds and then dies at `OSError: [Errno 30] Read-only file system`, so the next
run is still uncalibrated while the console showed a threshold. Resolve the destination from the
checkout in the working directory when one is present, keep an explicit `--out` for everything
else, and then make the file part of what ships — a module list is an explicit enumeration, so a
new JSON asset beside the scripts is invisible to every packaged build until it is added to that
list. Because a flake's source is the **git-tracked** tree, it must also be staged before the
build that copies it can see it (`cp: cannot stat …calibration.claims.json` is an untracked file,
not a typo). Prove it from the artifact: `ls <framework>/scripts/calibration.claims.json`, and
compare the threshold it carries with the one the gate reports.
- **Deriving from the same single sample twice.** Two derivations over one draw agree with each
  other and both describe the same accident; the agreement reads as corroboration.
- **Deriving before the coverage rule exists.** See "a score derived from what the producer
  admitted rewards silence" in SKILL.md: without it, a silent producer's rung enters the clean
  class at the maximum score and drags the threshold up.
- **Assuming the arithmetic is the hard part.** Choosing candidates, running the loop, and
  matching detection to ground truth is the work; the threshold is the division at the end.
- **Paying for repeats before proving separation once.** One run per rung on two rungs (the clean
  one and the dirtiest) costs two producer turns and answers the only question that matters first:
  does the score separate at all. Twelve runs of a corpus whose arithmetic cannot separate buys
  twelve points on one side of a line that does not exist. Scale to three per class only after a
  single pair separates, and fix the ladder shape before either.
- **Treating a floor added to one term as a floor.** See "Shape the ladder" above: the guard has to
  reach every expression that divides by the quantity, or the smaller member is penalised and the
  the separation margin silently shrinks.
- **A repeat report that reads "no run" for every rung.** The run root holds `round-N/` and only the
  latest round that carries the proofs file is the pass; a report that looks for `proofs.json` at
  the root finds nothing and prints an empty result, which reads exactly like "measured, and there
  was nothing to find". Resolve the round, and let an empty report say `no run` rather than a row of
  zeros.
- **Reading a secret-shaped string out of tool output and concluding the tree is corrupt.** Agent
  runtimes redact credential-shaped strings in command output, so a well-formed seeded key reads
  back as `sk_liv...lo2C` with an ellipsis and looks exactly like a generator that planted a
  placeholder. Verify by measurement — length, character class, a hash — before changing anything:
  on this corpus the planted key was 38 well-formed characters, the generator was correct, and the
  "fix" would have replaced a valid credential with a different one and invalidated every run that
  used it. Anything a redaction can touch is checked by its properties, never by reading it.

## A failed run is part of the record, not a missing row

`collect` that finds no artefact prints "not run" — the same line it prints for a rung nobody ever
attempted. Those are different facts, and the difference is the whole reason a corpus can be trusted
through a provider outage: one means the sample was never drawn, the other means it was drawn and
refused, possibly three times.

Record every attempt in the manifest beside the rung:

```json
{"rc": 1, "artefact": "missing", "reason": "provider_refused"}
```

- **Classify from the runner's own words**, not from the exit code alone: `provider_refused`,
  `rate_limited`, `auth`, `timeout`, `connection`, `unparseable`, `unknown`. Order the patterns, the
  first match wins, and let `unknown` mean unknown — a classifier that guesses is worse than one that
  admits it did not recognise the text.
- **Keep the exit code beside the artefact, never in place of it.** A run can exit non-zero *after*
  writing a complete, parseable artefact; the artefact is the evidence and the code is a detail. The
  inverse trap is a truncated file that parses: validate the shape (`findings` present) rather than
  trusting either signal alone.
- **Put the retries inside the sampler.** A retry loop in a shell script leaves the attempts outside
  the tool, so the manifest cannot say whether a rung was refused or skipped, and the loop is
  unversioned behaviour that the next operator has to rediscover. `--sample-corpus --retries N` with
  the attempts written into the manifest makes the policy part of the artifact.
- **Let a sample write its own status file** (`sample-<n>.status.json`) for the same reason: a run
  started by hand still explains itself, and the explanation sits beside the artefact it describes.

## The corpus ingests only scores the gate stands behind

Three ways a rung acquires a number the gate did not mean, each measured:

- **`unprovable` still carries the maximum.** The probes observed a defect, the producer settled no
  claim, the verdict is `unprovable` — and the aggregate is 100.0, because the number is honest about
  what it measured and the *verdict* is what carries the gap. That is right for the gate and wrong
  for the corpus: a 100.0 enters the clean class and drags the threshold up. Record the verdict and
  refuse the score, with the gap's own words as the note.
- **The scale is not the one the corpus declared.** A manifest saying `claims` with no claims
  calibration on disk is scored on the deterministic scale, silently, and a perfect 100.0 lands in a
  corpus measuring something else. Assert `score_source == manifest["scale"]` at collect time and
  refuse the rung; a threshold from one scale does not apply to the other.
- **Nothing was examined.** A sample that ran no tool, no probe and reported no finding is not a
  clean tree — the gate cannot tell "nothing found" from "nothing looked at". Reported findings
  count even when unproven (that producer examined the tree and failed to settle its claims), and so
  do probes that ran; only all-three-empty is uninformative.
