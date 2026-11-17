---
name: critical-verdict
description: "Use when asked to judge viability, quality or soundness."
version: 1.1.0
author: Storm, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
category: software-development
metadata:
  hermes:
    tags: [review, evaluation, verdict, evidence, sources, bias, self-assessment]
    related_skills: [grounded-citations, requesting-code-review, deterministic-quality-gates]
---

# critical-verdict

Judging whether something is viable, sound, or worth keeping — a design, a repo,
a tool, a claim — and answering with a verdict whose evidence the reader can check.

The failure mode this skill prevents: a confident verdict resting on the artifact's
own documentation, its author's optimism, or the assessor's own work.

## When to Use

- "Is this viable / sound / worth keeping / good enough?"
- "Be a critical reviewer of this" / "be as self-critical as possible".
- Comparing an implementation against a reference implementation — see
  `references/reference-implementation-comparison.md`.
- Assessing work the agent itself produced. The hardest case, and the one the
  rules below exist for.

Not for: reviewing a diff before commit (`requesting-code-review`), or
fact-checking a single claim (`grounded-citations`).

## The output contract

Answer in this order. The reader is checking the reasoning, not just the verdict.

1. **Verdict first, in one paragraph.** Say plainly what is viable and what is not.
   Split it when the honest answer is split: a sound concept in an unsound
   implementation is one sentence, not a hedge.
2. **The load-bearing claims, each with its evidence.** For every claim the verdict
   rests on, state what would have to be true and what you actually found. A claim
   that was never tested is the most important thing to report, not to pass over.
3. **Sources, each with its bias.** A table: source, what it establishes, and its
   incentive or status. Include the ones you could not verify and label them. The
   reader asked for sources to check *your* bias; an unqualified list fails that.
4. **Your own conflict**, in its own paragraph. See Self-assessment below.
5. **What would change the verdict** — the cheapest test that would falsify it.
   Name one decisive experiment rather than adding more prose. When that experiment
   is actually going to be run, follow `references/decisive-experiment.md`.

## Rules

**Read the artifact, not its description of itself.** Code beats a docstring,
a docstring beats a README, a README beats a roadmap. A claim sourced to the
project's own prose is unevidenced until you confirm it in the artifact.

**A replica can be newer than the source it is built from.** When a repo installs a
copy of itself — a skill into a library, a generated artefact into a tree, a mirror —
do not assume the destination is the stale one. Run the tool's own check mode and diff
in both directions before any sync: the installed copy may hold text the source lacks,
and writing the source over the destination deletes it. A check that reports drift says
the two disagree, not which one is right.

**Hunt internal contradiction — it is the strongest evidence and the cheapest.**
When a docstring asserts X and the code a few lines later does Y, that is a
finding, and it costs one grep. Grep the artifact for its own claim's vocabulary
and check each hit against the implementation. Assertions in comments, type
names, and docs are all testable against the code they describe.

**Follow the policy boundary, not only the logic.** Find every setting the artifact reads
from the thing it is judging — a config file in the reviewed repository, a request header, a
plugin's manifest — and ask what that input is allowed to change. A rule engine can be
flawless while the artifact hands its own safety switch to the input: a sandbox the reviewed
repository can disable, an allowlist it can widen, an output path it can redirect.
*Check:* name the loader, then name what the untrusted side controls. A boundary the subject
can move is not a boundary, and it is invisible to tests that only feed the boundary trusted
values.

**A document that contradicts the code is a defect to repair, not only to report.** When
the verdict is "the implementation and the plan disagree", the plan is part of the
artifact and the disagreement is the plan's to fix. Repair it in the same pass, because a
plan is the first thing the next reader — human or agent — opens, and one describing an
abandoned design is worse than no plan: it is confidently wrong about the thing the reader
is trying to change. Correct the status/header block first (that is what gets read), then
state each delta as a **decision** rather than an omission — "one reviewer sampled N times",
not "the five specialists were not built" — and keep the superseded section as the
historical record instead of rewriting it. A plan whose own sections contradict each other,
one saying a component does not exist and another saying it was built, discredits every
true statement beside it.

