# Closing a feature milestone

Use when the ask is to find what is missing from a milestone, finish a feature, or
prove a feature to completion in a council checkout.

## 1. Audit before editing

- Read the newest decision record under `docs/M*.md`; run every row of its
  **Acceptance** table literally. Keep "the old milestone rows pass" separate from
  "the new feature is bound": a green old milestone does not close a new feature.
- Read `docs/README.md` (decision-record table and index), `CHANGELOG.md`
  (Unreleased), `claims.toml`, and `git status`. Compare six things: implementation,
  regression tests, claim, mutation, decision record, changelog. A missing claim or
  mutation is a real gap even when the feature's tests pass.
- For a feature borrowed from an adjacent tool, name which contract it strengthens
  (review a change, settle a finding with evidence, reproducibility/audit, or cheaper
  gate without dishonesty). Record adopted, deferred and rejected candidates in
  `docs/FEATURES.md`. Reject features that turn the reviewer into an author, chat
  product, workspace, plugin runtime, or automatic merger. A deferred feature needs
  its contract designed before code: provider checkout verification, durable review
  state, a multi-profile merge rule, or a separate write authorization.

## 2. Bind the behaviour

1. **Drive the CLI boundary.** If the feature crosses parser -> function -> external
   call, add a test through `cli.main` that asserts the value or effect reached the
   call. A test of the callee alone lets the parser accept the option and the call
   site discard it; that is the failure `verify-and-stop` calls "parser and signature
   but not the call between them".
2. **One claim per independent behaviour.** Name exactly one pytest node in each
   `[[claim]].check`; the mutation mapper reads only the first node. Split a
   multi-node check into separate claims, one node each.
3. **One mutation per declared falsifier.** Use the exact whole statement or call
   site, not a fragment; a fragment can leave a syntax error that trips every test
   while mapping to no claim. Run the complete `tools/mutation_check.py`: every new
   mutation must print `caught` and `falsifies <claim>`, the run must say `N/N`, and
   no `PROBLEM` line may remain. A caught mutation reporting `falsifies no claim`
   means its failing test is not the node its claim cites - split or retarget the
   claim, do not delete the mutation.
4. **Write the decision record.** Add `docs/M<n>.md` with the decision, rejected
   alternatives, known limit, and an acceptance table of exact commands. Link it in
   the `docs/README.md` decision-record table; an unindexed document fails
   `test_docs_index`. Add the feature under `CHANGELOG.md` Unreleased.
5. **Regenerate derived truth.** Run `./bin/council-verify --write docs/CLAIMS.md`; run
   `./bin/council-verify --check docs/CLAIMS.md` afterwards. Update measured counts (claims, falsifiers, mutations, test
   files) in `docs/FOUNDATIONS.md` and any current comparison page from a fresh
   count - never increment prose from memory. A stale count is a claim no gate
   reads.

## 3. Proof commands

From the checkout, inside `nix develop -c`:

```text
python -m pytest -q -p no:cacheprovider
./bin/council-verify
python tools/mutation_check.py
mypy src
pyright
ruff check --select F,E9 src tests tools
python -m pytest tests/test_docs.py tests/test_docs_index.py \
  tests/test_doc_citations.py tests/test_release.py tests/test_skill.py \
  tests/test_files.py -q -p no:cacheprovider
```

Run the Markdown link checker if the repository ships one. Stage new files before
`nix flake check --keep-going`: the flake builds from the git tree, so an untracked
test or document is invisible. `nix flake check --no-build` only evaluates; quote it
as evaluation, not as the built gate.

Read the exit code and the summary line, not a piped tail alone. For a long mutation
run, launch it in the background and record its exit status; a display-only timeout
is not a result.

## 4. Close

- New Markdown files end with exactly one newline; `tests/test_files.py` enforces it.
- `git diff --cached --check` before committing; stage the decision record, generated
  claims page, tests, claims, mutations and changelog together.
- Commit on the session branch only. Never commit to `main` and never push the
  remote; report the commit SHA, the branch, and how many commits it is ahead.
- Re-run the focused acceptance rows after the final edit. A proof from before the
  last edit is proof of a tree that no longer exists.