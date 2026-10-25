---
name: cross-platform-test-portability
description: "Use when tests must pass on Linux, macOS and Windows."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
category: software-development
metadata:
  hermes:
    tags: [testing, ci, portability, windows, macos, pytest]
    related_skills: [deterministic-quality-gates, surgical-patch, verify-and-stop]
---

# Making a test suite pass on every OS

A suite that is green on the machine it was written on and red in CI is usually not a
code bug. It is a test that assumed its host: a path that resolves differently, a
fixture only one OS can execute, a flag only GNU coreutils has. The fix belongs in the
test, not in the code it exercises — the code was right and the assertion was
parochial.

The CI matrix is the specification. If the workflow runs `tests (ubuntu-latest)`,
`tests (macos-latest)` and `tests (windows-latest)`, then "passes" means all three, and
a green run on one of them is a third of the evidence — say which third you have.

## When to Use

- CI fails on one OS and passes on the others.
- Writing a test that touches paths, temporary directories, subprocesses, file modes
  or the shell — anything whose meaning is host-dependent.
- A test passes locally and someone asks whether it will pass on Windows or macOS.

## Procedure

1. **Get the failing node IDs before touching anything.** A platform failure names its
   tests; ask for the `FAILED ...` lines or the `short test summary info` block from that
   job. Fixing a guessed cause is how you add a second bug to the one you were sent.
   **When you cannot read the log at all** — a job's log needs admin rights on the
   repository, so an outside contributor, or an agent with no token, gets `403` — the
   check-run **annotations** are served unauthenticated for a public repository and name
   the failing test. Read them, and if the workflow emits none, add a step that does
   (pytest `--junitxml` plus a reporting step). Build that step the first time a
   platform-only failure is invisible, because the next one will be too — the endpoints and
   a worked example are not yet written up as a reference, and that gap is worth closing.
2. **Reproduce the host condition on the machine you have.** You almost never need the
other OS — you need the condition. A directory reached through a symlink reproduces
macOS's `/var` → `/private/var`; a file with no extension reproduces what Windows'
CreateProcess refuses. Write the probe, print both sides, and show the assertion
failing for the reason you claim. Recipes: `references/reproducing-host-conditions.md`.
To find the whole class before fixing the one test that failed, run
`scripts/platform-sweep.py <repo>` — it greps ~20 host-assumption categories (path
resolution, exec bits, temp paths, process spawning, GNU-only flags, locale, reserved
names, interpreter names) and prints file:line per category, so the fix covers the
siblings instead of the symptom.
3. **Fix the assertion, not the code under test** — unless the probe shows the code is
genuinely wrong on that platform. In the resolved-vs-raw case the function was right
(it returns what the environment handed it) and the test was wrong; changing the
function would have been a real regression.
4. **Match the file's own convention.** If the sibling assertions compare raw values,
the odd one out is the bug. Grep the rest of the suite before choosing a shape.
5. **Guard, or skip with a reason — never weaken the assertion.** A guard that turns a
real check into a no-op trades a red CI for a silent hole.
6. **Prove the guard fires.** Force the platform flag to the other value in a throwaway
copy, run it, and confirm the tests skip *and name their reason*. A guard never
observed to fire is a guess.
7. **Run CI's exact invocation, on the interpreter CI pins.** `pytest tests/` and
   `python -m pytest tests/` differ in `sys.path` handling, and the job's command is the
   one that decides. The *version* matters as much as the command: a devshell or venv on
   a newer Python tests a version no runner uses, so a construct newer than the pinned
   one passes locally and fails on every job. Read the workflow's `python-version`, run
   the suite on that version, and check any floor the docs claim as a separate fact —
   `nix shell nixpkgs#python312Packages.pytest -c pytest tests/ -q` for a pinned 3.12.
   For syntax alone, `ast.parse(src, feature_version=(3, 12))` flags what the pinned
   interpreter cannot parse without needing it installed.
8. **State the limit.** If you cannot run the target OS, say the fix is proven by
reproducing the condition, not by a run on that host. Never imply a green Mac run you
did not get.

## The matrix is not the only job

A workflow usually has more than its test matrix — lint, a type check, a build, a
policy gate. Read every job before calling CI fixed, and run them locally, because a
failure in one of them is not a platform bug and the portability sweep will not find
it.

**When a policy gate fails on a file you added, the gate is usually right and the file
is redundant.** A repository that enforces "one language, one entry point" will fail its
check on a helper script you introduced to wrap something that already exists. Route the
work through the entry point the repo already has — the wrapper was a second way to do
the same thing, which is exactly what the gate exists to prevent. Delete it, update the
docs that named it, and keep the reasoning: the gate's own message is usually a design
decision already written down.

## Rules (always on)

**Compare like for like — never a resolved path against an unresolved one.**
`Path(td).resolve()` against a value the function returned verbatim passes on Linux and
fails on macOS, where `TMPDIR` sits under `/var`, a symlink to `/private/var`, so
`resolve()` yields a different string for the same directory. Decide which side owns
resolution and apply it to both, or to neither.

**When the question is "is this the same directory", ask the filesystem.**
`os.path.samefile(a, b)` beats aligning two `Path` strings, because the two names may
never converge: `tempfile` hands back `/var/folders/...` while `getcwd()` returns the
resolved `/private/var/folders/...` on macOS, and Windows can return an 8.3 short path
for the same directory. `==` on `Path` objects is a *string* comparison and cannot know
that. Use `samefile` in any assertion comparing a path you were given against a path you
derived — and note that it requires both paths to exist, which is exactly what makes it
the right question.

