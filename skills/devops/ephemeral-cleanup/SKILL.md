---
name: ephemeral-cleanup
description: "Use when a task left ephemeral files; clean them up."
version: 1.1.0
author: user, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
category: devops
metadata:
  hermes:
    tags: [cleanup, hygiene, ephemeral, scratch, nix, wsl]
    related_skills: [nixos-clan-flake, verify-and-stop]
---

# ephemeral-cleanup

Every task that answers a question with files leaves debris: probe scripts, logs,
fixtures, temp clones, caches, mktemp droppings. This skill is the standing rule
that ephemeral things must be cleaned up when their purpose is served — every
task, every time — and the Nix environment is the strict case, because nothing
there cleans itself.

The knowledge survives in skills and in the session record; the files do not.

## When to Use

- The end of any task that created scratch files: probe scripts, captured logs,
  JSON/TSV dumps, temp clones, fixtures, caches.
- Before calling any task done whose evidence files no longer have a reader.
- Don't use for: things that serve a purpose by existing (repos, configs,
  deliberately named backups), caches an installed tool is actively using, or
  the nix store itself — see "What stays".

## The rule (always on)

**If it was made to answer one question, it dies with the answer.** Before the
final report: list what the task created, fold anything durable into the skill it
belongs to, then delete the rest. "Cleaned up" is part of "done", not a favour
to be asked for. This has needed restating more than once; treat it as standing.

## What counts as ephemeral

- Scratch/diagnostic scripts and their outputs; captured logs; probe JSON/TSV.
- `mktemp` files and dirs (`/tmp/tmp.*`), `nix-shell.*` working directories.
- Temporary clones and fixture repos ("probe", "verify", "test" copies).
- Caches of tools no longer installed: e.g. `~/go` (module cache) after a one-off
  Go experiment, `~/.cache/go-build`, `~/.config/go` — `go` itself absent.
- Hermes session scratch: `cache/scratch/` files and `cache/terminal-output/`
  overflow logs (the tree prunes idle entries in 24h; never rely on the pruner).

## The Nix environment is the strict case

The WSL guest's `/tmp` is disk-backed and **never auto-cleaned** — week-old files
survive reboots (verified). Treat every probe run on the guest as a cleanup debt.

- **Sweep `/tmp` at the end of any task that used it.** Scope it to the invoking
  user, and skip: sockets; anything young (`-mmin -120` — an active process's
  temp file is always recent); the system dirs (`.X11-unix`, `.ICE-unix`,
  `.font-unix`, `.XIM-unix`, `systemd-private-*`). Root-owned strays go via
  `sudo`, **but keep `systemd-private-*` by prefix, never with an end-anchored
  alternation**: a pattern like `^(systemd-private-|.X11-unix)$` matches the
  literal string `systemd-private-` and misses every real instance
  (`systemd-private-<id>-<unit>.service-XXXXXX`) — that shape has deleted live
  dirs.
- **Read-only caches need `chmod` first.** Go marks its module cache read-only;
  plain `rm -rf ~/go` fails file-by-file with `Permission denied`. Use
  `chmod -R u+w ~/go && rm -rf ~/go ~/.cache/go-build ~/.config/go`, then verify
  each target is gone.
- **`nix build -o /tmp/…` output symlinks are gcroots.** The symlink is the only
  thing pinning that store path; remove it once the artefact is inspected.
- **`nix-collect-garbage` and generation deletion are never automatic.** Old
  generations are the rollback story; delete only on the owner's explicit word.
- Windows side: end with `cache/scratch/` empty and check the Windows Temp
  directory for strays. Waiting for the 24h pruner is not cleanup.

## What stays (check before deleting)

- System dirs, sockets, young files, `/etc` (managed — hands off).
- Deliberately named backups: a "backup" that disappears is worse than clutter —
  flag it in the report instead of deleting it.
- Working tool caches (`~/.cache/nix`, `~/.npm`, editor state), the nix store,
  and every repo the user keeps.
- **Evidence a report cites.** Before/after audit JSONs, a scored run's directory, a
  subagent's transcript: these exist so a claim can be re-derived later, so keep them
  and list them as kept. A runner's own output is a record, not debris.

## Procedure

1. Inventory what the task created, both sides of WSL. Completion: every file
   created is either deleted or named in the report as deliberately kept.
2. Fold durable findings into the skill they belong to; the files' only reader
   was future-you, and the skill just replaced it. Then delete them.
3. Sweep with the recipes above; print what was removed and what was skipped.
4. Verify the environment after the sweep: the gateway answers,
   `systemctl --failed` is empty, a real connection works.
5. Report: deleted (counts and sizes), kept (with reasons), verification result.

## Pitfalls

- Filter bugs delete live things. Test a skip pattern on one entry before
  running it across the directory; anchor prefix keeps by prefix, not by `$`.
- A `rm` that "finished" may have failed per file — read its output and verify
  each target afterwards; do not report a deletion you did not confirm.
- Deleting `systemd-private-*` does not kill their services but orphans their
  private-tmp mounts until restart; avoid, and if done, say so.
- Sweeping "everything old" without the recent guard can eat live state; the
  `-mmin` guard is not optional.

## Verification

- The sweep printed: N removed, and the kept-list with reasons.
- `/tmp` shows only system leftovers (plus anything named as kept).
- The environment still works — cleanup is proven by the environment, not by a
  command exiting zero.
