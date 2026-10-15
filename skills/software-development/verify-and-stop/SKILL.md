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

## Stop condition

Stop immediately when the acceptance proof is complete. Report the commands, their
results, and any unresolved risk — nothing else.

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
