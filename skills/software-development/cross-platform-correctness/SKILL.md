---
name: cross-platform-correctness
description: "Use when code must work on Windows, macOS and Linux."
version: 1.0.0
author: Storm, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
category: software-development
metadata:
  hermes:
    tags: [cross-platform, portability, windows, paths, encoding, comparison]
    related_skills: [nixos-clan-flake, deterministic-quality-gates]
writes: [none]
side_effects: [none]
---

# cross-platform-correctness

Code whose behaviour does not depend on which operating system runs it — and,
harder, catching the places where it silently does.

**This class of bug rarely raises.** A comparison that never matches zeroes a
metric, drops every record, or reports a clean result, and the output looks like
data rather than a fault. Nothing crashes, so nothing points at the cause, and the
platform you develop on cannot see it at all. Assume a wrong answer, not an error.

## When to Use

- Code that runs on more than one OS, or whose output another tool or process consumes.
- Serializing paths, line endings, or numbers into JSON, an artifact, a log, or a cache.
- A metric, match rate or count that is zero — or suspiciously perfect — on one platform.
- A test that passes locally and fails on exactly one CI leg.
- Reviewing an equality comparison between values that come from different sources.

## Rules (always on)

**Normalize at the comparison, and normalize BOTH sides.** Two producers writing the
same logical value will disagree on its representation, and an equality check then
fails — silently, on one platform only. Put the canonicalization in one helper and
call it on every side of every comparison. Normalizing only the side you consider
"correct" is not enough: the other producer may be echoing the host's own convention
back at you, so a comparison that works only when both agree is a coincidence, not a
check.

**A path's string form is a platform detail, not a serialization format.**
`str(path)` — and `str(path.relative_to(root))` — yields backslash-separated text on
Windows and forward slashes elsewhere. Use `as_posix()` for anything that crosses a
boundary (an artifact field, a JSON key, a comparison against a documented shape),
and keep the native form only for display to a human on that host. A repo-relative
path's canonical spelling is forward-slashed with no leading `./`.

**A failed comparison inverts a metric rather than erroring.** When a matcher keys on
normalized identity, one mismatched representation does not lose one record — it makes
the match rate `0` *and* reclassifies every true positive as a false positive. A
recall that is exactly zero, or a precision that is exactly perfect, is the signature:
check the identity function before believing the number.

**Assert by parsing, not by shape.** An assertion on a string's shape encodes the
conventions of the machine it was written on — a suffix check, a hardcoded separator, a
quoted form. Parse the value with the same tokenizer the real consumer uses (`shlex`
is the shell's own tokenization) and assert the *contract* — arity, that no token is
empty, that the last token is the expected one. A shape assertion is a proxy; the proxy
is what breaks, not the code.

**A test guarded by an environment condition asserts nothing when the condition is
false.** `if " " in path: assert quoted` passes on every machine without a space in
the path, which is most of them. State the property unconditionally instead — a
round-trip (re-quote, re-parse, compare) tests the same thing everywhere and cannot
degrade into a no-op.

**Verify an emitted command executes in the target shell.** Quoting that is correct for
one shell's rules may not be executable by the consumer at all, and the failure lands at
run time in a different process, long after the build. Run the command in the shell that
will receive it; do not reason about whether the quoting is right.

**Exercise the normalizer directly, with both representations.** A cross-platform bug is
invisible on the platform you develop on, so the fastest durable guard is a test that
feeds the helper a Windows form and a POSIX form and asserts they collapse to the same
value. That assertion is platform-independent and fails everywhere the day someone drops
the normalization — which is strictly better than waiting for the one CI leg that can
see it.

**Prefer one canonical form over per-platform branches.** An `if windows: … else: …`
inside a comparison is a second implementation that will drift. Normalize once, compare
once.

**Locate your own script without an external tool.** `$(dirname "${BASH_SOURCE[0]}")`
needs `dirname` on PATH, and when it is absent the command substitution is empty — so
`cd "/.."` succeeds and the script silently operates on `/` instead of failing. The same
wrong-answer-not-an-error signature as everything else here: it reports finding nothing
rather than erroring. `${BASH_SOURCE[0]%/*}` is equivalent for self-location and needs
nothing. Keep `dirname` for a path the *user* supplies, where its semantics (a bare name,
trailing slashes) are what you actually want.

**Run a shipped script under a stripped PATH before believing it is portable.**
`env -i PATH=/usr/bin:/bin bash script.sh` surfaces every undeclared dependency on an
external tool. They are invisible on a development machine, which has them all, and the
ones that fail this way usually change behaviour rather than stopping the script.

**An explicit environment override beats a PATH lookup.** A `which`-style lookup cannot
see a tool provided outside PATH — mounted into a container, installed beside the default
one. Read an explicit variable first and fall back to the lookup, so an alternate install
can be named without rewriting PATH for every caller.

**Nothing that ships may name this machine.** A test fixture, a doc example, an error
message, a sample defect and a skill are all read on other machines, where your home
directory is wrong and meaningless. Use a placeholder (`/home/user/projects/myrepo`,
`C:\Users\<you>`). That holds for historical records too — the fact each records survives,
the incidental path does not, and a reader who sees your path learns nothing from it.

**A fixed PATH must name every place the tool can be installed.** A script builds a PATH
rather than inheriting one when a hostile PATH must be kept out — but listing only the
distribution you develop on means the tool is not found anywhere else. `nix` is in
`/run/current-system/sw/bin` on NixOS, `~/.nix-profile/bin` or
`/nix/var/nix/profiles/default/bin` on other distributions, and `/bin` in a minimal
container image; naming one silently breaks the rest. The failure is the usual quiet one:
a helper that resolves a toolchain by running a command reports "did not run" and a
coverage term drops, with no error. List the candidates in precedence order and let the
missing ones fall through — an entry for a directory that does not exist costs nothing.

**Turn a path audit into a check, and guard the guard.** A one-off sweep decays; a test
that scans the shipped files keeps it true. Two assertions make it trustworthy: that the
detector still matches the lines it claims to (a regex that silently matches nothing
passes forever, which is the same wrong-answer-not-an-error failure this skill is about),
and that the allowlist is still exercised (a list of permitted names that no longer
appears anywhere cannot be reasoned about). Watch the false positives that make such a
check unusable: a line that *prepends* to `$PATH` inherits the ambient value and needs no
locations of its own, `Environment=PATH=$VAR` is a use rather than a definition, and a
variable named `*_PATH` may hold a single file rather than a list.

## Procedure

1. **List every value that crosses a boundary** — between the filesystem and an
   artifact, between a tool's output and a lookup table, between two processes, between
   a host and a serialized file.
2. **Name each one's canonical form** and write it down (forward-slashed relative path;
   UTF-8 without BOM; UTC; a fixed decimal format).
