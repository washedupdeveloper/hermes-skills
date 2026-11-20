# Removal audit — leave nothing asserting what was deleted

For the task: "remove X from this library/tool" or "X is gone, make sure nothing still
mentions it". The artefact is the easy part. What outlives it is every place that *asserts* it,
and a removal is finished when a stranger can read the tree without learning that X existed.

Applies to both directions of a two-project setup: the library that dropped a vendored copy,
and the tool that named the library it consumes.

## 1. Classify before deleting

| what | where it hides |
|---|---|
| the artefact | the files, their support files, their tests |
| the checks about it | a claim ledger row, a suite that ran its code, an exemption naming a file inside it |
| the records | the ADR that justified it, the ADR that recorded its removal, archived change records |
| the vocabulary | schema fields and enum values carrying its name |
| the assertions elsewhere | `related_skills`, spec requirements, prose deferrals, cross-citations |

Deleting only the first three leaves the last two, which is the state that reads as finished and
is not.

## 2. Where an assertion survives, and how to find it

- **`related_skills` naming it.** The gate resolves those against the catalogue, but a contract
  that lists the name as an *external* skill validates it without any skill existing. Five skills
  carried the dead name with the gate reporting zero violations, so **a green gate is not evidence
  that names resolve** — grep the frontmatter directly.
- **A spec requirement binding you to it.** `The <other> skill SHALL be generated from
  <repo> and synced` is the strongest coupling a library can carry: a written obligation to a
  project it does not own. Rewrite the requirement to the rule it encodes — *a shipped skill's
  source of truth is in this repository; a copy generated elsewhere is not committed here* —
  which stays true with no project named.
- **Deferral prose.** "See the `<name>` skill — its operational commands live there, not here"
  outlives the skill by years. Replace the deferral with the principle, and the reader keeps the
  rule without the dead pointer.
- **Cross-citations in the surviving records.** "the drift ADR-0003 records" dangles the moment
  ADR-0003 goes. Read every record that mentions it, not only the two being deleted.
- **Archived change records.** A completed change that describes paths inside the removed tree is
  unverifiable history. Delete it with the thing (see §4).
- **Data and fixtures.** A recorded verdict, snapshot or log can bake `/home/<user>/…` into a
  committed file. Grep `fixtures/` and `*.json` for `/home/`, `/Users/`, `/mnt/` — a code-only
  grep misses every one of them.
- **Caches inflate the count.** `.hypothesis/constants`, `__pycache__`, `.ruff_cache` embed the
  checkout path in dozens of files; a name search reported 96 hits that were 90 cache lines and
  6 fixtures. Delete or exclude them before counting anything, and add `__pycache__/` to
  `.gitignore` if it is missing.

## 3. Judge each hit: assertion, illustration, or the ordinary noun

Delete or rewrite assertions. **Keep illustrations** — a real tool named in a worked example
teaches the rule and is not a claim about what the repo ships. **Keep the ordinary noun**: "present
the result as a council", "an advisory council" are English, not references to a project.

A quick test per line: does the sentence promise that this tree contains, generates, or depends
on the thing? If yes, it is an assertion.

## 4. Prefer deletion over tombstones, for an owner who wants only the present

A record of the removal is itself a reference to the removed thing. Delete the justifying record
and the removal record together, with their index rows; rewrite the records that cited them. Keep
a tombstone only where the repo treats decision records as immutable history — that is a repo
convention to confirm, not a default.

What must survive a deletion is the *rule the thing taught*, restated without the thing: a
requirement, a principle, a schema field under a neutral name.

## 5. Vocabulary moves last and completely

A data schema keeps the name after the code is gone (`owner: <project>`, `<project>_run`). Rename
to the neutral term and **remove the old key outright**: one spelling, judged as written. A read
alias plus a duplicated key is a stopgap for data already on disk — offer it once, label it
temporary, and retire it when the owner says nothing should be left behind. After the alias goes,
a record still carrying the retired value lints as wrong, and that is the honest report: the value
is wrong, not the rule.

## 6. Prove it

Report a per-name count before and after, and quote the gate at the commit, not in the working
tree:

```sh
for pat in '<old-name>' '<old-name-2>' '<old-adr>'; do
  printf '%-20s %s\n' "$pat" \
    "$(grep -rn "$pat" --include='*.md' --include='*.py' --include='*.nix' --include='*.sh' . \
       | grep -v '^./.git' | wc -l)"
done
git worktree add --detach /tmp/verify HEAD && cd /tmp/verify
python3 scripts/validate.py && python3 -m pytest tests/ -q && python3 scripts/claim-audit.py
```

Then run the repo's own remaining gates — a spec validator, a docs index test, a prose ledger —
because each one covers a class of assertion the others do not.

Two honest notes belong in the report: any edit that landed only in another writer's *untracked*
draft (corrected on disk, absent from the commit), and any deliberate survivor — an oracle fixture
recorded from the retired version, a provenance ledger the licences require — with the reason.

## 7. Testing that the tree is isolated

When the requirement is "no test may depend on anything outside this repository, unless it is
labelled end-to-end":

- Enumerate every module and classify by what it *invokes*, not what it names. `shutil.which(...)`,
  a `subprocess.run(["<binary>"...])` with something other than `sys.executable`, and a URL are
  hits; a docstring mentioning a tool is not.
- **Injected fakes are not dependencies.** A unit test passing `binary="hermes"` beside a fake
  `which` mapping, or creating a stub script under `tmp_path`, is testing a pure function. Read the
  call before calling it coupling.
- A test that spawns *its own* package's server or CLI is self-contained: integration with itself,
  not with another project.
- The only real external binary is usually `git`, used to build throwaway repositories in a temp
  dir — say so rather than implying a clean sweep.
- **Label the ones that reach out**, in the directory *and* in the module docstring: "Integration
  test: it drives the Nix evaluator, which no unit test can reach." A directory name is a label a
  reader has to infer; one sentence costs nothing and satisfies the rule explicitly.
