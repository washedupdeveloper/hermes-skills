# Representation mismatches between producers

A checklist for step 1 of the procedure: every value that crosses a boundary, the way
two producers spell it differently, what a mismatch *looks like* when it bites, and the
canonical form to pick.

Reach for this when a metric is exactly zero or exactly perfect on one platform, when a
lookup never matches, or when a file that demonstrably exists is reported missing.

| Value | How the two sides differ | Symptom when it bites | Canonical form to pick |
|---|---|---|---|
| Repo-relative path | `Path.relative_to` gives `a\b.py` on Windows, `a/b.py` elsewhere; a documented field says `relative/path` | equality fails on one platform only — match rate `0`, every true positive reclassified as a false positive | forward slashes, no leading `./`, normalized on **both** operands |
| Absolute path | drive letters, UNC (`\\host\share`), `C:/` vs `/mnt/c/` | "file not found" for a file that exists | resolve through a path object; never string-concatenate |
| Path case | Windows and macOS filesystems are case-insensitive by default; Linux is not | dedup counts one file twice, or two files once | compare case-insensitively only where the filesystem is; do not assume either way |
| Line endings | CRLF vs LF, per file and per checkout setting | byte-exact comparison or hash differs; an anchored regex misses | normalize on read; read bytes when *checking* endings |
| Text encoding | UTF-8 vs locale default; optional BOM | mojibake; a BOM breaks a parser expecting byte 0 | always pass `encoding=` explicitly; strip a BOM on read |
| Number formatting | decimal comma vs point; thousands separators | a parse truncates or throws | format and parse with a locale-independent method |
| Float in an artifact | binary float repr drifts across versions and operations | a pinned golden value fails for a rounding difference | pin with a tolerance, not equality |
| Shell quoting | POSIX quoting rules applied to a native path | the command fails at run time in a *different* process | run it in the shell that will receive it |
| Command / tool name | the text someone types (`nix flake check`) vs the name a table expects (`flake-check`) | a lookup never matches, silently | map known invocations to canonical names in one explicit table |
| Timestamp / timezone | local time vs UTC; DST transitions | ordering off by hours; same-day comparisons wrong | store UTC, format explicitly |

## Two shapes of fix

**Canonicalize at the comparison** when the value is opaque to you and you only need
identity — a path echoed back by a model or a tool, a name typed by a human. One helper,
applied to both operands.

**Canonicalize at the boundary** when *you* are the producer and the value is persisted
or handed onward — serialize the canonical form so every consumer receives one spelling.
Do this in addition to the comparison, not instead of it: the consumer may still send
back something else.

## Picking a canonical form

Prefer the one that is already the documented or wire format for that value, even when
it is not the host's native form. A repo-relative path is a POSIX-style string by
convention; a timestamp is UTC by convention. Fighting the convention means every other
tool has to normalize against you.