**A relative path is not a string — normalise separators before comparing or printing.**
`str(Path.relative_to(...))` and `os.path.relpath()` yield `docs\\MILESTONES.md` on
Windows, so an assertion against the literal `docs/MILESTONES.md` passes on Linux and
macOS and fails there, with a diff whose only difference is a backslash. Call `.as_posix()`
and compare that. Decide *where* to fix by asking who owns the string: when a **test**
builds the path to assert *which* file was found, normalise in the test; when the
**tool** prints or reports the path, normalise in the tool, because output that differs by
separator is a portability bug in the product rather than in the assertion.

**A suite step with `continue-on-error: true` reports success when it fails.** Read the
*enforcing* step, not the suite step: a matrix job can show `run the suite: success` while
the annotation step after it exits 1 on the parsed failures. Judge a job by its
conclusion, and when it fails with no readable log, read the check-run annotations —
those name the failing test and are served unauthenticated for a public repository.

**A fixture that must execute has to be executable by the target OS.** A `#!/bin/sh`
file with no extension runs on POSIX and not on Windows: CreateProcess resolves
executables by extension, so the call fails and anything asserting the fixture *works*
fails with it. Guard only the block that needs it to run and keep the assertions that
still hold on Windows outside the guard, so the test is skipped exactly where it cannot
work rather than being disabled wholesale.

**A test asserting a platform-only capability is asserting the wrong thing.** When the
code branches on a facility — `import pwd`, then return early when it is missing — the
correct behaviour on a platform without it *is* that early return, so a test asserting
the capability worked fails there while the code is right. Guard that test, and pin the
other branch on every platform by making the import fail: assigning `None` into
`sys.modules` makes `import <name>` raise `ImportError`, so the fallback is exercised
wherever the suite runs instead of only on the OS that lacks it. Recipe:
`references/reproducing-host-conditions.md`. This turns a platform-specific gap into an
ordinary test, and it is the difference between a guard you believe and a guard nobody
has run.

**Guard on the capability, not the OS name.** `os.name != "nt"` names the platform when
what the test needs is a *facility*. Ask the interpreter instead —
`importlib.util.find_spec("pwd") is not None` — because the two come apart: a module can
be absent for a reason other than the OS, and the OS can gain one. A capability probe
also reads correctly on the platform you are *not* on, which is exactly where the guard
has to be believed.

**A skip without a reason is indistinguishable from a deleted test.** Pass the reason
to `pytest.skip("...")` so the summary prints it, and write the why in a comment at the
guard — the next reader must be able to tell "the platform cannot do this" from "nobody
finished it".

**Prefer a test that works everywhere to one that is skipped somewhere.** Reach for the
guard only when the platform genuinely cannot express the case.

**A platform guard can hide a real coverage gap — name it.** When the guarded block was
the only test of a path (a `.cmd` launcher beside the `#!/bin/sh` one), say so in a
comment rather than leaving the impression of coverage.

## Pitfalls

- **`/tmp` is not `/tmp`.** macOS: `/tmp` → `/private/tmp` and `/var` → `/private/var`.
  Compare resolved to resolved or raw to raw, never across.
- **A hardcoded `/tmp/...` path.** Use `tempfile`; on Windows the equivalent is
  `%TEMP%` and a literal `/tmp` may not exist at all.
- **GNU-only flags.** `readlink -f`, `stat -c`, `sed -i` (needs an argument on BSD),
  `date -d`, `mktemp -d --tmpdir`. Prefer Python over shelling out to a tool whose
  flags are not portable.
- **macOS ships bash 3.2** at `/bin/bash`. Arrays, `mapfile` and other bash 4+ syntax
  fail there while working on Linux.
- **`os.fork` / `multiprocessing` under the default start method.** Windows spawns, so
  a module-level side effect or an unpicklable argument fails there and nowhere else.
  Guard the entry point with `if __name__ == "__main__"`.
- **CRLF.** A CRLF shebang fails on Linux/WSL2 with `bad interpreter ...^M`, and a
  mixed pair makes a byte comparison report false drift. Pin the newline on write
  (`newline="\n"`) and assert it, allowing `.bat`/`.ps1`/`.cmd` to differ. Pinning the
  write is only half of it: a **Windows runner checks out with `core.autocrlf=true`**, so
  the files the tests read arrive CRLF before any of your code runs, and a tree-wide
  `* text=auto eol=lf` in `.gitattributes` is what protects every file at once. Simulate
  that checkout rather than trusting it — recipe in
  `references/reproducing-host-conditions.md`.
- **Case-insensitive filesystems.** Two files differing only in case coexist on Linux
  and collide on macOS/Windows — and on Windows the collision is silent at write time.
- **Locale-dependent ordering.** `sorted()` on `str` and `locale.strxfrm` both move
  with the host's collation. Assert on a set, or sort with an explicit key, rather than
  on a list order the locale happened to produce.
- **A file-mode assertion.** `chmod` and the executable bit mean little on Windows, so
  a test that asserts a mode, or depends on one, is POSIX-only.
- **Assuming `python3` exists.** Windows has `python`; NixOS has neither name. Resolve
  the interpreter the way the host provides it.
- **Treating a sweep hit as a finding.** A category grep is high recall and low
  precision: most hits are correct code — a Windows branch in a launcher, a `.exe`
  suffix handler, a `chmod` on a POSIX-only path, a guard that already catches the
  `ImportError`. Open each hit, decide it against the code, and record the ruling. The
  value is in the ruling out; a sweep left unclassified is noise that buries the one
  real hit. Expect the fix to be one or two sites out of hundreds, and say which hits
  you cleared and why rather than reporting the raw count.
