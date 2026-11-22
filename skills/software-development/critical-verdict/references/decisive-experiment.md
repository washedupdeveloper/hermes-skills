# Running the decisive experiment

`critical-verdict` ends by naming the cheapest test that would falsify the verdict. This
is how to design and run that test so its result actually decides something, instead of
producing a number the author can explain away afterwards.

Use it when a verdict rests on an unmeasured claim — "this architecture is worth its
cost", "five specialists beat one generalist", "the extra moving parts pay for
themselves". The claim is usually the one thing nobody measured.

## 1. Fix the rule before the first run

Decide what result means what, in advance, and make the artifact enforce it.

- State the rule as a **threshold with a direction**: "the expensive arm must find at
  least 1.5x the distinct true defects of the cheap arm at equal cost, or the
  architecture collapses to the cheaper one."
- Put the constant in the code as a named value and **assert it in a test**. A test
  that fails when the rule moves is what makes "pre-registered" true rather than
  claimed. Without it, the rule is a sentence someone can edit once they see the
  numbers.
- Write the **losing branch as plainly as the winning one**. A rule that only
  describes success is a wish, not a decision procedure.
- Record the rule where the artifact lives (a milestone note, a docstring, the module
  header) so the next reader sees what was committed to before the data arrived.
- **Check the rule has room to fire.** A ratio rule needs more truth than the threshold
  implies: "at least 1.5x the cheap arm" on a corpus holding N defects demands the
  expensive arm find more than 1.5N, which is impossible once the cheap arm already
  finds most of N. Size the corpus so the ratio can be satisfied, or say plainly that the
  corpus size — not the arms — decided the verdict. A rule that cannot be met is a
  pre-registered conclusion.

## 2. Compare at equal cost

An experiment that compares two designs at different cost measures cost, not design.

- Pick the currency that matters — agent turns, tokens, wall-clock, dollars — and make
  the arms equal on it *before* comparing quality.
- If they cannot be made equal, report the ratio and let the reader weigh it. Never
  present a more expensive arm's better score as a design win.
- State the cost of each arm in the write-up, not just its score.

**Hold the sampling depth constant when the metric is derived from the findings.** A
score computed from a findings list moves when the number of samples changes, for a
reason that has nothing to do with quality: more samples find more defects, which raises
the finding density, which lowers a density-normalised score. The shallower run therefore
scores *higher* — it found less. Comparing runs at different depths measures the depth,
not the design. Fix the sample count across every run you intend to compare, and treat a
number produced at a different depth as a different measurement rather than as an
improvement.

## 3. Isolate what the design bundles

A design usually bundles several changes at once. Comparing the bundle against a plain
baseline attributes the whole difference to the whole bundle and names no cause.

Add an arm per change you can afford to separate. For a multi-agent design the shape is:

| Arm | Isolated variable |
|---|---|
| bundled | N contexts + per-role instructions |
| control A | N contexts, no instructions |
| control B | instructions, one context |

That separates "more contexts" from "role knowledge" — two things the design claims as
one advantage.

## 4. Establish ground truth

Prefer truth known **by construction** over truth you infer.

- **Constructed:** plant a known number of defects deterministically from a seed; the
  seed's output *is* the ground truth. Build the corpus with a script, never by hand.
- **Historical:** if the artifact was already fixed, the revision *before* the fixes is
  a corpus. Recover it with a worktree at that commit.
- **Never** derive truth by diffing two revisions separated by unrelated refactors. The
  diff returns every refactor as a defect and recall becomes meaningless.

### Keep the seeded defects invisible to the project's own gate

A defect the project's automated gate catches is not a reasoning defect, and a corpus
that trips its own gate is broken. Two ways this goes wrong, both silent:

- **Formatting and lint.** An edit the target's formatter would rewrite, or that a linter
  flags outright (an unused argument, a dead binding, a duplicated setting), is visible
  for free to anyone who runs the gate. Write each injection the way the project's own
  tooling would write it, and confirm with the formatter in check mode.
- **Duplicate-definition semantics.** Where a configuration language *errors* on a
  duplicate definition instead of silently preferring one — the NixOS module system does:
  a plain definition beside an existing one is a hard conflict — a bare override makes the
  tree fail to evaluate, so the defect is caught by evaluation and never reaches a
  reviewer. A *silent* override needs explicit priority (`lib.mkForce`), and that is the
  defect worth planting.

