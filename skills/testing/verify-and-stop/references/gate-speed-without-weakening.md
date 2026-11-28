# Making a verification gate faster without making it weaker

A gate that runs the same expensive check once per case scales with `cases × check`. Every
honest way to cut it changes *when* work happens, never *what counts as proof*. This is the
decision table for that, and the failure modes that make a fast gate a lying one.

## The one rule

**A subset may prove a catch. Only the whole check may prove a miss.**

A failure observed in a subset is a real failure — nothing was inferred. A pass observed in a
subset is evidence about the subset and nothing else, so it must never be reported as the
case surviving. Every rejected design below fails this rule; every accepted one keeps it.

## Declared subset vs guessed subset

| subset | sound? | why |
| --- | --- | --- |
| the cases that **declare** this subject (a claim's own falsifier test, a rule's own example) | yes | the subset is part of the specification, not a prediction about it |
| tests that import the mutated module | no | indirect users catch things the import graph never names; measured 6% direct importers against tests that do catch |
| coverage of a previous run | no | a new case can be caught by a line that did not run before |
| "the fast tests" | no | speed is not a dependency relation |

Before proposing a declared subset, measure its size and its hit rate on **all** cases:
`1.11 nodes per case` and `72/72 fired` is a design; "should be small" is a hope. If the
hit rate is low the fallback dominates and the change buys nothing — measure first, then
decide whether the idea survives.

## Fallback is unconditional on a pass

```
run the declared subset
  if it fails -> caught, attribute to the subset's own rule
  else         -> run the whole check and decide from that
```

The `else` is not an optimisation detail; it is the correctness argument. Removing it turns
the gate into a sampler.

## Fail-fast belongs inside the subset, and only there

Stopping at the first failure over a multi-node subset records **one** broken rule, so a
subject named by three rules reports two of them as "its own falsifier did not break it". Run
every node in the subset; let the attribution come from all of them. Over the *whole* check,
fail-fast is worse still: the first failure can be a test no rule cites, so the campaign
reports a catch with nothing behind it.

## Cache the verdict, key it to the experiment

A recorded verdict may be reused only when **every input that can change it** is identical:

- the whole source tree, not just the file the case touches — the check runs against all of it;
- the whole test tree, the registry of rules, the runner's own source;
- the interpreter version, when a verdict can depend on it.

Keying on the mutated file alone is unsound for exactly the reason the subset rule exists: a
change elsewhere changes what the check would have said. Load with a tolerant parse (a
corrupt cache is an empty cache), validate each entry before use, and never let a failed
write fail the run — a read-only source tree is a normal environment, not an error.

## What a cache cannot do

It cannot help a **new** commit. New input means new work, and a build system that already
caches per input hash (Nix, Bazel) has nothing left to save. Measured: a cold store with a
local binary cache took 328s against 310s without, because the check outputs had never been
built on the host. Say this plainly rather than shipping a cache and claiming a speedup.

Related trap: building with an explicit alternate store (`nix flake check --store
local?root=X`) realises outputs **inside that store**, so the host store never holds them and
a cache serving the host has nothing to serve. Populate the host first if you want to
measure substitution at all.

## Make the shape visible, or a regression is silent

Print how the cases were decided — `N decided by the declared falsifier, M by the full
check` — and pin it with a test and a claim. Without that line, a registry change that
breaks every declared subset degrades the gate back to full cost and looks exactly like
success.

## Sizing the win before you build it

Measure the three numbers that decide whether the design is worth its complexity:

1. cases × subset cost ÷ workers  (the new steady state)
2. cases × full cost ÷ workers    (today)
3. the baseline run that survives either way

When (1) collapses, (3) becomes the largest item — a suite run once to prove the tree is
green. That is the next target, not a rounding error: measure it before celebrating.
