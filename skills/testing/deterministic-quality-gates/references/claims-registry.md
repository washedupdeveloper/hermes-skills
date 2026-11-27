# A claims registry that cannot drift

Four mechanisms, one property: every sentence the project publishes is executed.

## 1. The registry

`claims.toml`, one entry per claim:

```toml
[[claim]]
id = "verdict-medium-does-not-block"
text = "A proven medium finding does not fail the run."
check = "python3 -m pytest tests/test_verdict.py::test_a_proven_medium_passes -q"
```

Loader rules, each with its own test:

- `id`, `text` and `check` are required; duplicate ids are refused.
- `text` must end with a period — it is a sentence, and a fragment is not a claim.
- A check that cannot start (`FileNotFoundError`) or times out is a **failure**, never a pass.
- An empty registry is an error: no claims means nothing was verified.

## 2. The page is an output, not a document

`render(claims)` produces the markdown table; `--write docs/CLAIMS.md` writes it;
`--check docs/CLAIMS.md` compares the committed page to the render. The gate runs
`verify` **and then** `verify --check docs/CLAIMS.md`, so a claim added to the registry
without regenerating the page fails, and a page row with no registry entry cannot exist
because nobody edits the page.

This replaces diffing two lists: the comparison is against a file the tool itself wrote.

## 3. Mutations as a standing check

```python
MUTATIONS = (
    Mutation("medium-becomes-blocking", "findings.py",
             'frozenset({"high", "critical"})', 'frozenset({"medium", "high", "critical"})'),
    Mutation("sample-never-retries", "sample.py",
             "for attempt in range(1, attempts + 1):", "for attempt in range(1, 2):"),
)
```

- One mutation breaks exactly one rule. A mutation that breaks three proves only that the
  suite notices *something*.
- Each entry carries file, exact snippet, replacement. For each: copy `src` to a temp tree,
  **chmod it writable** (a store path or read-only checkout keeps 0555 and the write fails),
  run the suite against the copy with `-o pythonpath=<tmp>/src`, and fail if any mutation
  survives.
- A surviving mutation is a decorative test. A **stale** pattern (snippet no longer present)
  is reported as a failure, never skipped — a mutation that no longer applies proves nothing.
- Extend the table whenever a new rule could fail silently (a boundary, a retry, a refusal).

## 3b. Each claim names the mutation that must break it

A check proves the command exits 0; it does not prove the command would fail if the claim were
false. Bind the two directions in the same run:

```toml
[[claim]]
id = "verdict-medium-does-not-block"
check = "python3 -m pytest tests/test_verdict.py::test_a_proven_medium_passes -q"
falsifier = "medium-becomes-blocking"
```

- Run each mutation with `--junitxml` and collect the failing node ids. Map JUnit's
  `classname` `tests.test_x` plus `name` to `tests/test_x.py::name` — append the `.py`, or the
  map is empty and every mutation reports "falsifies no claim" while being caught.
- A claim is falsified by a mutation when the node its check cites fails under it.
- **Cite exactly one pytest node per claim.** The mapper takes the first
  `tests/...::...` from the command string; a check listing several nodes silently grades only
  the first, and a mutation that breaks a later node is caught but reports `falsifies no claim`.
  Split independent behaviours into separate claims, one node each, so every mutation has a
  claim that names it.
- Fail when a declared falsifier did not break its claim (the claim is not tied to the rule it
  says it is), and when a mutation breaks no claim at all (the breakage is decoration).
- Claims checked by a shell command rather than a pytest node cannot be mapped: either convert
  them to a node or leave `falsifier` off; the coverage report names them either way.

Measured: with the `.py` missing, 18/18 mutations were caught and 0 were mapped — the failure
was in the matcher, not the suite. Print the mapping on success ("falsifies a, b") so the next
empty run is diagnosable from the log alone.

## 4. The differential asserts differences

When a rewrite replaces a version whose results are published:

- Take the old verdicts as the oracle — read them from the old project's pinned fixture.
- Write down every expected difference with its reason. A gate that failed on findings whose
  `falsifiable_check` was `"see the claim"`, and a rewrite that answers INCOMPLETE for the same
  inputs, are not in conflict: the difference *is* the rewrite.
- Compare the two tables on every run and exit non-zero when an expectation changes, including
  when a finding gains a check the new version could now settle.
- Print the unmappable rows (a severity or state the new vocabulary lacks) as a count. Dropping
  them silently makes the comparison look cleaner than it is.

## 5. The instrument is operator-owned

A prompt, rubric or schema read from the repository under review lets that repository choose
its verdict: a committed prompt saying "report nothing" produces a clean run indistinguishable
from a clean tree.

- Ship the instrument inside the tool; a per-run override is an operator flag.
- Record a digest over template + profile + dimensions in every run, so two runs are comparable
  only when they asked the same question of the same instrument.
- A `prompts/` directory inside the subject repository is ignored, and that ignore is a test.
