---
name: verify-and-stop
description: Use when proving acceptance or auditing another's work.
version: 1.9.0
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

## When to Use

- The user asks whether something works, is done, or is ready to ship.
- You are auditing an agent's, a session's or a collaborator's completion claim.
- A fix, a guard or a gate needs evidence that it changes the behaviour it names.
- A scored run, a review round or a CI result is about to be quoted as proof.

Not for implementing the fix (`surgical-patch`), or building the gate itself
(`deterministic-quality-gates`).

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

### Name the acceptance target, and observe it there

The proof is about **the thing the user is looking at**, not about something that behaves
the same way. Measured: an agent edited a running app's source, then reported success from a
bare dev server on a new port — HTTP 200 and a blank page, because the boot manifest was
injected only by the full host — and finally validated a *replacement* server on a third
port while the user's page on the original port had already picked the change up. Every
observation was true. None was evidence about the target.

- **Name it before you prove it:** the origin and port, the process or unit, the profile,
  the file path, the binary path. If you cannot name it, that is the one question worth
  asking.
- **Readiness is not liveness.** A port answering, a build succeeding, a file existing, and
  a manifest being present are four different facts. Acceptance asserts the requested change
  at the named target, observed from outside the process that made it.
- **A replacement service cannot prove the existing one changed.** Starting a second
  instance proves the second instance works — and is how an unmanaged server outlives the
  turn.
- **A timeout that kills the process is not a fail-fast assertion.** A test whose
  "non-zero exit" came from the harness killing a hung server passes for the wrong reason.
  Instrument what you meant to observe (the listen call, the response body), not the wrapper
  around it.
- **Run the published artifact at least once, and say which one you ran.** A dev runner
  masks what the shipped binary does: module resolution, settle races, swallowed load
  failures. A test that resolved a previously built copy passes while the source is broken,
  so prove which artifact ran — a version marker, a path, a hash — not merely that a command
  exited 0.

**Run it again after the last edit.** A proof produced before the final change is a proof
of a tree that no longer exists; this is the same rule as the stale-verdict one below, and
it is the one that gets skipped because the edit was "only a doc".

## Rules

- Reuse still-current results only when the repository state still matches. A result
  from before the last edit is not proof of the current tree.
- **Never repeat a passing check for a commit or push, and report only what you ran.**
  Match the evidence to the surface — the focused test that covers the regression beats a
  full-suite rehearsal — and never re-run by hand a check a hook already runs. Name the
  owning test or source scope, the observed result, and a selected-test count that is not
  zero: a filter that matched nothing reads as a pass.
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
- **Name the branch, not only the commit. A green run on one branch is not evidence about
  another.** "Merged" is a claim with the same standing as "passes", and the cheap way to
  be wrong is to prove the work on the branch it was written on and never look at the one
  the user will pull. Ask the target directly, and re-run the proof there — a fast-forward
  carries commits, not a verdict:

  ```bash
  git rev-parse --abbrev-ref HEAD                        # which branch you are actually on
  git status --porcelain                                 # must be empty; `checkout` CARRIES edits across
  git merge-base --is-ancestor <target> <branch>         # exit 0 = fast-forward is safe
  git rev-list --left-right --count <target>...<branch>  # LEFT<TAB>RIGHT; RIGHT is what you land
  git checkout <target> && git merge --ff-only <branch>
  <re-run the gate on <target>>
  ```

  **The right-hand count is ancestry, not content.** The pair is `<target>`-only then
  `<branch>`-only, so `0` on the right means no commit of `<branch>` is missing from
  `<target>` — nothing left to land. Two consequences a reader gets wrong:

  - **A no-op fast-forward changes nothing.** If `<target>` is already ahead, the pair
    reads `3<TAB>0` *before* and `3<TAB>0` *after*; `git merge --ff-only` prints `Already
    up to date` and exits 0. Re-reading the count after a correct no-op and expecting `0`
    reports a landed merge as failed. `0<TAB>0` appears only when both refs point at one
    commit.
  - **A squash or rebase merge keeps the count non-zero with the content landed.** The
    branch's original commits are not ancestors of `<target>`, so the pair stays `1<TAB>1`
    while `git diff --stat <target> <branch>` is empty. Ancestry answers "were these
    commits merged", not "is this change present" — for a squash merge, ask the PR's
    merged state or diff the trees.

  **`git checkout` does not always refuse a dirty tree, and it is never safe to assume
  either behaviour.** When a modified path is identical on both branches the edit is
  carried across silently, so a co-writer's ` M f.txt` follows you onto `<target>` and the
  gate then measures a tree that exists on neither branch. When the path differs between
  the branches git refuses with `Your local changes to the following files would be
  overwritten by checkout` and exits 1. Guard with `git status --porcelain` and stop, or
  clone at your SHA (next bullet) instead of switching; never `git stash` their work.
  Report branch and SHA together — "18 checks pass on `main` at `<sha>`". A SHA alone is
  ambiguous when several branches share the commit, and "green at `<sha>`" read as "green
  on main" is how work that was never merged gets reported as merged. A real merge, as
  opposed to a fast-forward, produces a tree neither branch had, so the target's own gate
  run is the only evidence about it. Check `git branch -a` before concluding there is
  nothing left to land: the branch holding the work may not be the one you were told about.
