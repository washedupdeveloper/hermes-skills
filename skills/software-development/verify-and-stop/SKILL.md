---
name: verify-and-stop
description: Use when proving acceptance. Smallest proof set.
version: 1.0.0
author: JuliusBrussee/caveman, adapted by user
license: MIT
platforms: [linux, macos, windows]
category: software-development
metadata:
  hermes:
    tags: [verification, scope, acceptance, proof]
    related_skills: [surgical-patch, deterministic-quality-gates, requesting-code-review]
    source: https://github.com/JuliusBrussee/caveman @ d262ab3882952a59312ff3537cd86d894523c5ab
---

# verify-and-stop

Translate the acceptance conditions into the **smallest sufficient proof set**, run it,
report, stop.

## Rules

- Reuse still-current results only when the repository state still matches. A result
  from before the last edit is not proof of the current tree.
- **A verdict is a snapshot; name the commit and the instant, or it is a claim about a
  moment you never stated.** On a tree another process can write — a background curator,
  a second agent, a CI job, a user reviewing alongside you — `HEAD` moves between your
  last check and your report, and every number you measured silently becomes history.
  Record `git log --oneline -1` and `git status --short` immediately before *and* after
  the proof run; if they differ the proof is stale and gets re-run, not annotated.
  Report the SHA with the result: "18 checks pass at `<sha>`" is checkable, "all checks
  pass" is not. When you discover the tree moved under a verdict you already delivered,
  say so and re-measure in the same breath — a standing property cannot rest on one
  observation, and a green summary is the easiest thing in the world to keep repeating
  after it has stopped being true.
- Run focused checks before wider gates. A focused failure is faster to read and
  cheaper to run.
- Distinguish **pass / fail / unavailable / blocked** exactly. "Could not run" is not
  "passed", and an absent tool is not a clean result.
- Do **not** edit product code unless the verification request explicitly includes
  fixes.
- Do **not** add polish, cleanup, or unrelated tests once the criteria pass.
- **Reproduce the claim before treating it as a defect.** Run the reported command, or
  read the call path. A claimed crash at a line the caller's own precondition makes
  unreachable is not a crash — the honest output is "not reproducible", with the reason.
  Do not add a guard that can never fire to close a finding you did not reproduce; that
  changes behaviour to satisfy a report rather than to fix a defect.
- **A fix is proven by a repro that fails before and passes after.** A green run after
  the edit is not proof: without the failing case, the edit and an unrelated change are
  indistinguishable. Keep the repro.
- **Compare the same metric before and after, and check the line, not only the count.**
  A count that does not move means the fix landed somewhere other than the reported site
  — a checker reports the line it flags, which is not necessarily the line you changed.
  Measure the same way both times.
- **Read the status of the command you mean, not of a pipeline wrapping it.**
  `cmd | tail` and `cmd 2>/dev/null | sed ...` report the *last* stage's status, so a
  `|| echo "absent"` never fires and the failure arrives as **silence** — which reads as
  a negative. Use `${PIPESTATUS[0]}`, or redirect to a file and read `$?` directly. The
  same trap hides in the value, not only the code: when one exit code or one output
  covers two conditions (a `--check` that exits 1 both for drift and for a missing
  prerequisite), the number alone proves neither — inspect the reason. **A check that
  passes for a reason it did not establish is worse than one that failed**, because it
  is reported as a pass. Before quoting a result, say which condition produced it.

- **A number is evidence only if the next person can re-derive it.** A figure measured
  on a fixture that is not in the repository, or against a tool set that has since
  changed, cannot be checked by anyone and quietly becomes folklore that later decisions
  are built on. Replace it with a measurement taken on something the repo **ships**, and
  name the command, so the claim is reproducible in one line. Where the old figure
  supported a real conclusion, keep the conclusion and drop the arithmetic that no longer
  reproduces — do not keep an unreproducible number because the sentence reads better
  with it.
- **Measuring can change the thing you measured.** A verification command that runs tools
  over a fixture may write into it (`nix flake check` creates `flake.lock`), so the next
  run scores a tree the first one altered. Check `git status` on the fixture after a
  measurement pass, and if it moved, restore it before quoting either run.
- **A test of a limit needs an input that crosses it.** A truncation test, a cap, a
  pagination boundary, a "too long" branch — the fixture has to exceed the threshold, or
  the branch under test never runs and the assertion passes for the reason that nothing
  happened. Compute the fixture's real size against the limit before trusting the test,
  and check whether an upstream bound makes the boundary unreachable from the input you
  chose: a body that lists at most N items cannot reach a byte cap that N short entries
  never fill, so the test silently stops testing. The same failure in miniature is a
  placeholder assertion left in a file (`assert x or True`): it cannot fail, so it proves
  nothing while reading as coverage. Delete it or make it assert — and when a test was
  written around the wrong fixture, say that the test was wrong rather than that the code
  passed it.

## Stop condition

Stop immediately when the acceptance proof is complete. Report the commands, their
results, and any unresolved risk — nothing else.

**An unresolved item is not a deliverable until it carries a decision.** This user
rejects a report that ends on a list of open questions — the ask is "solve this, or
decide a course of action to move forwards". So every risk or gap you name goes out with
one of three things attached: what you did about it, the decision you made and the reason,
or the single question that genuinely needs them with the options ranked and one
recommended. A flag with no next step reads as work handed back, however well documented
it is — and a defect found while investigating a flag is worth more than the flag itself,
so look before escalating.

## Failure modes this prevents

- **Scope growth** — turning a verification task into an implementation task.
- **Stale proof** — citing a run from before the change being verified.
- **Silent downgrade** — reporting a check that never ran as if it had passed, which
  is the failure `deterministic-quality-gates` names "absence is not cleanliness".
- **Post-pass polish** — more edits after the criteria are met, which invalidates the
  proof that was just produced.
- **Phantom fixes** — editing code to satisfy a report that was never reproduced. The
  change is real, the defect was not, and the next reader inherits a guard or a branch
  that cannot be reached and cannot be explained.
- **A count quoted instead of measured** — repeating a number from a report as if it were
  a measurement. Quote the number you ran.
- **A result that arrived for the wrong reason** — a check whose output cannot be
  attributed to the condition under test. Silence from a pipeline that failed upstream
  read as "nothing found", or a gate that went green because its prerequisite was absent
  rather than because the thing was correct. The proof is the result *plus* the reason it
  has that value; without the reason it is a coincidence that happens to look like an
  answer. When you find you reported one of these, correct it in the same breath as the
  next report — a verdict already delivered is not thereby true.
