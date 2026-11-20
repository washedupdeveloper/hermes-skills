---
name: hermes-file-editing
description: "Use when Hermes refuses a write. Read fully, or patch."
version: 1.1.0
author: Storm, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
category: autonomous-ai-agents
targets: [hermes]
metadata:
  hermes:
    tags: [hermes, file-tools, write_file, patch, staleness, guard, workflow]
    related_skills: [hermes-agent]
---

# hermes-file-editing

Editing files through Hermes' own tools without tripping the staleness guard, and
reading its two warnings for what they actually are.

## When to Use

- `write_file` returned `stale_write_blocked`.
- A `patch` succeeded but carried a `_warning` about a partial view or an external edit.
- The desktop or CLI showed a `⚠️ File-mutation verifier:` footer at the end of a turn.

## Two warnings, two meanings — never conflate them

| Surface | What it is | Did the edit land? |
|---|---|---|
| **Inline `⚠️` on the tool result** | a *warning* attached to the call | **Yes** — `patch` returns `success: true` plus a `_warning` |
| **`⚠️ File-mutation verifier:` turn footer** | a *failure* never superseded | **No** — the listed calls failed |

The footer is assembled at turn end from `write_file` / `patch` calls that returned an
error and were never later resolved. Only those two tools are tracked, and a
**successful patch clears the entry** — so a patch warning can never produce a footer.

Do not attribute a footer to patch warnings. They are different code paths, and
diagnosing the wrong one wastes the whole pass.

## The three staleness causes

`file_state.check_stale` — and the `write_file` guard built on it — fires for exactly
three reasons:

1. **drift** — "modified since you last read it on disk (external edit or unrecorded
   writer)". The file's mtime moved since your last read.
2. **partial** — "was last read with offset/limit pagination (partial view)".
3. **no baseline** — "has not seen its full current content".

## A refusal that is not the guard: a `\\wsl.localhost\` path

The two tools die before the guard is consulted when the target sits behind a WSL UNC path:

```
Failed to write file: mkdir: cannot create directory '//wsl.localhost': Read-only file system
```

The path is valid and the file is writable — the tool collapses the `\\` prefix and tries to
`mkdir` it. No read clears this, no spelling of the path avoids it, and the same file written
through `terminal` succeeds. Treat it as a *different* failure from `stale_write_blocked`: more
reading cannot help, and retrying in a loop spends the turn.

**Stage on the side the tools can write, place it through the shell.** Write the content to the
scratch directory the tools can reach, then move it into place from inside the guest:

```bash
tr -d '\r' < /mnt/c/.../scratch/stage/SKILL.md > /home/<user>/projects/<repo>/skills/<cat>/<name>/SKILL.md
```

`tr -d '\r'` is not decoration: a Windows-side write can carry CRLF into an LF-only tree, and the
copy is the last place it can be removed. For a *targeted edit* rather than a whole file, apply the
replacement with a small anchor-checked script run through the same interpreter
(`nix develop -c python3 <edit script> <file>`) instead of a heredoc.

This is the one place where "never edit a file through `terminal`" does not apply. That rule
protects a baseline; a path the tools cannot open has no baseline to protect, so the shell copy is
the only route. Everywhere else the receipt still matters.

## Rules

**Read a file in full before `write_file`.** A whole-file overwrite requires a
full-content baseline, and a windowed read does not establish one. Page contiguously
to the last line and the baseline is granted.

**Prefer `patch` for anything large.** If you are changing part of a file you do not
need a full read at all — `patch` succeeds after a windowed read. Paging a 2,000-line
file into context purely to overwrite it is the expensive way to do the same job. The
guard's own refusal message says so: *"...or use patch, before overwriting it."*

**A full read does not always clear a partial state — stop re-reading and patch.** The
windowed-read marker can survive a later contiguous read of the same file, so
`write_file` refuses again with "last read with offset/limit pagination" while the
content you hold is complete. Re-reading in a loop does not fix it. Switch to `patch`,
or to the splice below when the change is structural. Measured: a 230-line module read
in one call was still refused; the patch route landed the same change first try.

