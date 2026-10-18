---
name: verify-and-stop
description: Use when proving acceptance. Smallest proof set.
version: 1.3.0
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

## Run the thing. A passing test is not the proof.

**This is a standing rule, not a suggestion for some tasks.** Testing establishes that the
code you wrote does what your assertions say. It does not establish that the *software
works*, because the assertions are yours and the failure modes you did not think of are
exactly the ones no test names. So after the suite is green, **execute the artifact and
observe it**: boot the VM, run the binary, invoke the CLI verb, build the toplevel,
`curl` the endpoint, open the file the generator produced. Report what came back.

The gap this closes is not theoretical. Measured in one session:

- a suite at **532 passed** on a repository whose e2e VM test had **never been run by
  anyone or anything** — it passed when invoked by hand, and no gate or CI job named it;
- `nix flake check` reported **all checks passed** while the machine toplevel was never
  built, because the checks it knew about did not include one that builds it;
- a machine added to a cluster passed `system`, `home` and `structure` — and its toplevel
  **failed to build** on a missing generated secret. The tests were right; the software
  was broken;
- a guard I had just written passed in the exact case it was written to catch, because
  the option it tested was set by an unrelated module. Only a mutation said so.

What "run it" means, by artifact:

| you built | the proof is |
| --- | --- |
| a CLI or script | the verb executes and prints the thing you changed |
| a service | it starts, its unit is `active`, and its own config parses |
| a NixOS/home-manager config | `system.build.toplevel` **builds**, and a VM boots it |
| a library | a caller in another process imports and uses it |
| a generator or copier | the output file exists and its content is what you claimed |
| a container | the image builds and the entrypoint runs once |

**A test that requires a fixture you cannot supply is a blocker, not a pass.** Say
"unproven: needs `<thing>`", never "covered". And when the run contradicts the suite, the
run wins — the suite is a model, the run is the system.

**Run it again after the last edit.** A proof produced before the final change is a proof
of a tree that no longer exists; this is the same rule as the stale-verdict one below, and
it is the one that gets skipped because the edit was "only a doc".

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
- **An acceptance clause is proven by a command that something runs, and a harness that
  cannot express the clause is a blocker rather than an excuse.** A test can exist, pass,
  and be invoked by nobody: an attribute deliberately kept out of the main gate (a VM test
  needing KVM) with no CI job naming it either, so it runs only when a human remembers the
  command — and a document citing it as acceptance evidence is citing something nobody
  triggers. Before reporting a clause as covered, name the command **and** the thing that
  invokes it on every change (`grep -rn '<attr>' .github/workflows/`). When a clause has no
  test at all, inspect the harness before writing "not covered": a test double that carries
  its own copy of the system's configuration table makes the new case *unrepresentable*, so
  the double is the defect. Parameterise it and the clause becomes testable; declaring it
  unprovable instead ships the gap and records it as a decision.
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
- **A derived claim is only as good as the stability of its inputs — test the weakest one
  before calling it proven.** When a conclusion is computed from several measured values
  (an interval from a set of scores, a threshold from two classes, a projection from a
  rate), the arithmetic can be flawless and the conclusion still wrong, because it inherits
  every assumption underneath. Enumerate what the derivation takes for granted, rank them
  by how likely they are to be false, and test the top one *before* the claim is written
  down. The usual culprits: that each input is a stable measurement rather than one sample
  of a noisy process; that the inputs were measured under the configuration that actually
  ships; and that the members were correctly classified in the first place. "Proven" is a
  claim about the assumptions, not about the arithmetic — and a derived number that ships
  into a document is far more expensive to retract than to test, because everything
  downstream restates it.
- **Do not state a property in a summary that you have not run a command for.** A closing
  report invites asides — "the mirror is in sync", "no other file references this", "the
  config was untouched" — and each is a claim with the same standing as the ones you
  measured. Either run the check and say what it returned, or mark it as unverified. The
  cheap failure mode is worse than the expensive one: an aside is read as a finding because
  it sits beside findings, so an unchecked one launders an assumption into the record.
- **Measuring can change the thing you measured.** A verification command that runs tools
  over a fixture may write into it (`nix flake check` creates `flake.lock`), so the next
  run scores a tree the first one altered. Check `git status` on the fixture after a
  measurement pass, and if it moved, restore it before quoting either run.
- **A new guard is unproven until you have watched it fail.** A check, validation or lint
  rule you just wrote asserts something about the world; the only evidence it asserts
  anything is a run where the world is wrong and the guard says so. Prove it by
  **deliberately breaking the thing it guards**, one break at a time: apply a break that
  actually changes the behaviour the guard observes, run the guard, confirm it exits
  non-zero **and** its message names the right cause, then restore and confirm the clean
  run returns. **A mutation that leaves the behaviour unchanged proves nothing**, and it
  reads exactly like a guard with no teeth. When the fix has redundant layers — a
  directory filter *and* a suffix filter, a length cap *and* a regex, two independent
  conditions that each reject the same input — removing one leaves the other doing the
  job, so a single break produces a clean run and you conclude the test is vacuous when
  the test was fine and the mutation was insufficient. Remove **every** layer before
  concluding that, and check the failure you finally get reproduces the original symptom
  rather than a new one. Two to four distinct breaks is enough, and they should differ in
  kind rather than in spelling — a wrong value, a missing dependency of the guard, and a
  boundary the guard derives rather than hardcodes exercise three different failure paths.
  **The negative fixture must differ from the good one in exactly the thing under test.**
  A test asserting "no drift" fails for the wrong reason when its tree also carries a file
  the source genuinely lacks: the assertion is correct, it is reporting a real defect, and
  it is not the one you planted — so the run proves nothing about the rule you added and
  the fixture has to be trimmed until that is the only difference left. Restore is part of
  the procedure: a guard proven by leaving the tree broken is a worse outcome than an
  unproven one. Print the verdict
  per break (`FAILED AS EXPECTED` / `PASSED — NO TEETH`) rather than eyeballing four runs,
  and re-run clean at the end so the report ends on the state you are shipping.