Then prove it, and prove it against a baseline: **the unmodified base must pass the same
gate, and so must the corpus.** Run that gate *with building enabled*. An invocation that
only evaluates — `nix flake check --no-build` — reports success while the builders that
would have failed are never run, which is exactly how both failures above survive a check
claiming to have passed. If the base does not pass the gate, gate-passing proves nothing
about the corpus and the criterion is unusable.

## 5. Check the corpus discriminates before spending runs on it

Three failure modes, each of which wastes a full run:

- **The corpus names its own answer.** A seeded defect living in `seeded_secret_0.py` is
  findable by filename, so every arm scores it and recall saturates at the ceiling. Such
  a corpus can still measure *precision*; it cannot measure recall. Say which one it is.
- **The corpus is already clean.** Confirm the defects are still present in the exact
  revision you will review, and that nothing upstream already removed them. A clean
  corpus yields false positives only, and no recall signal at all. Enumerate the fix
  commits from history rather than trusting your recollection of how many rounds ran —
  a repo is often cleaner than the last run you remember.
- **The corpus is contaminated by its own base.** A corpus built by copying a repository
  inherits that repository's defects, and every arm is then penalised for reporting them:
  a true defect in the base counts as a false positive against whichever arm found it.
  That conflates "hallucinated" with "correctly found something out of scope", and it
  penalises thoroughness — the very behaviour under measurement. Confirm the base is
  clean, or score findings inside the planted set separately from findings in the base.

A saturated corpus yields a tie; a clean corpus yields noise; a contaminated one yields
a penalty for thoroughness. None decides the question. Verify all three *before* the run,
and say so in the write-up.

### Pre-register three outcomes for the fixture itself

A task used to test whether a guide, a skill, or a tool changes an outcome needs its own
controls, fixed before any arm runs:

- **The pristine fixture fails, for the planted reason only.** If it fails for something
  incidental, whichever arm fixes that incidental thing scores as a success.
- **A gold solution passes.** A check only ever observed to reject is a filter, not a
  measurement: you do not yet know that success is reachable at all.
- **The tempting naive answer evaluates cleanly and fails on content.** A trap that
  crashes teaches nothing, because the error itself sends the agent looking for another
  approach. The wrong answer has to look right and produce a plausible result the check
  then rejects — an override that removes the error while silently dropping sibling
  fields is the shape to aim for.

**Never hand a human a labelling job for a corpus that cannot discriminate.** Labelling
is the expensive, human part of the measurement. If the run's own numbers already show
the arms tied at the ceiling, or that nothing true is there to find, say so and withhold
the sheet — asking for verdicts on a corpus that cannot separate the arms spends the
operator's attention on a non-result.

## 6. Blind the labelling

When a human labels which findings are real:

- Do not reveal which arm produced each finding.
- Do not show per-arm totals on the same sheet.

Knowing the expensive arm found it biases the verdict toward "real" — which is exactly
the comparison the labels exist to settle. Keep provenance in the machine-readable
record and join it back at scoring time.

## 7. Count the right thing

Count **distinct defects found**, not findings that matched.

An arm that describes one defect three ways must not out-score an arm that describes it
once. Scoring by matched findings rewards verbosity and inflates precisely the number
the rule compares. Keep the raw count visible beside the distinct count for the record.

**Guard the denominator, and make the null result read as undecided.** A ratio rule
("arm A must find at least N times arm B") computes infinity when B found nothing, and
`infinity >= 1.5` announces a win for A on a corpus where neither arm found anything at
all. Handle zero explicitly and emit **UNDECIDED** — no result is not a result in your
favour. Test that branch directly: it fires on a corpus you have not yet validated, which
is exactly when a confident wrong answer costs the most.

**Recall asks about the defect, not about ownership between findings.** Match
**non-exclusively**: a defect is *found* if **any** finding points at it. Resolving each
finding to a single truth entry — the intuitive "nearest match" — silently under-counts
whenever two planted defects sit within the matching window of each other (a setting and
the commented-out block three lines below it): one finding covering both is credited to
whichever is nearer, and the other reads as missed. Recall is understated by exactly the
amount under comparison, and the totals show nothing wrong. Test the overlapping case
directly.

