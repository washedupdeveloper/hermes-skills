# Concurrency and retry probes

Use these after the state map identifies a candidate. Each probe should fail
before the fix and pass after it; keep the smallest one as a regression.

## Two-process claim race

This proves whether two runs can share one output directory. Use a real repo and
a deliberately slow stub so both processes reach the guard.

```sh
# terminal A/B, or two background jobs with a wait
council review -C "$repo" --base HEAD --samples 1 \
  --reviewer "$slow_stub" --no-sandbox --no-stream \
  --no-ephemeral --run-id race
```

Expected after an exclusive claim: one process exits 0, the other exits 3 with
`already exists`; the run directory contains exactly one `sample-1.json` and one
`verdict.json`. Before the fix both can pass the existence check and interleave
writes.

At the unit seam, assert the claim itself:

```python
_claim(root / "run", "run")
with pytest.raises(ReviewError, match="already exists"):
    _claim(root / "run", "run")
```

## Retry that succeeds on the second attempt

Use a counter file, not a mock sequence, so the real process and attempt counter
are exercised.

```sh
#!/bin/sh
n=$(cat "$STATE/count" 2>/dev/null || echo 0)
n=$((n + 1)); echo "$n" > "$STATE/count"
if [ "$n" -eq 1 ]; then echo "first attempt failed" >&2; exit 1; fi
printf '%s\n' '{"sections":{"security":[],"performance":[],"readability":[],"correctness":[],"architecture":[]}}'
```

Assert: exit 0, `sample-1.json.attempts == 2`, `error is null`, and `failures[0]`
contains the first failure. A missing binary is different: `ReviewerMissing` must
exit 3 without a retry.

## Keep/export collision

Pre-create the destination run directory, run with `--keep` and a fake review,
then assert the source evidence still exists, the destination has no new
`verdict.json`, and the message names both paths. A merge is a bug.

## Invalid UTF-8 from the child

Write one invalid byte to stdout from a stub. The transport must replace it (or
mark the sample failed), never raise `UnicodeDecodeError` through the CLI. Test
both the plain run and the streaming run.

## Empty final event

Emit `{"type":"text","text":"ok"}` followed by
`{"type":"result","text":"","exit_code":0}`. The answer must be `ok`; an empty
result must fall back to accumulated text events.

## FIFO read

```python
os.mkfifo(root / "pipe")
outcome = run_proof("present", {"path": "pipe", "line": 1, "text": "x"}, ctx)
assert outcome.state is State.UNRUNNABLE
```

The check must happen before `read_text`; a test that opens the FIFO will hang.

## JSON Pointer index grammar

With `{"a": [1, 2]}`, both `/a/-1` and `/a/01` must be `UNRUNNABLE`; `/a/1` may
resolve. The common implementation bug is `int(part)`, which accepts both.

## Cleanup after a start failure

A missing reviewer or malformed prompt must leave no run directory when no
evidence was written; a failure after a sample must keep the sample. Assert the
directory contents, not only the exit code.
