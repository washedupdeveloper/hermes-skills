# Reproducing a check that failed once

A gate that fails once and passes on the retry is the worst failure shape: the run failed,
so nothing was proven, and the retry makes it look like a ghost. The failure is the only
information you have. Spend it before moving on.

## The log is already gone

Nix truncates a failed build's log to "last N log lines" in the error message. If the check
was built through an app or wrapper that did not pass `--print-build-logs`, those lines are
all that ever reached the runner — typically a summary (`262/263 items hold`) with the
failing item one line above the window. The derivation lived on an ephemeral runner.
Re-running the same commit does not help: that commit still lacks the flag.

So fix the loudness in the same change that investigates. Pass `--print-build-logs` **inside
the app**, not at the call site, or the next flake is undiagnosable by construction.

## Rebuild the exact artifact

The derivation path in the CI error is a content address. The same commit and the same flake
inputs evaluate to the same path:

```bash
git worktree add --detach /tmp/wt <sha>
nix eval --raw "/tmp/wt#checks.<system>.<name>.drvPath"
```

Compare against the `/nix/store/...` path named in the CI error. A match means you can re-run
exactly what failed:

```bash
nix build --rebuild --no-link --print-build-logs .#checks.<system>.<name>
```

`--rebuild` re-runs the builder even though the output is already in the store. Repeat it: a
one-in-four failure reproduces within a few runs, and this time with the whole log.

A worktree at the failing sha also answers the other question — whether the local tree is
still the tree that failed — without disturbing the checkout you are working in.

## Separate "flaky item" from "shared state"

Run the failing item alone first. Ten or fifteen clean solo runs means the defect is not in
the item: it needs a neighbour. Then vary exactly one thing at a time, and write the result
down as a ratio, not an adjective.

| Condition | Reading |
|---|---|
| solo, N runs | reproduces → the item is genuinely flaky or environment-dependent |
| concurrent, shared temp root | reproduces → cross-process interference |
| concurrent, private temp roots | clean → confirms the temp root is the interference |

Give each concurrent process its own `TMPDIR`/`TMP`/`TEMP` and re-run the shared case as the
control. "One failure in six rounds shared, none in ten private" is a finding. "It was
probably the cache" is not — and a wrong mechanism, once written into a commit message or a
skill, outlives the fix and misleads the next investigation.

## Sweep the class, not the instance

A pooled runner that launches one subprocess per item has N chances per run to hit the same
bug. After finding it in one place, grep for every other place that spawns the same kind of
subprocess and apply the isolation there too — the fix for the flaky cheap check is usually
the fix for the expensive campaign nobody has caught failing yet.