**Compare paths before line distance.** A matcher that ranks by line distance alone
matches a finding to a defect in a *different file* whenever the line numbers happen to
be close — which reports **zero false positives for every arm** and makes all of them look
perfectly precise. Match the path first; a `new-file` truth entry matches only within its
own path. Neither bug is visible in the aggregate: both were found by reading individual
findings against the raw output after the numbers looked wrong.

## 8. Verify the arms actually ran

An arm that exits cleanly but writes no output silently understates itself, and the
missing output is the number under comparison. Count produced artifacts against
expected and fail loudly on a shortfall — an exit code is not evidence of a result.

**Make the entry point emit the deliverable.** If the measurement needs a handover
artefact — a labelling sheet, a summary table — have the run write it. A separate
subcommand that must be remembered will eventually be forgotten, and the run then
"completes successfully" without the one thing the next step depends on. Generation
belongs inside the run, not beside it.

### Hold the corpus still

Every arm must review the same bytes. Hash the corpus before the run and re-verify
against that hash while it runs: a formatter invoked for any reason, a stray checkout, or
any tool that rewrites files in place changes the tree mid-measurement, and arms that ran
before and after it are not comparable. When that happens the run is void — restart it
rather than reporting it with a caveat, because a caveat does not restore comparability.

## 9. Repeat the measurement

One pass per arm is an anecdote, not a measurement, and it can invert a conclusion.

Run the same arms against the same corpus at least twice, and report each arm's spread
beside its score. In the run this rule comes from, the first pass put the rubric-less arm
at a perfect score — reading as "the instructions change nothing" — and the second put it
well below the instruction-carrying arm, which held its perfect score both times. The
finding reversed, and only the repeat exposed it. **The arm that moves is the arm that
looked perfect on a single pass**; at n=1 a stable arm and a lucky one are
indistinguishable.

- Report the delta, not just the mean. An arm with a wide spread and one with none are
  not the same evidence even when their averages agree.
- A verdict that survives both runs is worth stating confidently. One that appears in a
  single run only is provisional, and should be labelled so.
- Concurrent load inflates wall-clock. If a repeat runs beside another job, its timings
  are not comparable to the first pass — say so, and compare recall rather than time.
- **Equal arms is a result.** When every control arm solves the task from priors, the
  fixture has no headroom and the honest report is "no measurable difference" — not a
  sharper metric, and not another re-cut of the task until it separates. A strong model
  solving a task it was never given guidance for is evidence about the model, not about
  the guide.

## 10. Challenger vs the incumbent you already run

A vendor's benchmark answers "is this better than the systems they chose to compare
against", not "is this better than what I have". The incumbent is part of the experiment.

- **Run the control arm on your own configuration.** A challenger's "native memory"
  baseline is often a configuration that does not retrieve at all; if yours already does,
  the published delta can vanish at small scale. Measured on one library: the vendor
  claimed 24–57% for native memory, and the incumbent scored 93% on the same probe set.
  That is not a refutation of the product — it is a refutation of the baseline.
- **Look for the threshold, not the average.** When the incumbent has a hard capacity
  limit, the result is a step change: parity below the limit, a widening gap above it.
  Size the corpus to cross the limit, or run two sizes, and report where the gap opens
  and what mechanism bounds the incumbent (a character cap, a context window, a TTL).
  One mid-size run reports "no difference" and is true only at that size.
