# Silent failure patterns

Patterns where code reports success while doing nothing, or a check lies about what it
measured. Each one defeats a gate or a test while leaving the output looking clean, so
each is worth a deliberate assertion rather than trust.

Distilled from real defects found by review — the mechanism matters more than the
instance.

## A suffix filter silently skips the file it names

`pathlib.Path('.env').suffix` is `''` — a dotfile has no suffix — so a walk filtering on
`suffix.lower() in suffixes` never yields `.env` even when `.env` is in the list, and the
secret scanner reports **clean on a file it never opened**. Any name-based filter must
match the bare name as well as the suffix.

Detection: assert on a fixture containing the exact file the filter claims to cover. A
fixture without it cannot catch this.

## A shallow copy aliases nested state

`{k: dict(v) for k, v in DEFAULTS.items()}` copies one level. Nested dicts and lists stay
the **same objects**, so a caller that mutates the returned config corrupts the
module-level default for the rest of the process — surfacing later as an unrelated test
failing, which sends the reader to the wrong file. Use `copy.deepcopy` when the returned
structure is mutable and the source is a module constant.

Detection: mutate the returned object, then re-read the source constant. The test that
catches it is one that appends to a nested list, not one that reads.

## One function-scoped name reused for two shapes

Python gives a function **one binding per name**, so a second assignment in the same
scope inherits the first's inferred type. A type checker then reports a genuine error at
the second use that is really a shadowing bug: the fix is to rename the second variable,
not to annotate it. Renaming also removes the real hazard, which is a reader believing
two different dicts are one.

Detection: two assignments to one name with different value types in a single function.
Read the checker's reported line, not just its count.

## An invariant enforced in the caller is invisible to the checker

When a callee requires a value that its only caller already guarantees — a run directory
that qualified on a recorded field — both `mypy` and `pyright` flag the callee, because
neither can see across the two functions. A guard there is **dead code**: the branch
cannot be reached. State the invariant with an `assert` naming the file or the reason, so
it fires at the invariant if the caller's contract ever changes, and so the checkers stop
reporting a non-problem.

Detection: reproduce before fixing. If the claimed crash needs a state the caller cannot
produce, the finding is about provability, not runtime behaviour.

## A payload delivered as a command-line argument

The kernel caps a single argument at `MAX_ARG_STRLEN` — 65536 bytes on Linux. A prompt or
payload assembled from real input (a repository's probe JSON runs to ~400 KB) dies with
`[Errno 7] Argument list too long`, and the failure surfaces only as an opaque non-zero
exit code. Pass large text through a **file** instead, and check the tool's own flag for it
(`--query-file` alongside `-q`); a file is also not shell-interpreted, so quotes and
substitutions in the payload survive verbatim.

Detection: measure the real artifact. This passes on a small fixture and fails on every
input large enough to matter, which is the worst shape a bug can have — a green fixture
run proves nothing about it.

## A test suite that aborts at collection

Two test files with the same basename, in directories that are not packages (no
`__init__.py`), collide: collection stops with `Interrupted: 1 error during collection`
and **none** of the suite runs. Give test modules unique basenames, or make the
directories packages.

Detection: a summary line reporting zero failures is not evidence of a passing suite.
Check that the expected number of tests was collected, and treat a collection error as
zero coverage of the code that ships.

## A path check that does not strip the URL fragment

Testing `(doc.parent / target).exists()` against a link written `README.md#section`
reports a valid link broken — the fragment is not part of the path. Split on `#` first.
In a gate that exits non-zero on failure, a false positive is a false alarm that trains
the reader to ignore the gate.