**Check whether the central claim was ever measured.** Absence of a benchmark, an
ablation, or a control is a finding, not a gap in your knowledge. Name the missing
measurement explicitly: "X has never been compared against a baseline." Most
over-built systems are over-built in exactly the dimension nobody measured. When you
then run it, fix the decision rule before the first run and make the artifact enforce
it — a rule chosen after the numbers cannot fail, so it decides nothing.

**Grade evidence by provenance, and label it inline.** Peer-reviewed > preprint >
vendor benchmark > blog > the project's own docs. Never let a vendor's number sit
beside a peer-reviewed one unmarked, and say when a number is a vendor's own
benchmark of its own product.

**Search for the counter-evidence deliberately.** A verdict built only from
supporting sources is advocacy, not assessment. If the honest answer is that the
literature contradicts the artifact, that is the verdict.

**A recommendation with alternatives must name their kind.** An instrument, an objective and a
workaround are not three answers to one question, and listing them as peers pushes the reader
toward whichever sounds cheapest. When the honest structure is "this is what we want, this is how
we would know whether we got it, and this is the fallback if that fails", write that sentence
instead of a menu — and if you do rank options, put the actual recommendation first rather than
the most defensible-sounding one. Measured: presenting *measure / enforce / reduce* as A / B / C
drew the correction that A was only an instrument and C was the goal. It was, and the menu had
implied otherwise; a false choice costs the reader the work of noticing it.

**Separate "it works" from "it earns its place".** A thing can be correct and
still not be worth its cost in moving parts, latency, or maintenance. Say which
question you are answering.

When the answer is that it does **not** earn its place, recommend **deleting** it
rather than keeping it by default. Version control already preserves it, so removal
costs one commit to look up later, while unjustified machinery is paid for on every
future read; "we might need it later" is not an argument when the commit *is* the
record. If you cannot argue for keeping something on the evidence, the honest verdict
is to remove it — and say so plainly rather than leaving the decision hanging.

**"It works" is not "they can get it."** For anything built for a different user
than you, test obtainability before quality: can the intended user actually acquire
it? A component that requires the very thing it was written to avoid, and is
published nowhere, has a path strictly worse than doing nothing — the user installs
the dependency anyway and then gets an extra step on top. Ask where it ships from,
and whether the pipeline that produces it exists at all. If not, the verdict is
**finish the distribution step** or **delete the component**; both beat defending it
because it functions.

**When the artifact reports a metric, ask what data it was measured on.** A
perfect score on the data a threshold was fitted to is circular, and a calibration
sample of one is not a calibration. When *you* produce the number, hold out a disjoint set written before the tuning and report
that delta; the fitted figure only proves the tuning set was too easy. Look for the eval set's provenance before
trusting the number.

**Quantify where the artifact quantifies.** "Genuinely useful" is a claim; the
number behind it is the evidence. Inventory by count, not by impression.

**Verify before asserting a defect.** Read the code path that would have to be
wrong, and quote it. A critique aimed at the wrong layer is worse than no critique,
because it is actionable and wrong. Two mechanisms that manufacture confident false
findings, both cheap to rule out:

- **A count that counts something other than what you think.** `git grep -c … | wc -l`
  emits one line per matching *file*, so it returns the number of files, not the number
  of occurrences — reading it as "declared twice" when the option appears once is the
  error this rule exists to prevent. Count occurrences explicitly before claiming
  duplication or redundancy. The same trap is a definition count: `^def test_` misses
  `async def` and every method inside a class, so a regex census undercounted one suite by
  19% (10,593 against 12,605 by AST) — and the low number then "corroborated" a story
  about shallow tests. Parse the tree when a count carries a claim; a regex is a quick
  look, not a measurement.
