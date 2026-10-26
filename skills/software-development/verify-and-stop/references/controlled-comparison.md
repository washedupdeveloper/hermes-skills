# Controlled comparison

For a claim of the form "does X help?" where X is a process, a prompt format, a structure or a
tool. The alternative is an anecdote dressed as evidence, and this user asks for the test.

## Design

1. **One variable.** Copy the starting tree twice. The only difference between the arms is the
treatment. Same model, same toolset, same scope and reporting instructions.
2. **Identical information, and say when it is not.** If the treatment carries more detail than
   the control, the test measures packaging plus content. State that in the result; it biases
   the comparison toward the treatment, which only strengthens a negative finding.
3. **An independent measurement.** The arms' own tests are theirs. Write the probe from the
   requirements (see "Auditing an agent's report" in SKILL.md) and run it in each tree.
4. **A second, blind scorer where one exists.** A review round with fixed scope and sample count
   scores the artifact, not the judgment that produced it. That makes it evidence about the
   code, never about whether the structure made the agent smarter.
5. **Record the confounds before running**: one model, one task, N samples, repository size,
   and the wall-clock and token cost of each arm.

## Set up the arms so they differ in one thing only

- `git init` the base and commit it *after* a test run, or `__pycache__` and other build output
  land in the base commit and then differ between arms for reasons unrelated to the change.
  A `.gitignore` in the base commit is part of the experiment, not housekeeping.
- `cp -r . ../arm-b` copies `.git` as well, which is what you want for two independent arms,
  but check `git log --oneline -1` in each before the agents start.
- Keep the probe outside both arms and run it as `cd <arm> && python -c "$(cat probe.py)"`.
  `python /path/to/probe.py` imports the package beside the probe, not the arm's.
- If the arms' results are committed, commit them under one identity with an obvious message so
  the review round sees a clean tree and scores the change rather than the leftovers.

## Reading the result

- **A delta inside the noise is not a result.** Two samples, one task, one model is a pilot. Say
  "no measurable difference"; never "X is better".
- **Absolute scores do not travel.** A threshold calibrated on real repositories scores a
  scratch repository in the 50s. Only the delta between arms is meaningful, and it is meaningful
  only because both arms sat under the same gate and threshold.
- **A negative result with a mechanism is the valuable one.** "The treatment arm skipped a
  path" explains why; "it scored 2.9 lower" alone does not, and cannot be acted on.
- **Cost belongs in the verdict**: tokens of brief, wall-clock, tests written. A treatment that
  buys uniformity at three times the brief is a trade, not a win.
- **A report-only mode never satisfies a gate.** An advisory run cannot apply a fix, so it
  escalates by design and exits non-zero. Read its outcome and score, and never call that exit
  code a failure of the tool.

## Measured example

Prose brief (278 tokens) against a validated four-artifact change (874 tokens), the same five
requirements, two isolated agents:

| | prose | spec |
|---|---|---|
| requirement probe | 8/8 | 8/8 |
| tests written | 17 | 12 |
| wall-clock | 176s | 123s |
| early-return path | covered | **escaped** |
| review aggregate | 52.96 | 50.07 |

The finding that mattered was not the score. The spec narrowed behaviour to its scenarios, so
an unstated branch was not implemented while the result still looked complete — which is why a
spec needs a scenario for every path that can return before the guarded call.
