# Whole-codebase untangle execution

Use this when the user asks to untangle the whole codebase to completion, not only to
propose an architecture RFC. The categories are from `caldoai/skills`'
`untangle-codebase`; the execution rules below are the adaptation for this repository.

## 1. Ask before touching code

List these additions with their exact descriptions and ask which to include:

- **Comments** — Remove comments that only restate the code.
- **Tests** — Remove tests that would not catch a real bug, and fix the ones that fail
  without one.

Do only what the user selects. If neither is selected, run the code untangle alone.

## 2. Inventory before editing

Read the whole source tree, not just the hot files. Start from history and the dependency
graph:

```bash
# which files change together
git log --format= --name-only | sort | uniq -c | sort -nr | head -30

# source/test sizes
git ls-files 'src/**/*.py' 'tests/*.py' | xargs wc -l | sort -n

# who imports whom
grep -RInE '^(from|import) ' src | head -300
```

Write one decision log with every real problem in these categories:

- **Hidden links:** copied values or logic, shared globals/files, a feature split by layer,
  call-order or naming conventions callers must know.
- **Needless links:** callers reaching into internals, stable code importing volatile code,
  caller-specific parameters on a general function, shallow pass-through modules.
- **Surplus:** wrappers that only forward, speculative configuration, dead code.
- **Special cases:** one-value `if`s, a parameter for one caller, swallowed exceptions,
  retries/sleeps, disabled tests.

For every entry: `file:line`, category, why the pieces must or must not change together, and
the smallest structural fix. Do not edit source in this phase.

## 3. Redesign from first principles

Group multiple symptoms under one structural fix. Prefer moving a decision behind one
interface over fixing each symptom at its call site. Apply the deletion test from
`codebase-design`; do not add an adapter for a seam with one implementation.

Write the chosen fix above the problems it removes, then a migration order where every step
leaves the program working and the full gate runnable.

## 4. Implement in small, green commits

- Move the decision first, then update callers; keep public re-exports while tests and
  downstream imports still name the old module.
- Stage new files before `nix flake check`; Nix's flake source only sees tracked files.
- When a helper moves, update mutation anchors and tests that monkeypatch the old private
  name in the same commit. A moved anchor becomes `STALE` and the mutation gate fails even
  when pytest is green.
- Keep LF-only and a final newline on every text file.

## 5. Comments and tests last

If selected:

- Remove a comment that only restates an implementation fact. Keep a comment that records
  an external constraint, a measured provider limit, a security boundary, or a workaround
  whose underlying problem still exists.
- Remove a test only when it cannot fail on a real regression. A test tied to a private
  import should be rewritten against the public interface first; it may still be valuable.
- Do not delete a test merely because it uses `pytest.raises` or a helper assertion. The
  “no assert” shape is often a false audit positive.

## 6. Check until nothing worth fixing remains

Run the focused checks first, then the full gate:

```bash
./scripts/verify.sh
```

Have independent subagents sweep the final tree for the four categories after the edits.
Stop when the remaining items are accepted residual debt with a named reason, not when the
first patch lands.

## Pitfalls

- A god module is not fixed by moving its private helpers into several files that still
  share the same request object. Separate the decisions from the effects and reduce the
  interface.
- Do not preserve a private helper as a pass-through facade just because a test imports it.
  Rewrite the test at the public boundary.
- Do not call a slice of the inventory “complete” after one module. The user asked for the
  whole codebase; keep the decision log live until every category is swept.
- Do not make behaviour changes in the same commit as a structural move. Note a bug, fix it
  separately, and keep the gate green at each step.