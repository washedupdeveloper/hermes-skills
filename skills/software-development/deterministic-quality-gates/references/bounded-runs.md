# Bounded runs: slicing, deadlines, and the instrument probe

A producer that answers a small request can still never answer a large one, and a large
change is many requests. This is how a run stays finite, honest about what it did not
look at, and started only when the machine can actually run it.

## The arithmetic

- Per-call timeout `T`, one retry: up to `2T` per sample.
- A change sliced into `U` units: up to `U x 2T` for the run.
- Measured: 67 units at 180 s per sample is over three hours worst case; a 300 s
  run-level budget finished the same run in about six minutes with 3 units reviewed
  and 64 recorded as unreviewed.

Bound the aggregate, not only the call. A per-call timeout answers "will this call
return?"; it does not answer "will this run end?".

## Slicing a change too large for one prompt

- Try the whole change first. If its prompt exceeds the input budget, split by **file**
  (a file whose prompt fits is one unit).
- A file that does not fit is split by **hunk**, and each hunk keeps the file header so
  it still parses as a patch.
- Each unit records: id, files, line ranges, diff digest, context digest and depth,
  prompt bytes, samples run, findings, its own verdict.
- A finding belongs to the unit whose ranges contain its location; merge findings across
  units by the same key the whole run uses (dimension, path, line).
- An **unreviewed** unit (samples returned nothing, or it was never asked) makes the run
  `INCOMPLETE` — never `PASS`, and never silently dropped.

## The run-level budget

- Use **seconds**, not units: machine speed varies, and a unit count does not bound wall
  time.
- Check the budget before starting each unit; the unit in flight is allowed to finish.
  Cutting a sample mid-prompt yields half an answer and a failure that says nothing about
  the code.
- Record every skipped unit with `samples_run: 0`, `ok: false` and its reason (for example
  `"time budget exhausted"`).
- Write the budget into the verdict artifact, so the deadline that produced the unit set
  is part of the evidence.
- A run with a skipped unit cannot `PASS`. If an unresolved finding already made it
  `INCOMPLETE` or `FAIL`, keep that verdict but append the unreviewed units to the reason:
  the reason is the human summary, and naming only the first cause hides the missing
  coverage.

## Probe the instrument before the run

A `doctor` command separates hard failure from degradation:

| check | absent means | exit |
|---|---|---|
| `git` | cannot review at all | fail |
| the reviewer binary | cannot ask anything | fail |
| `bwrap` (or the sandbox) | command proofs become `UNRUNNABLE` | warn, exit 0 |
| profile liveness | the instrument is dead | fail |

The liveness probe is a one-line prompt with its own short timeout; report the seconds it
took to answer. That number is advisory: a producer that answers a 20 s probe may still
never answer a 5 KB review prompt, so the probe proves *liveness*, not capacity.

Warnings keep exit 0 on purpose: a machine without the sandbox can still review findings
that use tree-reading proofs (`present`, `diff`, `schema`), and a doctor that fails there
would forbid a run that is merely degraded.

## Reasoning effort is part of the instrument

`hermes chat` accepts `--reasoning LEVEL` (`none` … `ultra`); without the flag the
profile's `reasoning_effort` applies. A high level is invisible to a one-line probe and
can consume the whole deadline on a long-output prompt. Measured on one 7,954-byte review
prompt against the same model:

| level | result |
|---|---|
| profile default (`ultra`) | no answer in 90 s, twice |
| `low` | no answer in 150 s |
| `minimal` | empty answer at the 150 s boundary |
| `none` | 21 s |

- Select the level explicitly in the harness, write it into the run's metadata, and hash
  it into the instrument digest. Two levels are two instruments, not one with noise.
- A level that answers is not yet a reviewer: on a tree with a planted credential,
  `none` returned a `critical` finding in 11 s, while an unvalidated level can return
  well-formed empty sections. Plant a defect before trusting an empty result.
- For CI, choose the level the host actually answers at and expose it as an input; a
  pipeline that inherits the profile's highest level times out on every diff.

## Report the envelope, not a verdict about the model

Measure and write down what the instrument does: trivial prompt latency, the size of the
review prompt that did return, the sizes that did not, and the sample count. Put it in the
README's known limits, not in a promise that the next run will be better.

Never relax "a missing answer cannot pass" to make a bounded run finish. The deadline
makes the run finite; the unreviewed-unit rule keeps it honest.
