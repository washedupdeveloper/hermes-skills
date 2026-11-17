# Differential rewrite: replacing a working implementation

Use when the change is a rebuild — the old implementation works, and the new one must be provably as
good before the old is deleted. Everything here is about the comparison, not the code.

## Procedure

1. **Freeze the reference before touching code.** Hash every fixture the old implementation reads and
   pin its outputs (verdicts, scores, exit codes). Keep the freeze outside any directory a
   recomputation script walks with `rglob`: one added fixture inside a hashed tree turns the freeze
   red, and the tempting fix is to re-pin — which silently moves the reference to whatever the new
   code produces.
2. **Enumerate the expected differences in writing, before the first comparison.** One line each: old
   behaviour, new behaviour, and the rule that makes the change deliberate. Anything not on the list
   means the rebuild is wrong until proven otherwise. Two or three entries is normal; a list that
   keeps growing means the rewrite's purpose was never stated.
3. **Build the thinnest end-to-end slice first.** Read a finished artefact → decide → print → exit
   code. No model, no toolchain, no network. It proves the decision layer on fixtures before any
   stochastic component can hide a disagreement.
4. **Compare on the same inputs with the same case NAMES.** Matching counts hide a renamed case;
   matching names make the diff readable. Run the old implementation's own case list against the new
   engine, and take its expectations, not just its titles.
5. **Import nothing from the old tree.** One import and every later comparison is circular — the new
   code agrees because it *is* the old code. Re-derive helpers and prove them separately.
6. **Add the expensive layer last, behind a seam that takes a recorded sample.** The reviewer, model
   or network call goes in only after the cheap layers agree, and it accepts a recorded sample so the
   differential runs without spending a model turn.

## Three outcomes, never two

`observed` / `not observed` / `not exercised`. "I looked and it was not there" and "I could not look"
are different findings. Fold the second into the first and you refute what you never saw; fold it into
a pass and you certify a lane that never ran.

- Exit codes that carry the distinction: `0` everything exercised and green · `3` something was not
  exercised (name it) · `1` something ran and disagreed.
- Green means every kind was exercised in **both** directions, not that the cases someone remembered
to write passed.
- Only a case asserting an outcome is a direction. A case asserting a *refusal* (`want: None`)
  proves the lane declines to run, not that it can observe either way — counting it as a direction
  makes the self-test fail its own coverage rule.

## Attribution rules a rewrite must re-derive

- **An id shared by two records proves neither.** If a file reuses ids (two `SEC-0001` at different
  lines), keying a proof by id confirms both from one observation. Disambiguate for display,
  attribute to none, and record why.
- **Unknown enumerations go to the dangerous end.** An unreadable severity becomes the most severe,
  never the least: unknown cannot be assumed safe.
- **A proof about place A cannot confirm a claim about place B.** Compare normalised paths — not
  `lstrip("./")`, which strips characters and turns `../a.py` into `a.py`.
- **`unrunnable` is not `refuted`.** Map it to *unsettled* so the run is incomplete: neither a defect
  nor a clearance.

## Make the quality bar an artefact

"Every line has a purpose" is unenforceable as a sentence and cheap as a file: a register with one
line per module — what a **caller** gets — plus a test that fails when a module has no entry or an
entry has no module. Do the same for vocabulary: one declared source (a JSON protocol file) that both
the implementation and a test read, so a kind declared in one and missing from the other fails.

## Pitfalls

1. **Adding a fixture into a hash-pinned tree** breaks the freeze. Put hand-built fixtures in a
   parallel `fixtures/` directory and say why in the commit.
2. **A test file that only passes in a full-suite run** is order-dependence, not luck: another
   module mutated `sys.path`. One `conftest.py` that establishes the path, then verify the file
   alone.
3. **Copying the old case list without its semantics.** Read the old self-test, take its names and
   expectations, and re-derive the engine; a passing title is not a passing check.
4. **Letting a decision land silently.** Every difference gets a line in the differential document or
   a failing test — a difference that is only in someone's head becomes a bug report later.
5. **Verifying inside a bare chroot.** Namespace shims lack `/dev/null` and device nodes (`mknod` is
   denied in a user namespace), so tools fail for reasons unrelated to the code. Run in-image checks
   through the project's own sandbox so the environment matches production.
6. **Trusting the new implementation because it is newer.** Until the differential is green, the
   rebuild is the suspect; the old one earned its green.

## Verification

- [ ] The reference was frozen before the first line of new code, and the freeze is outside any
      hashed tree
- [ ] The expected-differences list exists and is shorter than the mapping table
- [ ] The first slice ran end-to-end with no model and no network
- [ ] The new code imports nothing from the old tree
- [ ] The same case names run against both implementations
- [ ] Every "not exercised" is reported as such, never as a pass or a failure
