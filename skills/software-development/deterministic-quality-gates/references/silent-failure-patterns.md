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

## A membership test against a table keyed by a different axis

`sev in BLOCKING_SEVERITIES` reads as a membership test and is one — against a mapping
keyed by **dimension**. Every lookup returns `False`, so a `continue` written to skip
already-handled findings never fires and the same item is listed twice: once as required,
once as an optional improvement. Nothing errors, because the expression is valid and a
miss is indistinguishable from "not present".

Detection: for every `x in TABLE`, name TABLE's key type out loud. If it is a different
axis than `x`, the test is a constant. The behavioural tell is a branch that never runs —
a skip, a filter, a dedupe — so prove it with an input where the condition *is* true and
assert the branch's effect, not just that no exception was raised.

## An existence test satisfied by a stub

`config.users.users ? name` reads as "the account exists" and is true on every machine
regardless, because a base module assigns `users.users.<name>.shell` for the login shell.
The account was never created; the attribute exists. Any "does X exist" assertion over a
merged configuration has to test a field only the real thing sets (`isNormalUser = true`),
never the presence of the key — merged configs are full of stubs that one module or
another created for its own purpose.

Detection: construct the negative case — the entity genuinely absent — and confirm the
assertion fails. If it passes, the assertion is testing the container rather than the
content, and it will pass in exactly the situation it was written to catch.

## `set -e` does not abort on a failing `&&` operand

Bash exempts every command of an `&&`/`||` list except the last, so a guard written as a
chain guards nothing. `T=$(mktemp -d) && chmod 700 "$T"` continues with `T` **empty** when
`mktemp` fails, and `git clone … && cd … && <gate>` falls through with the cwd still in the
caller's tree — the gate then measures the tree you were already in and reports it as the
thing you meant to check. Measured both ways: the chained form printed `FELL THROUGH` and
exited **0**; the same failure on its own line exited **128**. Give each command its own
line, or `|| { echo … >&2; exit 1; }` on the one that must not fail.

Detection: break the FIRST command of every chain in the recipe and confirm the block still
aborts. A recipe tested only on its happy path cannot show this.

## `lstrip("./")` strips a character set, not a prefix

`str(path).lstrip("./")` removes any leading run of `.` and `/` characters, so `.env`
becomes `env`, `.review-council/x/council.log` becomes `review-council/x/council.log`, and
`.github/workflows/ci.yml` becomes `github/workflows/ci.yml` — a path that exists nowhere,
cited as the location of a real finding. Nothing errors: the string is valid, it just names
a different file. Use `while text.startswith("./"): text = text[2:]`, and route every call
site through one helper so the form cannot reappear in one module out of nine.

Detection: a structural grep for `lstrip("./` in the source, asserted empty. The bug is
invisible in output that looks like a plausible path, so the test has to read the code.

## A 0-based index reported as a line number

Tree-sitter and most JSON location APIs report `row`/`line` **0-based**; a report a human
reads is 1-based. Used unshifted, every finding cites the line *above* its own — 44 for a
`uses:` on line 45 — which points the reader at a comment and makes a true finding look
false. Add one at the boundary where the coordinate enters your vocabulary, and name the
convention in a comment there.

Detection: the existing test is the trap. A test asserting `"7"` for `row: 7` was written to
match the code's output, so it pinned the off-by-one and a green suite carried it. Assert
the line the fixture actually puts the token on, read off the file, not off the parser.

## `git ls-files -s <dir>` lists a directory's contents, never the entry

Asking for the mode of a directory path returns one line per file **inside** it at
`100644`, and `040000` never appears — so a check that distinguishes "a real directory" from
"a plain file" by mode reads a correct directory as a file, or as absent for an empty one
(git does not track empty directories at all). `git ls-tree HEAD <path>` reports the entry's
own mode: `120000 blob` for a symlink, `040000 tree` for a directory, `100644 blob` for a
file. Use `ls-files -s` for the symlink case only.

Detection: create both markers — a real directory and a symlink — and assert the check
accepts each. A fixture with only the symlink cannot show this.

## A scanner that ignores the harness's own skip list

A third-party scanner invoked on the tree root (`gitleaks detect --source .`) walks
*everything*: it does not honour `.gitignore` and knows nothing about the framework's
`SKIP_DIRS`, so the tool re-reports the run's own scratch — its logs, its quoted scanner
output — as fresh findings. Measured on a 377-file repository: **274 hits, 270 of them
ignored scratch**, burying the three real ones and deflating the score for a reason the code
could not see. Configure the scanner from the same list the harness uses, and keep the
scanner's shipped ruleset (`[extend] useDefault` in gitleaks) so only paths are excluded,
never detection.

Detection: assert the config and `SKIP_DIRS` cannot drift apart, and run the probe on a
fixture holding one real defect plus a copy of it inside a skipped directory — the expected
result is exactly one finding.

