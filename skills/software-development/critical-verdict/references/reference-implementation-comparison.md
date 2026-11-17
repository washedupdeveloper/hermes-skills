# Comparing an implementation against a reference

Use when the user names a repo as a good example of its kind and asks how theirs
compares, what to adopt, and what the change would look like.

## Fetch the reference's real files

The rendered GitHub page gives you the file listing and the README, not the file
contents. Fetch raw:

```
https://raw.githubusercontent.com/<owner>/<repo>/<branch>/<path>
```

Batch several paths into one call — the flake, the module that wires the flake
outputs, the checks module, the CI workflow, and any file whose decisions you
intend to recommend copying. Read the user's side directly from their working
tree.

## Compare technique, not size

A production fleet repo and a single-machine homelab differ in scale by design.
Comparing line counts or directory counts is meaningless. Compare **what each does
about the same concern**, and state the scale difference up front so the reader
knows the comparison is about technique.

## Report the convergence, not only the gaps

When the reference was built independently and is much larger, say where both arrived at
the same rule without seeing each other. That is the strongest evidence in the comparison
that a rule is necessary rather than stylistic — two teams paying the same cost found the
same shape — and it tells the reader which of their own inventions to keep rather than
replace. Measured: a product and a single-purpose gate independently produced an evidence
ledger whose states gate completion, the same "unrun is not a pass" rule, and the same
split between a pure decision and an effect shell. A comparison that lists only gaps hides
the part of the user's work that is already right.

## Quantify the reference's own claims, especially the test count

Test count is the most misleading number in a large repository: it tracks history, not
coverage. Measure the *shape* of the suite before crediting it — the fraction of test
files that construct the product, that import the application object, that assert on
source text rather than behaviour, and whether a coverage configuration exists at all. A
12,000-test suite with no coverage gate and six files that build the app is a
unit-and-characterization suite, and saying so changes the verdict.

The same rule applies to the rest of its self-description — endpoints, CI gates, supported
platforms, contributor count. Count them yourself; a README's numbers are a claim, and a
star count is not evidence of quality.

## Verify the gap exists before recommending the fix

This is the step that fails. Before writing "add X", confirm X is absent from the
user's artifact — and that the reference is genuinely ahead on it.

Run the user's own tooling rather than reading:

```bash
nix eval --json '.#checks.<system>' --apply builtins.attrNames   # what checks exist
nix flake check --keep-going --no-build                          # what evaluates
nix path-info '.#<attr>'                                         # what is already built
```

A recommendation to "add CI" is wrong when the repo already has `.#checks` and
merely lacks a runner. The real gap is narrower and only visible after checking.

## Check for deliberate divergence first

Before calling any difference a defect, look for the reasoning behind it: an
`docs/adr/`, a design note, or a comment at the decision site. A pin direction, a
module boundary, or an input `follows` that is documented as intentional is not a
gap, and "fixing" it to match the reference is a regression. Call it out
separately as a deliberate difference you are *not* recommending against.

A documented decision is also *evidence of cost*: when the reference costs 100× more
code, every gap you find there is a gap it can afford and the user's artifact cannot.
Rank adoptions by what they buy at the user's scale, not by what the reference spends.

## Its failures are requirements, not only warnings

The reference is evidence in both directions. Its defects are the strongest argument for
the user's mechanism, and they are testable: run the user's instrument against the
reference, and treat each defect it *proves* there as a requirement for the user's tool,
with the check that found it as the acceptance test. That is how a comparison becomes a
roadmap with evidence attached instead of a feature list.

Two rules keep it honest. Name the class before proposing a change — "a proof that quotes
a line cannot settle behaviour", "a per-file reviewer cannot see an invariant in the next
file" — because one defect is an anecdote and a class is a design argument. And separate
what the reference does *deliberately* from what it does *badly*: a documented trade-off is
not a defect to design against, and the user's tool losing to it would be a regression.

What this produces is a precision number rather than an impression: on a 3,000-file
reference, nine review runs gave 169 findings, of which six were real defects, about eight
were true but minor or documented, and three were false at the system level. That ratio is
what tells the user whether the mechanism is worth adopting at their scale; a list of 169
items tells them nothing and reads as thorough.

## Output shape

1. **Verdict** — where the user's artifact stands relative to the reference, in
   one paragraph, including where theirs is ahead.
2. **Where the user is ahead** — a table. This is not flattery; it stops the
   reader from adopting a reference pattern that would be a downgrade.
3. **The gaps, ranked** — each with what the reference does, why it matters, and
   what it would cost.
4. **Pseudo-diffs** — real diff blocks against real paths, `---`/`+++`/`@@` style,
   with the new file's full content when the fix is a new file.
5. **What NOT to copy** — the reference's scale-specific machinery (cloud
   provisioning, multi-user administration, org dashboards) and its own deficits
   (a missing ADR set, no local hooks). Never present the reference as uniformly
   better.
6. **Priority order**, cheapest-and-highest-value first.

## Pitfalls

- **Treating the reference as uniformly better.** It usually has its own gaps, and
  the user's repo usually does something it does not.
- **Recommending a pattern you did not verify is absent.** See above.
- **Recommending a change that contradicts a documented decision.** Check the ADRs.
- **Copying scale-specific machinery into a smaller artifact.** Terraform, multi-user
  administration, and org CI belong to the scale that needed them.
- **Pseudo-diffing a file you never read.** Read the target file first, or the diff
  will not apply and the paths will be wrong.
- **Crediting the reference's maturity to one feature.** A product's security posture is
  the sum of a hundred small decisions; adopting three of them and calling it "their
  approach" produces a checklist that reads as done while the property is not.