**A structural rewrite is a splice, not a hundred patches.** Moving a whole block
between modules with `patch` leaves call sites behind, and `replace_all` on a fragment
anchor rewrites syntax you did not mean to touch — replacing `sample(1,` with
`sample(` produced `sample( raw())` and left every other call site unconverted. When
the change is "cut lines A–B and add an import", do it with a small script that reads
the file, cuts between two named markers, writes it back and prints the new line count;
then read the file once so the guard has a fresh baseline. The script's write is
unrecorded, so expect the next edit to carry a warning — that is the warning, not a
failure.

**A multi-file edit is one script with anchored refusals.** When the same change lands in
ten or twenty files (a rename, a new field, a signature), write one script holding
`EDITS = [(path, old, new), …]`, accumulate each file's replacement into a
`planned: dict[Path, str]`, and write only after every anchor has been checked. Planning
every edit against the *pristine* text is the failure to expect from the naive version:
two edits to one file both replace the original string and the last write silently drops
the other. Refuse the whole batch — print `REFUSED: <file>: anchor found N times` and
touch nothing — when any anchor is not unique, so a drifted file fails loudly instead of
half-applying. Write with `newline="\n"` to keep the batch LF on Windows, and prefer a
unique multi-line anchor over a short one (`return x`) that a second site also matches.

**At end of file, a diff can join two lines that are separate on disk.** Patching the last
entry of a file with no trailing newline renders the removed and added text on one line
(`-old]++[[new]]`), which reads as corruption. The write itself is fine: read the final
lines and confirm both entries exist before repairing anything — a re-patch on that
suspicion duplicates the block.

**`write_file` writes exactly the bytes you give it — end every text file with a newline.**
Nothing appends one, so content strings that stop at the last character produce a tree where
every file shows `\ No newline at end of file`, and an EOF patch renders two entries on one
line. Put the newline in the content, and gate it with a test that walks the shipped text
files and fails on a missing final byte. Exclude fixtures whose digests are pinned: adding
the newline changes their hashes and breaks the expectation the fixture exists to hold.

**On Windows, an edit through these tools writes CRLF — and `.gitattributes` hides it.**
Python's text-mode write translates `\n` to `\r\n` on Windows, so a file edited
through `write_file` or `patch` (and `skill_manage`, which patches the same way)
comes back CRLF even when every committed blob is LF. `git status` still reports
only `M`, because `* text=auto eol=lf` normalises on commit, and the committed
blob *is* LF — so nothing looks wrong. The working tree is not. On an LF-only
repo, strip the CRs before committing and verify the **blob**, never the working
tree:

```bash
git cat-file blob HEAD:<path> > blob && python -c "print(b'\r\n' in open('blob','rb').read())"
```

Measured: after a `skill_manage` patch on Windows, a 320-line file was 320/320
CRLF while all 47 sibling files in the same clone were LF-only.

**Pass native tools absolute Windows paths.** In git-bash, `/tmp` is MSYS's own
directory; native git resolves `/tmp/msg` somewhere else and fails with
`could not read log file`. `git commit -F` wants
`C:/Users/<user>/.../msg.txt`.

**Never edit a file through `terminal` or `execute_code`.** Those writes leave no
receipt, so the guard sees an unexplained mtime change on your next edit and reports
an "unrecorded writer" — which is you. Use `patch`. The same applies to an
`rm` + rewrite cycle: the rewrite has no baseline.

**A failed edit is not resolved by a later turn.** The footer is per-turn: only a
same-turn success, or a disk change before the turn ends, clears an entry. If a write
is refused, fix it in that turn rather than leaving it outstanding.

## Procedure

When `write_file` is refused:

1. Read the current content **in full** — page to the last line — or
2. Use `patch` for the specific change instead. Usually the right answer, and it
   needs no full read.

When a footer appears, confirm what actually landed rather than trusting the summary:

```bash
git status --short
```

## Verification

The guard is satisfiable, and all three paths were measured rather than assumed:

| sequence | result |
|---|---|
| windowed read → `write_file` | refused (`stale_write_blocked`) — this is the footer's cause |
| page to the last line → `write_file` | succeeds when that read established the baseline; a file also read through a window earlier can still be refused — patch instead of re-reading |
| windowed read → `patch` | succeeds; inline warning only, no footer |

A file written successfully also gains a full-write baseline, so consecutive
`write_file` calls on the same unchanged file stay clean.
