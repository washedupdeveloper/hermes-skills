# Benchmarking a skill

The library audit measures text. This measures behaviour: does an agent given the
skill produce a better artifact than one without it? Build it only when a claim
about performance has to be defended; a routing score is not that claim.

## Shape

One task, two arms, N repeats.

- **Treatment**: the skill's text sits in the workspace (`GUIDE.md`, with its
  `references/` at the paths the pointers use). **Control**: identical workspace
  without it. Same model, same prompt, same tools.
- **Isolate the arms.** One directory per arm, a fresh copy of the fixture in each,
  and an explicit instruction to stay inside it and not read the skills tree. Ask
  each agent for the commands it ran; that list is how you check for contamination.
- **The task must be mechanically checkable** and must contain a trap.

## Pre-register three outcomes before any agent runs

A benchmark is only readable if the scorer was proven in both directions first.

1. **Pristine fails, and only for the planted reason.** Print the full reason list:
   any other entry is a false positive in the scorer, and it will mislabel the arms.
2. **A gold solution passes.** A scorer that only ever fails measures nothing.
3. **The tempting naive fix fails on content, not on exit.** This is the whole design:
   a trap that crashes teaches nothing, because every agent notices a crash. The wrong
   answer must *evaluate cleanly* and silently lose something the check reads.
   - Force the whole nested option instead of the leaf (`service = mkForce { … }`): the
     error disappears and upstream's `name`/`icon` fall back to defaults.
   - Rewrite the tree instead of history: the file is clean and the old object survives.
   - Rewrite history but leave the tag: the log greps clean and `v1` still points at the
     poisoned commit.
   - Delete the guard instead of disarming it: the verdict it writes is byte-perfect, and
     the only thing that catches it is a hash of the files the task marked read-only.

Add a **robustness pass** to the scorer as well: re-run the solution against a variant
fixture whose upstream values differ. A solution that restates the expected values to
satisfy the first check fails the second.

## Score artifacts, never reports

Point the scorer at the directory after the agent stops. Ignore its narrative: agents
add their own probes and scaffolding, and a confident summary is not the output. Read
`git diff` / the file tree, then run the check.

Keep a **factory copy** of the fixture. It is the pristine arm for pre-registration and the
source of the hashes that prove an arm did not edit its way past a constraint; without it, a
wrong unblock that produces the right output scores as a pass.

## A ceiling is a result

A strong model often solves a mechanical task from priors alone, both arms pass, and
the honest finding is **no measurable difference** — not "the skill failed" and not
"the benchmark was broken". Report it with the effort numbers (calls, seconds) and the
fact that the controls derived the skill's own lesson unprompted.

Do not re-cut the task until it separates the arms; that is fitting the benchmark to
the answer. The alternative is a task whose success depends on a fact the model cannot
derive — a repo-specific path, a verb hidden behind an audience flag, an environment
trap. Those discriminate because the control has to *find* the fact, not because the
task is harder.

**Prove the guide states that fact before building the fixture.** Grep the guide for the
exact token the task hinges on. A trap drawn from your own notes rather than from the
shipped text yields two identical arms: the run completes, every arm scores the same, and
the result reads as a ceiling instead of the design error it is. And when the fact *is*
there, say what the test has become — a recall check. The treatment wins because it was
handed the answer, which proves the document exists, not that it is good.

State the limits with the result: n per arm, one task per domain, whether the guide was
read, and that the arms share a model. Two runs per arm cannot see variance — a skill
may reduce the tail without moving the mean, and that needs more repeats, not a
stronger claim.

## Fixture pitfalls

- **Never put a secret-shaped token in a fixture.** A redaction layer rewrites it in
  file content while leaving the task text and the scorer untouched, so the fixture and
  the instruction disagree and the task becomes impossible to complete. Use a neutral
  token (`BENCHTOKEN…`) and prove consistency by hashing the value extracted from
  fixture, task and scorer — print the hashes, not the value.
- **Pin newlines.** `write_text()` translates `\n` to the platform separator, so a
  fixture written on Windows commits CRLF and every expected blob hash is wrong. Pass
  `newline="\n"`.
- **Compute object hashes yourself.** Piping content through `git hash-object` in text
  mode re-encodes newlines and yields a hash that matches nothing. The blob id is
  `sha1("blob <len>\0" + bytes)`.
- **Do not build history with `filter-branch` under MSYS.** It aborts on working-tree
  checks and its `GIT_DIR` path conversion fails. Rewrite deterministically:
  `read-tree <commit>^{tree}` with `GIT_INDEX_FILE` set, `update-index --cacheinfo`,
  `write-tree`, `commit-tree` with the original author/committer env, then move the ref
  and the tag, expire reflogs, `gc --prune=now`.
- **Untracked harness files read as a dirty tree.** Either exclude `TASK.md`/`GUIDE.md`
  or score tracked files only; otherwise every arm fails the cleanliness check.
- **The scorer needs its own negative control.** A control that appends `raise` after
  the script's own exit is unreachable and proves nothing; a check that demands a skill
  the loader correctly hides by `environments:` asserts a false expectation. Break the
  fixture deliberately and watch the scorer fail before trusting a pass.