3. **Put the canonicalization in one helper** and route every comparison through it.
   Normalize both operands, never just one.
4. **Feed that helper both representations in a test** — this is the guard that works on
   any platform, so it runs on the one you are actually developing on.
5. **Run the suite on each supported platform** (a CI matrix is the usual way). Treat a
   single-platform failure as a real defect, not as CI flakiness: this class is
   deterministic, so it reproduces.
6. **When one leg fails and you cannot run that platform locally**, read the failure for
   which *representation* differs before assuming the logic is wrong — then confirm the
   fix by the helper's own test, not by reasoning.

## Pitfalls

- **Normalizing only one side.** The other producer may return the host's convention, so
  the comparison still fails — and now it fails asymmetrically, which is harder to see.
- **Making the truth canonical and leaving the input alone.** The producer that runs on
  the target platform is the one you cannot test from here; normalize what it *sends*,
  not only what you *expect*.
- **Stripping `./` with a character-class strip.** `lstrip("./")` removes *any* leading
  run of dots and slashes and will mangle a path that legitimately begins with them. Strip
  the literal prefix in a loop instead.
- **Dedup keyed on an unnormalized string.** If two spellings of one path fingerprint
  differently, a count of distinct items is inflated and whatever keys off it looks more
  productive than it is.
- **A lookup table keyed on a command's literal text.** The value someone *types* differs
  from the name the table expects (`nix flake check` vs `flake-check`), and a name derived
  from the first two tokens will not reach it. Map the invocations you know to canonical
  names in one explicit table rather than inventing a general rule that half-works.
- **Locale-dependent number and date formatting.** Decimal separators, thousands
  separators and date order vary; a parse that assumed one convention truncates or throws.
  Format and parse explicitly.
- **A byte-exact comparison over text.** Line endings, a BOM, or a trailing newline make
  it differ for reasons unrelated to content. Compare parsed content, or normalize at read.
- **Auditing for machine paths in one spelling.** A path appears quoted, escaped and
  backslashed, and a fixture holding a Python string literal stores a doubled backslash
  for each one — so a grep for the single-backslash form matches nothing and the audit
  reports clean. Grep case-insensitively, for both spellings, and for the username and
  hostname separately from the full path.

## References

- `references/representation-mismatches.md` — the checklist of value kinds that differ
  across platforms, their symptoms, and the canonical form to pick.
- `references/shipping-to-other-machines.md` — auditing a repo for local assumptions, and
  packaging it so it runs on someone else's host.