- **A claim inherited from an earlier document.** A run record, a previous verdict, or
  your own earlier summary describes the artifact *at the time it was written*. Confirm
  it against the current revision before repeating it. One stale finding discredits every
  true finding printed beside it, and the reader has no way to tell them apart.
- **A project's own known-gaps list ages in both directions.** A threat model or a
  limitations section is a claim like any other: it may still list a gap the code has
  since closed, and a defect quoted from it is unverified until the tree confirms it.
  When the document and the tree disagree, report the direction, because "the document
  understates the code" is a finding against the document, not against the code.
  Measured: a threat model's "independent copies that can drift" described eleven-line
  re-export shims that cannot drift.
- **A claim means what its own example shows.** "`mkForce` on a sub-attribute" meant the
  nested option path, not a key inside the attrset; a counter-fixture built on the other
  reading produces a confident false finding. Re-read the claim against its worked example
  before refuting it, and check a tool's own registry before calling a documented command
  stale — a verb can be absent from one build's audience rather than removed.
- **A result read through a pipe that keeps only the last lines.** A command that prints
  one summary per section emits several lines, and showing only the final one makes "it
  ignored my second argument" and "it reported 48/58" both look true while the hidden
  line above says otherwise. Read the whole output, or search it for the exact line the
  claim depends on, before writing the finding down — the same pipe also masks the exit
  status, so a failing check reads as a pass.
- **A setting that parses, validates, and is read by nothing.** Before trusting a
  documented key, grep for the code that consumes it (`cfg["review"]["mode"]`,
  `settings.get(...)`). A field whose only reader is its own validator is inert: the
  file is correct, the value changes nothing, and the user is left believing they
  configured something. The tell is two layers disagreeing about a default — the config
  says one value, the command line another — where neither is a typo, because only one
  layer is load-bearing. The tested contract decides which one moves.
- **A live checkout is not a fixed artifact.** When another session, agent or person may be
  writing the tree, read from a pinned copy — `git worktree add --detach <sha>` — and cite
  the sha in every finding. One module measured 394 lines and, minutes later, 273, because
  the file was being refactored underneath the read; a line number quoted from the moving
  copy is a claim nobody can reproduce, and a finding aimed at the wrong revision is
  actionable and wrong. The commit is the artifact; the working tree is a draft. The same
  rule settles the report: say which commit you reviewed, and when the file moved
  mid-review, re-read the changed hunk before repeating what you concluded about it.

**A finding and its prescribed remedy are two claims — verify them separately.** A
review that diagnoses a defect correctly can still prescribe a fix that does not work,
and the remedy is the half that gets acted on. Run the proposed fix against the defect
before applying it. A wrong remedy is worse than an open finding: it converts a true
diagnosis into a new defect, and it does so under the authority of the review that
produced it. When the remedy fails, find the one that works and report both halves —
the diagnosis you kept and the prescription you rejected, with what the test showed. A
`falsifiable_check` that asserts an exit code is the reviewer's claim, not its
evidence.

**When your own recomputation disagrees with the artifact's number, suspect the
recomputation.** A metric re-derived by hand almost always differs because an input was
omitted, not because the tool is wrong — and the wrong value is plausible enough to be
believed and reported. Call the tool's own entry point, or reproduce its number exactly,
before drawing any conclusion from the difference. Chasing a discrepancy you introduced
costs far more than the check that would have caught it.

### Self-assessment

**Verifying your own work is not validation.** If you built, wrote, or advised on
any of the artifact, say so in its own paragraph, and do not let a self-run test
carry a claim. n=1, self-graded, on a subject you know well is not evidence; report
it as unverified, or say plainly that it does not count.

**Do not dress a self-report as a result.** A report that you ran the thing and it
passed establishes that it ran, not that it is good. State the sample size and who
assessed it.

**A check that has only ever passed is untested.** Break the artifact and require the
check to fail before citing it. A control appended *after* the program's own
`raise SystemExit(main())` never executes, so the broken copy still exits 0 and the
control proves nothing; the failure has to come from the artifact, in the code path the
check actually reads. The same holds for a check that skips when its dependency is
missing — count what it examined, or it is a pass you cannot quote.