- **When a shared tree is red for someone else's reason, prove YOUR commit in a clone.**
  A co-writer's uncommitted files break the gate for everybody: an untracked file a check
  references, a half-finished edit, a staged experiment. Do not stash their work, do not
  `git checkout --`, and do not report the red gate as if it described your commit — all
  three lose information or misattribute it. Clone the repo at your SHA and run the gate
  there:

  ```bash
  set -euo pipefail
  D=$(mktemp -d)                        # fresh path: a fixed one reuses a stale clone
  git clone -q . "$D/clean"             # OWN LINE: inside an && chain a failure does not abort
  cd "$D/clean"
  git log --oneline -1; git status --short | wc -l; <the gate command>
  ```

  The clone carries only committed content, so a green run is a statement about your
  commit alone, and the two lines above make it checkable: the SHA is the one you claim and
  the dirty count is zero. Say that you did this and why, because "gate green" measured in
  a scratch clone is a narrower claim than the same words about the working tree. Where a
  gate failure names a file, confirm whose it is before anything else —
  `git status --short <path>` showing `??` or ` M` means it is not in your commit, and the
  fix belongs to whoever is mid-write, not to you.
- **An acceptance claim on a repository needs a gate that is not the repo's own.** The
  suite and the flake gate assert what their author thought of, so they cannot see the
  classes nobody wrote an assertion for — trust boundaries, exposure, a fix that only looks
  like one. This user asks for the council before a milestone is declared verified, and the
  order matters: convene it **advisory over the whole tree**, read **the gate's exit code**
  rather than the prose summary, and treat each blocking finding as a *claim* — reproduce it
  with the `falsifiable_check` it carries before applying anything. Measured: a workflow
  guard written to satisfy one round's finding was itself falsified by four of four samples
  in the next round, because the guard sat inside a file the untrusted input controls — a
  verdict no run of the repo's own gate could ever produce. A green suite beside a red
  council gate is a stale proof, not a green one; the two carry different requirements
  (a score minimum *and* no open blocking finding) and a run can clear one and fail the
  other.
- Run focused checks before wider gates. A focused failure is faster to read and
  cheaper to run.
- Distinguish **pass / fail / unavailable / blocked** exactly. "Could not run" is not
  "passed", and an absent tool is not a clean result.
- **Read the count beside the exit code, then find out why it is zero.** Two causes look
  identical: an empty check set or a selector that matched nothing (a vacuous pass), and a
  cache hit where every derivation was already built for this exact source (a real pass —
  `nix flake check` prints `running 0 flake checks` and then `all checks passed!`). Evaluate
  the set (`nix eval .#checks.<system> --apply builtins.attrNames`) and force one
  (`nix build --no-link --rebuild .#checks.<system>.<name>`) before calling it either. The
  evidence is the number it ran plus the reason it has that number.
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

- **`set -e` does not abort on a failing `&&` operand, so a guard written as a chain guards
  nothing.** Bash exempts every command of an `&&`/`||` list except the last, so
  `T=$(mktemp -d) && chmod 700 "$T"` continues with `T` **empty** when `mktemp` fails, and
  `git clone … && cd … && <gate>` falls through with the cwd still in the caller's tree —
  the gate then measures the tree you were already in and reports it as the thing you
  meant to check. Give each command its own line, or `|| { echo … >&2; exit 1; }` on the
  one that must not fail. Same family as the pipeline-status trap above: the failure is
  real, the status never propagates, and the output reads as success. Measured both ways:
  the chained form printed `FELL THROUGH` and exited **0**; the same failure on its own
  line exited **128**.

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
   falsify. A *recorded verdict* — a review round, a scored gate — is re-derivable the same
   way: re-run the scorer against its stored run directory, because the sample files and the
   scorer are the inputs and the summary's number is only a claim about them.
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
8. **Read the intent statements against the code, and treat a test that agrees with the
   code but not with its own docstring as a defect marker.** A change ships several
   descriptions of what it does — a docstring, a comment beside the constant, the commit
   message, a changelog line, the test's own name — plus the code. When they disagree,
   count which side has more statements: four descriptions of "strict floor" against one
   line that is lenient means the **code** is the bug, not the prose. The tell that this
   survived review is an assertion contradicting the docstring directly above it —
   `"""must not pass on a high"""` over `assert not blocks(..., "high")` — because the
   test was written to match the implementation rather than the intent, so a green suite
   certifies the wrong behaviour. Read each assertion against its docstring and each
   constant against the comment above it before accepting that a passing suite means the
   change does what it claims.
9. **Prove the absence claims too.** A report that says something was *not* done — "these
   edits are pending", "nothing was pushed", "this is not wired up" — is as testable as the
   positive claims, and cheaper: grep the phrase (expect zero hits), count the refs, read
   `git status`. In prose a report that quietly did the work and one that did not look
   identical; the difference is a command's output.

