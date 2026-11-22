---
name: ephemeral-cleanup
description: "Use when a run must leave no state; sandbox and clean up."
version: 1.3.1
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
- Running a shell, test, reviewer or other child process that must read the host
  but not write to it: sandbox it first — `references/sandboxing.md`.
- Before calling any task done whose evidence files no longer have a reader.
- Don't use for: things that serve a purpose by existing (repos, configs,
  deliberately named backups), caches an installed tool is actively using, or
  the nix store itself — see "What stays". For whether such an artifact should
  exist at all, use `artifact-retention-audit`.

## The rule (always on)

**If it was made to answer one question, it dies with the answer.** Before the
final report: list what the task created, fold anything durable into the skill it
belongs to, then delete the rest. "Cleaned up" is part of "done", not a favour
to be asked for. This has needed restating more than once; treat it as standing.

**Ephemeral is the default, not an option.** When the standing rule is
zero-footprint, every write-capable shell, code run and runner starts in a
private tree or sandbox and is removed after the result is printed. A persistent
run directory is the explicit opt-in (`--no-ephemeral`), not the default; a
`--keep DIR` copy is how evidence survives. A run that leaves state the caller
did not ask for is a defect, not a convenience.

**A tool that writes a run directory should make the ephemeral path the default,
and cleanup belongs on the success path.** Put the run in a private temp tree
(`tempfile.mkdtemp`), print the verdict and write any requested report/SARIF
**before** removing it, and remove it on failure as well as success. `--keep DIR`
copies the run there first; if the copy fails, leave the evidence in place and
print its path rather than deleting the only copy. Record `ephemeral: true` in the
result so a reader knows the run directory is gone by design.

**Preflight the output destination before the private tree exists.** A `--keep`
or `--sarif` parent that cannot be written is a start failure; discovering it
after the model call leaves a tree with no reader. Validate the parent, the
regular-file/directory shape and writability before `mkdtemp`; if a late report
write still fails, remove the tree in the same failure path.

Sandbox recipe and the NixOS/non-NixOS matrix: `references/sandboxing.md`.

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
  each target is gone. **A materialised container rootfs is the same shape at a larger
  scale**: every store path in it is mode 0444, so `rm -rf` on a 2.5 GB copy emits one
  `Permission denied` per file — megabytes of output in a single tool result — and deletes
  nothing. `chmod -R u+w <tree> && rm -rf <tree> 2>/dev/null`, then assert the path is gone;
  the noise is not evidence of progress and reading it costs more than the cleanup.
- **Inventory the home caches by SIZE before sweeping by name.** One directory can be most of
  the disk while the file count says nothing: a sandbox whose overlay upper lived under
  `~/.cache` produced 17 directories × 5 GB (84 GB) invisible to any name-based sweep. Start
  with `du -sh ~/.cache/* | sort -h | tail`, then delete. Prevent the next one at the source —
  an overlay upper belongs on tmpfs, never in `$HOME`.
- **Root-owned files inside a user cache need a sudo second pass.** A tree copied by a
  sandbox or a root-run build keeps the original ownership, so `rm -rf` prints one
  `Permission denied` per file and removes none of them, and `chmod` cannot help because you
  are not the owner. Run the user pass, then `sudo rm -rf` what is left, then assert the path
  is gone rather than trusting the exit code.
- **A `nix develop` / `nix-shell` directory is a mount point, not a directory.** `rm -rf`
  leaves it or fails; unmount first (`sudo umount -l <dir>`), then remove. When a deletion
  needs an approval that does not arrive, stop and name the leftovers in the report — do not
  reach the same outcome by another command.
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
  and list them as kept. A run kept via `--keep` is a record; an unkept ephemeral run is
  not.

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
- **Deleting the run directory before the verdict is printed or the report is
  written.** The output is the product; remove the tree only after stdout, SARIF
  and any kept copy are complete.
- **Cleaning up only on success.** A failed run leaves the same debris; put the
  removal in a `finally`/cleanup path that also runs on the error return.
- **A failed `--keep` copy followed by deletion.** If the copy raises, keep the
  source and print its path; deleting it turns a copy failure into evidence loss.
- **A sandbox that hides `/tmp` also hides the prompt and the binary.** Rebind
  both read-only after `--tmpfs /tmp`; otherwise the child starts with `ENOENT`
  on a file that exists on the host.
- **Kill the process group, not just the parent.** A wrapper's child can inherit
  the pipe and keep a stream open after the parent dies; start the child in its
  own session and kill the group.

## Verification

- The sweep printed: N removed, and the kept-list with reasons.
- `/tmp` shows only system leftovers (plus anything named as kept).
- The environment still works — cleanup is proven by the environment, not by a
  command exiting zero.
