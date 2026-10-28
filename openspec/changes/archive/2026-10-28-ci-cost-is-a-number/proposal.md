# Proposal

## Why

`gate-integrity` already requires that the gate's cost be measured. What a *run* costs was not
measured at all: the only way to learn which job took the time was to diff `started_at` against
`completed_at` by hand.

That was the whole investigation when two macOS jobs disappeared from a run. The check-run listing
showed `cancelled` and nothing else; the reason (15m01s, no steps executed) came from reading two
timestamps off an API response and subtracting them. A number in the summary would have been the
answer.

## What Changes

- `scripts/ci-cost.py`: the run's job list in, a markdown table out — seconds per job, longest
  first, a running job marked as such, and the run's span stated as **not** the sum of the column.
- A `cost` job that renders it into `$GITHUB_STEP_SUMMARY`, with `if: always()` so it runs when
  everything else failed, and `actions: read` as the only extra permission.
- Six unit tests, because a report whose arithmetic is wrong is worse than none.

## Capabilities

### Modified Capabilities

- `gate-integrity`: adds "A run's cost is a number, not an inference".

## Impact

`scripts/ci-cost.py`, `tests/unit/test_ci_cost.py`, `.github/workflows/ci.yml` (an eighth job). The
job is a report: it fails only if the report cannot be produced, which is worth knowing too.