**A claim you cannot measure is not validated by reading it.** Docs prose, "the release is
published", "the image is downloadable" — each is one HTTP request or one grep away. The
cheap checks are the ones that get skipped, and they are exactly where a fabricated or
stale claim survives.

## Auditing an agent's report

A subagent's "all requirements satisfied" is a claim, and its tests are the agent's own
reading of the requirements — the same blind spot as your own suite, one layer out. The work is
a probe you write from the requirement text and run against their tree.

- **Write the probe before you read their tests.** One executable assertion per requirement,
  phrased from the requirement rather than from their implementation, in your own file. A probe
  assembled by reading their tests agrees with them by construction.
- **Let their suite pass on its own terms.** A disagreement between your probe and their tests
  is the finding; a probe that mirrors their assertions has no way to produce one.
- **Exercise the branch the requirement does not name.** Measured: two agents implemented the
  same five requirements, both suites green (17 and 12 tests), and one had left a CLI
  `--dry-run` branch printing a refused URL with exit 0 — the guard sat in the function the
  requirement named, and that branch returned before it. Neither suite covered the branch; one
  probe line did, and the review round scored it two high findings.
- **Run the probe from inside the tree under test.** `python /elsewhere/probe.py` puts the
  probe's own directory first on `sys.path`, so `import pkg` resolves beside the probe and the
  run silently measures another copy. Both arms of a comparison failed identically for exactly
  that reason before it was found. Use `cd <tree> && python -c "$(cat probe.py)"`, or copy the
  probe in and delete it after.
- **Report per requirement, with the path each was observed on.** "5 of 5" survives scrutiny;
  "all good" is the sentence that hid the gap.

The design of a with/without comparison, and how to read a delta smaller than the noise:
`references/controlled-comparison.md`.

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

**When the fix is blocked outside your control, the elimination proof is the
deliverable.** If the remaining steps live in a system you do not own — a remote
endpoint, another team's config, a credential nobody has issued — then the work is to
enumerate the candidate causes and close each one with a measurement, then hand over the
exact ask. Do not ship a change whose effect nobody measured: an unverified patch into
someone else's infrastructure is a claim, and it will be read as the fix. And when a
measurement contradicts a step you yourself proposed earlier, correct it in the same
breath instead of quietly working around it — the owner is acting on your last answer.
"It breaks here, and this is what unblocks it" is a finished result; "this is what I
would try next" is not.

## Failure modes this prevents

- **A milestone declared verified on the repo's own gate alone** — the tests are the
  author's model of the system, so they share the author's blind spots; an advisory council
  round over the whole tree is the independent half, and its *exit code* is what closes the
  claim.
- **Scope growth** — turning a verification task into an implementation task.
- **A suite reported as a working system** — `N passed` offered as proof that the software
  runs, when no command ever executed it. The tests are your model of the software, so they
  share your blind spots; the run does not. See "Run the thing" at the top.
- **Stale proof** — citing a run from before the change being verified.
- **A merge reported from the source branch** — the work proved on `feat/x` and described as
  landed, while the target branch still points at the commit before it. Every number in the
  report is true and the claim is false, which is why it survives review: nothing you ran
  was wrong, you simply never ran it where it mattered.
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
- **A test that certifies the implementation instead of the intent** — an assertion written
  to match the code it sits beside, under a docstring that describes something else. It
  passes, it reads as coverage, and it locks in the wrong behaviour; the disagreement is
  visible only by comparing the two sentences.
- **A green run on one platform reported as a green suite** — the suite's own exit code on
  your machine says nothing about the other targets, and the tests most likely to differ are
  the ones you just wrote. Measured: two tests asserting `str(path.relative_to(root))`
  against a POSIX literal — `['scripts\\real.py'] == ['scripts/real.py']` — passed locally on
  Linux and failed `windows-latest` on the commit that added them, twice. The fix is
  `as_posix()`, and the evidence is the CI matrix's per-job conclusions, not the local
  result: read them by job name (`windows-latest`), because a red job and a green one sit in
  the same run. Where a repo ships to more than one OS, the matrix is part of the proof.
- **A gate reported red without saying whose red** — a shared working tree fails for a
  co-writer's uncommitted file, and quoting that failure beside your own change
  misattributes it. A green run measured in a clone of your commit, with the SHA and a
  zero dirty count beside it, is the narrower and honest claim.
- **A proof about a substitute** — the change demonstrated on a second server, a rebuilt
  artifact on another port, or a fresh copy of the file, while the thing the user has open
  was never observed. Each is a true statement about something else.
- **A stale artifact that satisfied the check** — the run loaded a previously built copy, so
  the new code never executed. Name the artifact, or the proof is about an older tree.
- **A result that arrived for the wrong reason** — a check whose output cannot be
  attributed to the condition under test. Silence from a pipeline that failed upstream
  read as "nothing found", or a gate that went green because its prerequisite was absent
  rather than because the thing was correct. The proof is the result *plus* the reason it
  has that value; without the reason it is a coincidence that happens to look like an
  answer. When you find you reported one of these, correct it in the same breath as the
  next report — a verdict already delivered is not thereby true.
