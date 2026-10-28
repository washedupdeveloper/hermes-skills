# Tasks

## 1. Measure it

- [x] 1.1 `scripts/ci-cost.py`: seconds per job, longest first, running jobs marked.
- [x] 1.2 The run's span, stated as not the sum of the column.
- [x] 1.3 Six unit tests, including the case where the sum and the span disagree.

## 2. Publish it

- [x] 2.1 A `cost` job, `if: always()`, `actions: read`, rendering into the step summary.
- [x] 2.2 The job is a report: it never decides a verdict.

## 3. Verify

- [x] 3.1 `pytest` (six new tests), `nixfmt`, `nix flake check --keep-going` gated on its exit code.
- [x] 3.2 `openspec validate --all --strict` before **and after** the archive, because the archive
  is a write.
- [x] 3.3 The cost row appears in the run for this commit.