**An estimate you produced is a claim, not evidence.** A number you introduce to
justify a recommendation — a cost, a saving, a threshold — is as unverified as the
artifact's own numbers, and it is worse than an omission because it *decides* the
answer. When a recommendation rests on "this saves N" or "this costs N", measure it
before the recommendation ships; the measurement is usually cheaper than the change it
argues for. An estimate that survives only because nobody checked it is how a component
nobody needs gets justified — and it is the assessor's own number, so no other rule here
will catch it.

**When asked whether your own additions degraded the artifact, measure rather than
argue.** Four cheap measurements settle it, and the ones that count are the ones you
do not control:

- **Commits touching the sensitive path.** `git log --oneline <base>..HEAD -- <the file
  that produces the numbers>` returning nothing is the strongest cheap evidence that
  behaviour cannot have changed — stronger than any test you ran yourself.
- **A regression guard that PREDATES your work.** It is the only evidence here that is
  not self-run; cite it and say that is why it counts.
- **Requested against yours, as line counts.** This separates what was asked for from
  what you added on your own initiative, and it is the number that answers a
  scope-creep question. It is uncomfortable in both directions, which is the point.
- **The cost of anything you put on a hot path**, timed before and after. A guard on an
  entry point runs on every invocation, so its overhead is real even when it is correct
  — and a regression you introduced while fixing something else is still one you
  introduced.

**Name your incentives.** If you have spent effort on the artifact, or your prior
advice is what is under review, that biases you toward defending it. Say so.

### When the artifact is the user's own

**Lead with what is ahead, not only what is behind.** A one-sided critique is as
unhelpful as a one-sided endorsement. State where their approach beats the
reference before listing gaps, and verify the gap exists in their artifact before
recommending it.

**Check for a deliberate decision before calling it a defect.** Look for an ADR, a
design note, or a comment. A choice that is documented and reasoned is not a gap,
and "fixing" it to match a reference is a regression.

## Procedure

1. **Inventory the artifact.** Size, surface, moving parts — as numbers, not
   adjectives.
2. **Read the primary sources it rests on**: its code, tests, measurements, docs.
3. **For each load-bearing claim, classify it**: tested or assumed, measured or
   asserted.
4. **Search for the counter-evidence**, in the artifact and in the literature.
5. **Look for internal contradictions** between claim and implementation.
6. **Grade and list the sources**, each with its bias, marking the unverifiable.
7. **State your own conflict.**
8. **Write the verdict in the contract order above.**

## Pitfalls

- **Critiquing the documentation.** A defect found in a README may not exist in the
  code, and vice versa; cite the artifact you actually read.
- **Accepting the project's own research as independent.** Material the artifact's
  author wrote about the artifact is its justification, not corroboration — say so
  when you rely on it.
- **Reporting a vendor benchmark as a measurement.** It is an upper bound on
  credibility, and it should be marked as such.
- **Letting a self-run test stand as validation.** See Self-assessment.
- **Reciting the process instead of the verdict.** The reader wants the conclusion
  and the evidence; how you got there is a sentence, not a section.
- **Padding with adjectives where a number belongs.** If the artifact is measured,
  the number is the evidence.

## References

- `references/reference-implementation-comparison.md` — comparing the user's
  artifact against a named reference repo, and producing pseudo-diffs.
- `references/decisive-experiment.md` — designing and running the experiment that
  settles the verdict: pre-registering the decision rule, equal-cost arms, ground
  truth, blind labelling, counting distinct defects rather than matched findings, and
  repeating the run so a single pass cannot invert the result.
- `references/applying-review-findings.md` — acting on a review's output: verifying each
  claim against the running system, testing a prescribed remedy before applying it,
  assertion-checked edits, proving the change rather than asserting it, and reporting
  per finding.