- **Probe taxonomy.** Exact recall, temporal supersession (the value changed later —
  score the current value and record whether the stale one also appears), multi-hop
  (two facts joined), paraphrase (deliberately avoids the corpus's own vocabulary) and
  abstention (never stated; a fabricated value is the failure). Paraphrase separates
  retrieval from keyword matching; without it a full-text index scores as semantic recall.
- **Score the final answer block, not the reasoning trace.** A trace recites the recalled
  text verbatim and will credit an arm that retrieved nothing it could use.
- **Cost the challenger in its own units.** Per-turn input tokens, p50 *and* p90 latency
  (a recall round-trip lands in the tail even when medians tie), and background work —
  extraction or consolidation jobs that never appear in the session's token ledger.
- **Same history, two ingestion paths.** Both arms receive the identical corpus through
  their own pipeline. When replaying transcripts, say so: the challenger stamps its own
  wall-clock date, so a temporal claim is then about the text, not the timestamps.
- **Audit each claim separately.** A claim can be true about the architecture and false
  about your install. Mark each one reproduce / refuted / confirmed / untested, and put
  the untested ones in the verdict rather than letting them disappear.
- **A narrower result is still a result.** "Buys immunity to the cap, not better recall"
  is the kind of finding that survives a repeat; "the product is good" is not.

## Pitfalls

- **Choosing the rule after seeing the numbers.** The experiment cannot fail, so it has
  decided nothing. Fix the rule and the test first.
- **Comparing unequal costs.** You measured cost, not design.
- **Comparing runs at different sampling depths.** When the score is derived from the
  findings, a shallower run scores higher because it found less, and the improvement is
  the measurement artifact.
- **Attributing a bundled design's advantage to the whole bundle.** You learn that the
  bundle differs, not which part earns its place.
- **Truth by diff across refactors.** Every unrelated refactor enters the truth set and
  recall collapses toward zero for reasons that have nothing to do with the claim.
- **A saturated or already-clean corpus.** Both produce a non-result that reads like a
  result. Check discriminating power before the run.
- **Unblinded labels.** The labeller reproduces the hypothesis you are testing.
- **Counting matched findings instead of distinct defects.** Rewards verbosity.
- **Trusting an exit code over output.** A silent arm looks like a clean arm.
- **Reporting only the hoped-for branch.** State the decision the rule forces in both
  directions, including the one that kills the thing you built.
- **A ratio rule with a zero denominator.** `infinity >= threshold` reads as a win on a
  corpus where nothing true was found. Emit UNDECIDED instead.
- **A corpus contaminated by the repo it was copied from.** Its pre-existing defects
  count as false positives against the arm thorough enough to report them, penalising
  exactly the behaviour being measured.
- **A deliverable that lives in a separate command.** The run completes and the artefact
  the next step depends on was never written.
- **Handing a human a labelling sheet for a corpus that cannot discriminate.** Spend
  their attention only on a corpus that can separate the arms.
- **A seeded defect the project's own gate already catches.** It measures the gate, not
  the reviewer, and it makes the corpus fail the very gate it is judged by.
- **Checking the gate without building.** `--no-build` evaluates checks and skips the
  builders that fail, so a broken corpus reports success.
- **Mutating the corpus mid-run.** Arms before and after are not comparable, and the
  measurement is void rather than merely noisy.
- **A ratio rule with no headroom in the corpus.** The corpus size decides the verdict,
  and the result reads as a finding about the design.
- **A finding inherited from a stale document.** Confirm against the current revision
  before repeating it; a fixed defect reported as open discredits the true findings
  beside it.
- **Exclusive nearest-match attribution.** Assigning each finding to its closest truth
  entry under-counts recall when two defects share a matching window, and the totals
  look fine. Match non-exclusively.
- **A distance that ignores the path.** A finding then matches a defect in another file,
  reporting zero false positives for every arm.
- **A benefit measured at one corpus size.** When the incumbent has a capacity limit, a
  single mid-size run reports parity that holds only below the limit.
- **Comparing against the vendor's stated baseline instead of running the control.** The
  baseline is the variable, and it is usually weaker than yours.
- **Scoring reasoning traces.** They recite what was retrieved and turn recall into a
  tautology.
- **One pass per arm.** The arm with the widest spread is the one that looks perfect on
  a single run, and the conclusion drawn from it can invert on the repeat.
- **An aggregation step that materialises empty artifacts.** When nothing was readable, a
  merge that writes one empty result per expected component scores as a clean pass: every
  component reads perfect and a total failure reports success. Leave the outputs missing
  so the error path fires, and test the zero-readable branch directly.

## What the write-up must contain

1. The rule, as fixed, and the fact that it was fixed in advance.
2. The arms, each arm's cost, and why the comparison is fair.
3. The corpus, how truth was established, and whether the corpus discriminates.
4. The numbers — including the ones that argue against the conclusion.
5. The decision the rule forces, stated in both directions.
6. Your own stake in the outcome, if you built or advised on the artifact (see
   `critical-verdict` Self-assessment).
7. Each arm's spread across repeats, not only its best or average score.