- **A guard that extracts its own evidence must assert the extraction found something.**
  A check that greps a list out of a file and then compares it to another list passes
  vacuously once the pattern stops matching, because it is comparing two empty results.
  `test -s <extracted>` before the comparison is the difference between a check and a
  formality — and the same shape covers any `grep -c` that could return 0 for the wrong
  reason.

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

## Auditing commits you did not write

When the ask is "validate these commits" — another agent, another session, a collaborator —
the subject is *claims*, not style. Re-derive each one; a commit message is a hypothesis.

1. **Enumerate before reading.** `git log --oneline --format='%h %ad %an | %s' --date=format:'%H:%M' <base>..origin/master`.
   Fetch first: the branch you were told about may not be the tip. **If you were given
   the writer's session id, read that as well.** The commit message is a summary of a
   measurement; the session holds the measurement and the intent, including what the
   writer believed it had proved — and that belief, not the code, is the claim you are
   testing. It also tells you which of their numbers were derived and which were quoted.
2. **Scope every commit.** `git show --stat --format='' <c>` per commit. A subject naming
   one concern that touches six files is a swept commit — say so, because the message is
   then evidence about nothing.
3. **Check revert pairs for net zero.** `git diff <A>^ <revert-of-A>` empty means the pair
   is honest churn rather than dead code left behind. A non-empty diff means the revert is
   partial and the tree carries both.
4. **Re-run the gate and suite yourself at the tip.** A commit message that says "all
   checks pass" is the least reliable input in the audit; it is also the cheapest thing to
   falsify.
5. **Re-derive every quantitative claim against its source record.** Where a figure appears
   in a doc, a manifest and a run record, read all three: the record is the authority, and
   the copies drift in the direction of the more impressive number. A summary that
   contradicts a sentence two paragraphs later is the tell.
6. **Read CI per job, by name.** With no `gh` available, the API is enough —
   `curl -s .../actions/runs?per_page=30 | jq` to find the run by `head_sha`, then
   `.../runs/<id>/jobs` for each job's `conclusion`. A run-level green hides a red job, and
   when a log needs rights you do not have, `.../check-runs/<job_id>/annotations` is served
   unauthenticated on a public repo and names the failing test.
7. **Report per commit, and say whose defect it is.** "Sound", "defect in their claim",
   "defect in mine" — the third happens and belongs in the report, not in a footnote: an
   audit that only ever finds faults upstream is not an audit. Say what the fix is and
   whether it is already in.

**A claim you cannot measure is not validated by reading it.** Docs prose, "the release is
published", "the image is downloadable" — each is one HTTP request or one grep away. The
cheap checks are the ones that get skipped, and they are exactly where a fabricated or
stale claim survives.

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
- **A suite reported as a working system** — `N passed` offered as proof that the software
  runs, when no command ever executed it. The tests are your model of the software, so they
  share your blind spots; the run does not. See "Run the thing" at the top.
- **Stale proof** — citing a run from before the change being verified.
- **Silent downgrade** — reporting a check that never ran as if it had passed, which
  is the failure `deterministic-quality-gates` names "absence is not cleanliness".
- **A proof nobody triggers** — a suite that passes when run by hand and is named by no
  gate and no workflow. Coverage that exists in the tree and nowhere in the process, so
  every later change is verified by the one thing that was never wired up.
- **Post-pass polish** — more edits after the criteria are met, which invalidates the
  proof that was just produced.
- **Phantom fixes** — editing code to satisfy a report that was never reproduced. The
  change is real, the defect was not, and the next reader inherits a guard or a branch
  that cannot be reached and cannot be explained.
- **A count quoted instead of measured** — repeating a number from a report as if it were
  a measurement. Quote the number you ran.
- **A green run on one platform reported as a green suite** — the suite's own exit code on
  your machine says nothing about the other targets, and the tests most likely to differ are
  the ones you just wrote. Measured: two tests asserting `str(path.relative_to(root))`
  against a POSIX literal — `['scripts\\real.py'] == ['scripts/real.py']` — passed locally on
  Linux and failed `windows-latest` on the commit that added them, twice. The fix is
  `as_posix()`, and the evidence is the CI matrix's per-job conclusions, not the local
  result: read them by job name (`windows-latest`), because a red job and a green one sit in
  the same run. Where a repo ships to more than one OS, the matrix is part of the proof.
- **A result that arrived for the wrong reason** — a check whose output cannot be
  attributed to the condition under test. Silence from a pipeline that failed upstream
  read as "nothing found", or a gate that went green because its prerequisite was absent
  rather than because the thing was correct. The proof is the result *plus* the reason it
  has that value; without the reason it is a coincidence that happens to look like an
  answer. When you find you reported one of these, correct it in the same breath as the
  next report — a verdict already delivered is not thereby true.
