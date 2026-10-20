---
name: nixos-clan-flake
description: "Use when working on a NixOS/Clan flake over WSL."
version: 1.13.0
author: user, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
category: software-development
metadata:
  hermes:
    tags: [nix, nixos, clan, flake, wsl, verification, reproducibility]
    related_skills: [systematic-debugging, requesting-code-review]
---

# nixos-clan-flake

Maintaining a NixOS + Clan.lol flake whose repository lives inside a WSL2 distro
while Hermes runs on the Windows host. Covers reaching the repo, editing it, and
the part that decides whether the work is done: proving the change with the repo's
own gates.

**This skill owns the WSL boundary and the FOD-hash rules.** Other skills point
here rather than restating them.

## When to Use

- A Nix/NixOS/Clan flake needs a change, a fix, or a verdict.
- Any task on a repo reachable only through WSL (`//wsl.localhost/...`).
- Applying a review's findings to a Nix repo and re-running the review.
- Anything touching `clan.core.vars`, a `fetchurl` pin, or host keys.

## Rules (always on)

**An untracked file does not exist to Nix.** Nix copies only git-visible paths —
tracked plus staged — into the store, so an untracked file is **absent** from every
build, eval, check, devshell and sync. Not stale: *missing*. A new module, a new
`SOUL.md`, a new skill, a new fixture — none of it reaches the build, and nothing
errors. The symptom is always "my change had no effect", which reads as a logic bug
and is not one. Applies to `nix build`, `nix eval`, `nix flake check`, `nix develop`,
`nh os switch`, direnv, and anything that reads a flake's store copy — an installer
or sync script then ships the OLD tree while the new file appears nowhere.

Two corollaries that catch people:

- **A file inside an already-tracked directory is still invisible.** Only the
  *file* is tracked or not; the directory being known buys nothing.
- **Only a local path inside a git work tree behaves this way.** Point Nix at a
  directory that is not a repo and it copies everything, untracked included — so the
  same tree can build differently in two checkouts for this reason alone.

`git add <path>` before any build or sync whose output you intend to inspect. Never
`git add -N` — see the rule below, where that is worse than doing nothing.

**There is no nix on the Windows host.** Every `nix`, `statix`, `deadnix`,
`nixfmt`, `treefmt`, `clan` and `git` command runs inside the distro. Confirm the
distro first (`wsl.exe -l -v`), then drive it:

```bash
wsl.exe -d <distro> -- /bin/bash /mnt/c/<scratch>/probe.sh
```

Write the script into the Windows scratch dir and run it by path. Do **not** use
`-- /bin/bash -c '...'` for anything non-trivial: the distro's default login shell
(fish, in this fleet) receives multi-line arguments and `${...}` and mangles them.
A script file has no quoting to lose. Probe with `command -v` before assuming an
interpreter exists — `python3` is often absent where `perl` is present.

**Translate Windows paths to `/mnt/...` yourself; `cygpath` will not.** Under
MSYS/git-bash, `cygpath -u 'C:/Users/x'` returns `C:/Users/x` **unchanged** — it
only rewrites the MSYS `/c/Users/x` form. An unconverted `C:/…` handed to a program
inside the distro resolves to nothing (or to a literal `C:` directory), and the
failure is silent. Convert explicitly before passing anything across:

```sh
# C:/Users/x  ->  /mnt/c/Users/x
drive=$(printf '%s' "$p" | cut -c1 | tr 'A-Z' 'a-z')
rest=$(printf '%s' "$p" | cut -c3-)
wsl_path="/mnt/$drive/$rest"
```

**A login shell can fail *after* your script has succeeded.** `bash -lc` sources
`/etc/bash_logout` on exit, which on NixOS references `__ETC_BASHLOGOUT_SOURCED`
unset. Any `set -u` in the script then kills the shell at exit with a non-zero
status — after every command has already run and printed its output. It reads
exactly like a toolchain failure and is not one. Run the script with a non-login
`bash` (or drop `set -u`) and the false failure disappears.

**One unbuildable tool fails the whole toolchain.** A `symlinkJoin`, or any list of
packages, fails entirely if one member fails — a `pythonRuntimeDepsCheck` mismatch
on a pinned nixpkgs takes every other tool down with it, and the error names only
the join, not the culprit. When a tool will not build on your pin, **remove it from
the list and record why**. An absent analyzer lowers a coverage score; a broken one
blocks everything.

**A tool that BUILDS can still be unable to RUN — exercise it, do not assume it.**
`nix build` proves the derivation, not that the program works. Measured on a pinned
nixpkgs: `pip-audit` builds cleanly and its wrapper then execs
`sys.executable -m pip --version` under an interpreter that ships **no pip**, so the
scanner sat on `PATH` and could not execute a single audit. Adding `ps.pip` to the
toolchain's `withPackages` env fixed the *import* and not the *wrapper*, because the
wrapper runs under a different interpreter — chasing the closure by hand
(`PYTHONPATH=$toolchain/lib/pythonX.Y/site-packages …`) only moves the
`ModuleNotFoundError` to the next dependency in a store path you did not guess.
Check every pinned tool with `--version` or a trivial real invocation before trusting
it, and prefer a **statically-linked single binary** over a scripted wrapper when one
exists: `osv-scanner` does the same dependency-CVE job for PyPI, npm, cargo, Go,
Ruby and Composer with no runtime dependency of its own to get wrong.

**Prove a pinned toolchain is deterministic by store path, not by inspection.**
Build the same flake from two different directories
(`nix build .#<attr> --print-out-paths --no-link`) and compare. An identical
`/nix/store/...` path proves the lock file pins the whole set; a differing one means
something outside the lock is leaking in. Run this before claiming "same toolchain
everywhere".

**A store path is an identity, not a copy of the repository — never answer a question
about it by diffing its contents.** Two ways that misleads, both measured: a packaging
derivation is not a transcription of the tree, so a legitimate output may simply omit a
file the repo has (a "framework" tree that ships no `flake.nix`), and `diff` then reports
a packaging decision as drift; and `cmp -s A B` returns non-zero for a **missing** file
exactly as for a differing one, so "DIFFERS" from that command proves neither. Resolve it
the way Nix does — `nix build --no-link --print-out-paths '.#<attr>'` and compare the
path to the one you hold. When a consumer records a store path and you need to know which
source produced it, build the candidate attributes: `.#framework` and `.#dev-framework`
are different trees, and the right one is the tree whose content the consumer needs, not
the attribute whose name sounds like the product.

**A background process does not survive a WSL invocation — start the daemon and
use it in the SAME script.** `nohup dockerd &` followed by the shell exiting leaves
no daemon and often no log: the session teardown takes the process with it, so the
next `wsl.exe` call finds nothing and the log is empty. Write one script that starts
the daemon, waits for its socket, does the work, and kills it, then run that single
script. This is also why `wsl.exe -d <distro> -u root -- <script>` is the escape
hatch for anything privileged: on a distro where `sudo` is not setuid it cannot
work at all (`must be owned by uid 0 and have the setuid bit set`), and a password
would not help.

**Verify a container image as a uid that is NOT the one it ships with.** An image
that runs as uid 1000 passes every test when you run it as uid 1000, and three
separate things break for anyone else — all three found this way, in one pass:

- **The mounted tree is not writable.** The repo belongs to the caller's uid, so the
  run cannot create its output directory and dies with `PermissionError`. The fix is
  `--user "$(id -u):$(id -g)"`; the image must ALSO make its own home and workdir
  writable by that uid, or the flag only half-works.
- **The uid has no `/etc/passwd` entry, and `nix` resolves `$HOME` through
  `getpwuid`.** `nix eval` then fails with `cannot determine user's home directory`
  **even when `HOME` is set** — so every nix-backed probe degrades and the coverage
  score silently drops. Have the entrypoint append an entry for the runtime uid
  (make `/etc/passwd` writable in the image; it is disposable).
- **`/tmp` may not exist at all.** `tempfile.mkdtemp()` searches
  `['/tmp', '/var/tmp', '/usr/tmp', cwd]`, so without it scratch lands in the
  working directory — i.e. in the repository under review — and on a read-only
  mount the tools that need scratch fail outright. `mkdir -p tmp && chmod 1777 tmp`.

The tell for all three is that the deterministic half is supposed to be
uid-independent: run the same probe set as two uids and compare the signals. They
matched exactly once fixed, which is what proves it.

**A base image's toolset is not a contract — check every tool a `RUN` uses.** A
Dockerfile whose last step piped through `sed` passed review and died at
`[builder N/N]` with `/bin/sh: line 1: sed: command not found`: the `nixos/nix` image
ships no `sed` and no `awk`, and its `/bin` holds only `sh`. Nothing before it could
catch that, because a Dockerfile only *parses* until it runs — "the Dockerfile is
valid" is a different claim from "the image builds", and only the second one matters.
Enumerate what the base actually has
(`docker run --rm <img> sh -c 'for t in sed grep tar find readlink …; do command -v $t || echo MISS-$t; done'`)
and take the rest from nixpkgs, so the step depends on the pin rather than on a base
image's incidental contents. `nixos/nix` was measured to have `bash cat chmod cp cut
find grep head ls mkdir mv nix nix-store readlink rm sh sort tail tar wc xargs`, and
to lack `awk` and `sed`.

**A NixOS test VM has no network because the NIX BUILD SANDBOX has none.** A
`runNixOSTest` guest's QEMU gateway is inert by default, so anything needing DNS or
TCP fails as though the VM were misconfigured. It is one flag away: `nix build …
--option sandbox false` gives the guest real internet (measured: DNS resolves, TCP
`1.1.1.1:443` OPEN, HTTPS 200), while `--option sandbox relaxed` does **not** — that
relaxes the filesystem, not the network. This is also why a guest cannot reach a
service on the host: `127.0.0.1` in a guest is the guest, and the host is only at
`10.0.2.2`, and only with the sandbox off.

**A NixOS test VM is ephemeral; the host-side half of the test is not.** A finished
`runNixOSTest`, or any container-image experiment, leaves host state behind that
nothing cleans up:

- **The directory you invoked the build from**, because `nix build` writes
  `result -> /nix/store/…` into the *current* working directory. One throwaway flake
  per probe means one throwaway directory per probe, and they accumulate silently.
- **That `result` symlink is a live GC root**
  (`/nix/var/nix/gcroots/auto/<hash> -> <dir>/result`), so it pins the whole test
  closure against `nix store gc` until the directory is gone. Delete `result`
  *before* the directory, or the root dangles and the store stays pinned.
- **Host users and their state** — `useradd`, a home, `/srv` directories,
  `subuid`/`subgid` ranges. These are host state, not a guest escape, so attribute
  them by reading `journalctl | grep -E 'useradd|groupadd'` rather than assuming the
  test leaked. **How long they survive is decided by `users.mutableUsers`, and the
  two cases are indistinguishable until the next activation:**
  - `mutableUsers = true` (nixpkgs' default) — activation only *adds* declared
    users, so an imperatively-created account persists indefinitely.
  - `mutableUsers = false` — activation rewrites `/etc/passwd` from the declarative
    set and **prunes undeclared users**. A stray account therefore vanishes on the
    next `nixos-rebuild switch`, and a later `userdel` reports `user 'X' does not
    exist` while `/home/X` is still on disk under a now-nameless uid. Delete the
    orphaned home yourself — `userdel -r` never ran.

  Read the flake before predicting persistence (`grep -rn mutableUsers <flake>`); a
  switch is the empirical test. Do not report "nothing reconciles users" from the
  nixpkgs default alone — a flake that sets it false makes that claim false.

Also check `/tmp` for unpacked image rootfs trees: extracting a container tarball to
inspect it is cheap, forgetting it is not, and a handful of 1–3 GB trees will dwarf
the test directories themselves (`du -sh /tmp/* | sort -rh | head -25`). Unpack
image tarballs into a scratch dir you delete, never into `/tmp` root.

**Those trees are read-only, so `rm -rf` as the invoking user fails — and fails
loudly.** An extracted rootfs carries the Nix store's modes (`444` files inside `555`
directories), so a plain `rm -rf` emits one `Permission denied` line per file: a
16-tree cleanup produced **80 MB of output** and removed only the trees whose modes
happened to be writable. Run it as `sudo rm -rf <trees> 2>/dev/null` and verify by
re-checking each path (`[ -e "$d" ]`), never by trusting the exit code. Expect the
same for anything extracted out of a store path or a container layer.

Audit, preserve anything unique, then reclaim: `references/host-side-leakage-and-reclamation.md`.

**`ls -d /nix/store/*-<name>.drv | tail -1` is alphabetical, not newest.** It will
happily return an older derivation from a previous run, so `nix log` shows you a
stale failure and you report it as current — with two runs of the same test name in
the store, the two verdicts can be opposite. Sort by time (`ls -t … | head -1`) or
enumerate every match and read each one's verdict. The same class of trap:
`builtins.toString /some/path` returns the path **unchanged** rather than copying it
into the store, so it cannot be used to inspect what a build would actually see.

**`patch`/`write_file` cannot write to a `//wsl.localhost/...` path.** Stage the new
file in the scratch dir and copy it in, stripping CR:

```sh
tr -d '\r' < /mnt/c/<scratch>/new-file.nix > /home/<user>/<repo>/<path>
```

`scripts/install-into-wsl.sh` does this with before/after hashes.

**When the user says they cannot move files across the boundary, do the copy
agent-side.** Do not hand them a path and a `cp` to run — that is work you can do
from inside the distro. Check the modes first (`find <dir> -type f ! -perm -004`): if
everything is world-readable the blocker is *not* Unix permissions, so the copy is
simply one you have not performed yet — `sudo cp -a <src> <dst> && sudo chown -R
<user>:users <dst>`, then verify with a per-file hash comparison. To hand content
across the Windows/WSL boundary, write a tarball under `$HOME` and deliver it as
`MEDIA:<path>`, which the desktop surfaces as a download; verify it with `gzip -t`
plus an extract-and-compare roundtrip, and report its sha256.

**A tar-sync from the Windows mount carries its file modes, and git may record them.**
Copying a tree out of `/mnt/c/...` with `tar` preserves that filesystem's modes, which
are uniformly permissive, so every file in the destination arrives `755`. In a repo with
`core.fileMode true` git then records spurious `100644 => 100755` changes — three
`SKILL.md` files became executable this way and the change was committed. Two rules:

- After any such sync, restore modes from the index:
  `git ls-files -s | while read m _ _ f; do chmod "${m#100}" "$f"; done` — but note this
  is a no-op when the index is already wrong, so correct the index instead.
- **`chmod` the FILE before staging.** `git update-index --chmod=-x` alone is undone by
  the next `git add -A`, which re-reads the working tree; the sequence has to be
  `chmod 644 <file>` then `git add <file>`.
- A repo with `core.fileMode false` is immune, which is why the same sync left one repo
  clean and the other dirty.

**Check line endings with a binary read, never with `grep`.** `grep -c $'\r' file`
reported *every* line as CRLF (155/155, 219/219) in this fleet's bash — the `$'\r'`
did not survive into `grep`, so it matched nearly anything. That nearly produced a
confidently reported "this repo is CRLF" on a repo whose committed blobs were LF-only
all along, which would have sent someone off to re-normalise 77 clean files. Read the
bytes instead, and check the **committed blob** rather than the working tree, because
`.gitattributes` (`* text=auto eol=lf`) hides a CRLF working tree from `git status`:

```bash
python3 -c "print(b'\r\n' in open('f','rb').read())"
git cat-file blob HEAD:path/to/f | od -c | head -3   # the blob, unfiltered
```

`awk length()` is the same class of trap from the other direction: it counts UTF-8
**bytes**, so box-drawing and accented characters inflate the count. An alignment
check on an ASCII-art diagram built with it is meaningless — use a real character
count (`python3 -c "print(len(line))"`).

**Copying a file from a Windows checkout into the distro can bring CRLF with it.**
A repo with `core.autocrlf=true` on the Windows side materialises **CRLF** working
files even when every committed blob is LF, so `cp /mnt/c/...` into the distro drags
CRLF in — and `git status` stays clean, because `eol=lf` normalises both sides when
it compares them. `git checkout -- <path>` will **not** fix it (git sees no change);
strip the CRs yourself. Check `git config --get core.autocrlf` per repo: it differs
between checkouts of the same fleet.

**Edit text inside the distro with an assertion-checked script, not `sed`.** A silent
no-match is the failure mode of an in-place edit. Write a `perl`/`python` script that
replaces an exact multi-line block and dies unless the match count is exactly 1, then
run it. Same for bulk doc edits.

**A comment-only edit is provable, not assertable — hash the parse tree.**
`nix-instantiate --parse <file> | sha256sum` before and after; comments vanish in the
AST, so an identical hash across every touched file is the evidence that no code
moved. Do this instead of eyeballing a diff, and report the hashes rather than the
claim. A bulk comment pass is the one edit where "I only changed comments" is easy to
say and cheap to prove.

**A comment inside `''` is NOT a comment — it is the string's content.** In an
indented string it is shell/Python source, so editing it changes the derivation; and
inside a `clan.core.vars.generators` script it can change the generator's inputs and
**rotate a secret**. Grep for `''` before trimming comments in any file that has one.
The AST hash is what catches this: the file whose hash moves when you believed you
touched only comments is the file with a string in it.

**The gate is `nix flake check --keep-going`, and only that.** `--no-build` only
evaluates and will report `all checks passed!` while the real gate is red — that is
exactly how a red gate stayed hidden behind a green summary. **It fails in the other
direction too, and that one is newer:** a machine's secret is a store path, and
evaluating a consumer calls `pathExists` on it, so `--no-build` refuses to realise it
and the evaluation dies with `error: path '<...>-per-machine-<machine>-<generator>_key'
is not valid` while the real gate passes. Use it only on something with no secrets in
it. And to build the leg that is not the current system: `--all-systems`. Then build:

```bash
nix build --no-link --print-out-paths '.#nixosConfigurations.<machine>.config.system.build.toplevel'
```

**Prove the specific change with `nix eval`, not with the diff.** Read back the option
you edited and show the value moved — the host-key list, the listener's credential
field, a filtered `systemPackages`. A green build does not prove an option took
effect; a concatenating list option in particular keeps the old value while looking
edited.

**A rendered `/etc/nix/nix.conf` lists DEFAULTS, so "who set this" is a question for
the module, not for the file.** The NixOS nix module renders `cfg.settings` and every
declared option carries a default, so `sandbox = true`, `require-sigs = true`,
`max-jobs = auto` and `cores = 0` appear whether or not anyone asked for them. A
review that reads them as local decisions invents findings and proposes "removals"
that change nothing. Two of them get misread in opposite directions:

- **`cores` defaults to `0` in BOTH layers, and `0` is the sentinel for "use all
  cores"** — the builder receives `NIX_BUILD_CORES=nproc`. `cores = 1` is therefore
  not a guardrail but a downgrade, forcing every `enableParallelBuilding` derivation
  (cargo, `make -j`, gcc) onto one thread; the conservative-looking number is the
  throttling one. Specifying `cores` at all is a no-op.
- **`max-jobs` defaults to `"auto"` in the module but `1` in bare nix.conf.** So
  "delete the setting and builds serialize" is true of Nix and false of NixOS. Both
  statements are correct about different layers, and only the module one governs a
  NixOS host.

Read the module's `mkOption … default` before overriding, and prove a default is in
force by **evaluating the config with the block removed**
(`nix eval --json .#nixosConfigurations.<m>.config.nix.settings`) rather than by
reasoning from the upstream manual — the manual documents the daemon default, not
the module's. Same rule as the firewall: the option's value is not evidence about
what the machine does.

**Run `nixfmt` on every file you touched** (via the devshell). The pre-commit hooks
run on commit and will reformat or fail; a green commit is extra evidence, not a
substitute for the gate. Markdown is gated too, and the two rules that bite are
mechanical: a `$` prompt inside a ```console fence fails markdownlint's MD014
(commands must be shown with their output), and a table whose separator row is
`|---|` fails MD060 -- write bare commands and `| --- | --- |`. A third rule bites on every document written in a
single call: **MD047** wants exactly one trailing newline, which `write_file` does not add —
`printf '\n' >> <file>` is part of finishing a document, not polish.

**Nix needs new files git-tracked — but never stage them with `git add -N`.** Nix
cannot see an untracked path, and its error message tells you to run `git add -N`;
that records the path in the index with an **empty** blob. pre-commit's
`staged_files_only` hides unstaged changes so hooks read the index alone, so those
paths are empty when statix/nil read them (`Unexpected end of file`), and the hook's
own rollback then conflicts — `already exists in working directory` — leaving the
files **empty** and discarding the unstaged worktree changes with them. Stage for
real (`git add <path>`): it satisfies Nix identically and leaves no empty blob.

**Recover that rollback from pre-commit's own patch, not from git.** When the
rollback fails, the stash it tried to re-apply is still at
`~/.cache/pre-commit/patch<epoch>-<pid>` (named in `pre-commit.log` and in the error)
and holds the complete lost diff. Copy it out first, then `git reset`, delete the
emptied 0-byte files, and `git apply` it. Never reach for `git reset --hard` or
`git checkout -- .`: the damage is to *unstaged* changes, which those destroy.

**Once the gate has run on the exact content, commit with `--no-verify`.**
`pre-commit run --all-files` with everything staged (nothing unstaged, so nothing to
stash) exercises every hook safely; the per-commit stash/restore dance adds risk and
no evidence. The hook CLI is not on the devshell PATH — invoke `.git/hooks/pre-commit`,
which carries its store path.

**Judge the code against the repo's own ADRs.** Read `docs/adr/` first. When code and
an ADR disagree, one of them is wrong — decide which, fix that one, and do not leave
both standing or "fix" code to match an ADR that describes the old shape.

**Removing `accept-flake-config` makes nix prompt — or warn, depending on the TTY.**
With it false (nix's default), a flake's `nixConfig` is not applied without consent,
and nix chooses between two shapes on one condition: **if stdin is a TTY it prompts**
(`do you want to allow configuration setting '…' … (y/N)?`, then `permanently mark
this value as trusted`), **otherwise it prints `warning: ignoring untrusted flake
configuration setting '…'` and continues.** Prove it with the same command twice —
`script -qec "nix eval …" /dev/null` versus `nix eval … < /dev/null`. This matters
because `nh` runs `nix build` as a subprocess with piped stdio, so an `nh os switch`
shows the *warnings* while a direct interactive `nix` command shows the *prompts*,
and the two look like different problems when they are one.

Answers are recorded per user in `<data dir>/nix/trusted-settings.json`
(`$XDG_DATA_HOME`, else `$HOME/.local/share/nix/`) — **not** in the config dir. When
`nh` elevates, the file lands under **root's** home, so the invoking user still has
none and keeps being asked. It stores the exact values approved, so it is narrower
than `accept-flake-config = true`: a different flake asking for different
substituters still prompts.

**direnv turns this into an apparent freeze.** `nix-direnv`'s `use_flake` runs
`nix print-dev-env --profile … "$@"` from the shell's `cd` hook, so the y/N prompt
lands mid-`cd` where it reads as a hang — direnv itself prints "is taking a while
to execute. Use CTRL-C to give up." The prompt *is* answerable (typing `y` + Enter,
six times for three settings) but users reasonably read it as wedged, and `Ctrl-C`
abandons the load. Two fixes: the caller's `trusted-settings.json` above, or
`use flake . --accept-flake-config` in `.envrc` (nix-direnv forwards the flag) —
prefer the trust file when the repo documents that accepting a flake's config is a
caller's trust decision, since a committed `.envrc` decides for everyone.

Silencing the warnings for one invocation is
`nh os switch .#<machine> -- --accept-flake-config` (nh forwards `EXTRA_ARGS` to
`nix build`); verify by counting warnings with and without it.

Before treating these warnings as a problem, check whether they matter: on a
machine where the system `nix.conf` already sets the same substituters, keys and
experimental features, ignoring the flake's `nixConfig` changes nothing —
`nix config show experimental-features` and `nix config show substituters` show what
is actually ambient. The `nixConfig` is usually there for *other* evaluators.

**`networking.firewall.*` is inert on a WSL guest — never file a port finding from
the config.** nixos-wsl sets `systemd.services.firewall.enable = false` at normal
priority (`modules/systemd/default.nix`: "Disable systemd units that don't make
sense on WSL"), for every machine with `wsl.enable`. `networking.firewall.enable`
still reads `true` — it is only nixpkgs' default — so a config-shaped review reports
ports as firewalled when nothing filters at all. Check the runtime, not the option:
`systemctl is-active firewall.service` (masked, with the unit path ending
`-unit-firewall.service-disabled`) and list the ruleset with `nft` from its store
path (`nix build --no-link --print-out-paths nixpkgs#nftables`); a guest's ruleset
carries only WSL's own `WSLOUTPUT` / `WSLPOSTROUTING` chains. Writing a narrower rule
is still worthwhile — it documents intent and is correct the moment the firewall is
enabled — but say plainly that it does nothing today, or the next reader trusts it.
Turning it on for real takes `lib.mkForce true`, which overrides an upstream decision
and can cost the guest its networking: that is the owner's call, not a fix to apply.

**Do not test guest reachability from the Windows host.** Under
`networkingMode=mirrored` the guest shares the host's addresses, so a host → host-IP
connection hits the *host's* stack and reports "closed" even for a port that is
listening in the guest — port 22 included. Only a third device on the LAN, or a
connection from inside the guest, says anything. Otherwise report the exposure as
unverified rather than as closed.

**Never trust a reported hash mismatch until you check the derivation.** See
`references/fetchurl-hash-modes.md`. A `recursive` `outputHashMode` pins a NAR hash
(mode bits included) and cannot be compared against a content hash. This is the most
expensive trap in this domain: it has produced a confidently reported false positive,
a wrong "fix" that broke the build, and a review that signed off on both.

**Never print a secret.** `clan vars get` writes plaintext to stdout. Give the user
the command; do not run it. Same for anything that would paste a credential, key, or
hash into the conversation.

**When you need to PROVE decryption works, prove it without the value — this is the
moment the rule gets broken.** "Does the store actually decrypt?" is a real question with
a real answer, and reaching for `clan vars get` to answer it is the natural move; that is
how a broker password ends up in a transcript. Every property worth knowing is checkable
from the shape of the output, never its content — a byte count, a marker count, and the
**derived public key** (`age-keygen -y`), which is not sensitive and either matches the
recipient you expected or does not.

The runnable block, the shell traps that make it safe (a `set -e` rule that does not
behave the way it reads, the `trap` that is the only cleanup, and what `shred` does not
guarantee), and the escrow step that decrypts: `references/sops-store-coherence.md`.
If no property answers the question, say the property is unverified rather than spending a
secret on it — and if one does escape, tell the user in the same reply and treat it as
disclosed, because it is.

**Verifying that a clan/sops secret store is wired the RIGHT way is its own audit** —
symlink markers, recipient↔key agreement, the orphaned-escrow check that catches a
recovery path which recovers nothing, and the at-rest boundary it does not cover — a
machine's age key is a plaintext file on that machine's disk, so disk encryption is a
separate decision: `references/sops-store-coherence.md`.

**Confirm scope before a consequential change.** Rotating a credential, changing a
host key, or deleting state has an operational tail: a device or a client needs to
know. Ask first, then state the follow-up in the commit body and in your reply.

**A test that cannot fail is worse than no test, and a test of something that does
not exist is fiction.** This user asks for proof, not the presence of tests, and
will push back on a suite that only demonstrates its own existence. Three
obligations follow, and they are not optional polish:

- **Prove each new assertion can fail**, by breaking the property and watching the
  matching test report, then restoring it. A suite green on its first run has
demonstrated nothing.
- **Never simulate an artifact or a consumer that does not exist.** If the product
  has no installer, there is no build tier; say so instead of building a fake one.
  A stub is acceptable only where the real thing is genuinely unavailable (network,
  a model, a second host) -- and then name what it stands in for and validate its
  contract against the real interface.
- **Name the command that runs it, and the thing that invokes that command.** A
  check can exist, pass, and be wired to nothing: an attribute deliberately outside
  `checks` (a VM test needing KVM), with no CI job naming it either, runs only when
  a human remembers the command. Before a suite is cited as proof of anything, say
  which invocation produces it on every change. A proof nobody triggers is a demo.
- **Report which mode produced the verdict.** "Checks pass" over cached results, over
  zero executions, or over a pipeline whose status is the last stage's, is not
  evidence. Say whether anything actually ran.
- **Prove a test is live by mutation, never by its derivation hash.** A `runTests`
  group that passes emits a *fixed* derivation, so `drvPath` is identical before and
  after you rewrite the assertions inside it -- measured on two different spellings
  of one group. A green gate plus an unchanged hash therefore says nothing about
  whether the test still tests anything.
- **Prove a comment-only rewrite with the AST.** `nix-instantiate --parse <file> |
  sha256sum` drops comments but keeps code, so an identical hash proves the code did
  not move -- the claim a reviewer cannot check by reading a 500-line comment diff.
  Hash every file first, rewrite, hash again, diff the lists. The general rule and the
  order to cut in are in the `writing-for-agents` skill; what is specific here is the
  trap: a `#` line inside a `''` string is script content, not a comment. In a clan
  vars generator, editing one changes the generator script hash and can **rotate a
  secret**. That file's AST hash moving is how the mistake surfaces.

**Testing a clan flake.** Eval assertions (`lib.runTests`), VM tests (clan's
`clanTest`), the deployability checks, the "no undeclared ports" pair, and the
gate/git-hook wiring are in `references/testing-a-clan-flake.md`. Read it before
adding or debugging a test, or before touching `modules/flake/git-hooks.nix`. It
also carries the three-tier rule -- eval for a value, build for a rendered file, e2e
for what a running machine does -- and why Python belongs only in the last one. For
the e2e tier it has the design rules: a test double must not carry its own copy of
the system's table (or the new case becomes unrepresentable), an assertion must check
that a unit MOVED the score rather than that its file exists, `nix log` is where a
VM test's assertions are, and a unit registered in several places needs a
 two-direction agreement test.

**Adding a machine** is its own procedure with its own traps -- clan's discovery
rule, the reserved tags, the vars a machine needs before its toplevel will build at
all, and the reason a test suite has to be fleet-shaped *before* the second machine
arrives: `references/adding-machines-to-a-clan.md`.

**A machine on new hardware takes its board support as a MODULE, not as a system
builder.** Clan makes the `nixpkgs.lib.nixosSystem` call itself, so an upstream flake
whose support ships as its own system-builder helper cannot be used at that seam; the
support goes in through `clan.specialArgs.<input>` plus
`imports = [ <input>.nixosModules.<board>.base ]` in the machine, and what that module
takes from its own flake gets read rather than inferred. Reading a clan service's real
interface from the pinned store, and why an overlay's public nodes do not make an
offline machine reachable, are in the same reference.

**"What is missing to reach the milestone?" cannot be answered from the code — the target has
to exist as a document first.** Grep for it before measuring anything (`grep -rni milestone`);
with none in the tree, the deliverable is the target, defined with the owner, not a gap list
against an imagined one. One home per fact, how to interview for an undefined target, the sweep
a reversed decision requires, and why a deferral must carry its measured consequence:
`references/planning-documents.md`.

## Procedure

1. **Recon**: `wsl.exe -l -v`; then in the distro, `git log --oneline -5`,
   `git status --short`, and read `docs/adr/*` plus every file you will touch.
2. **Change** via staged files copied in (above), one concern per edit.
3. **Format** the touched files (`nixfmt`).
4. **Verify**: `nix flake check --keep-going`, then the toplevel build, then
   `nix eval` on each option you changed. Report the exit codes.
5. **Commit** in the repo's own style, with the verification results in the body and
   any operational follow-up spelled out. **Scope the commit to your own paths**
   (`git commit --no-verify --only -- <path>...`). A tree shared with another writer
   -- a background curator, a second agent, a CI job -- will have ITS work staged in
   the same index, and a bare `git commit` or a `git reset --soft` into an amend
   sweeps it in silently: measured twice in one session, once producing a commit
   whose message described 35 files while it carried 40, and once attributing an
   unrelated edit to the wrong concern. After committing, prove the scope with
   `git show --name-only --format='' HEAD` and compare it to what you intended. If a
   sweep happens, `git reset --mixed <target>`, re-stage the other writer's paths,
   and re-commit with `--only` -- never `git reset --hard`.
   **The sweep also runs the other way, and you cannot fix that one by rewriting.**
   A co-writer running `git add -A` takes *your* in-flight files into *their* commit,
   so a commit whose message describes one concern arrives carrying two -- and the
   diff looks correct, which is why nobody checks. Do not rebase or amend history
   under a process that is still committing: it interleaves its work with yours and
   the next thing you lose is real. Commit what remains with a body that names what
   was carried, and run `git log --oneline -3` before every commit so you notice the
   tree moved rather than discovering it later.
   **Never pass a commit body through `-m "..."` when it contains backticks.** The
   double quotes let the shell execute `` `...` `` as command substitution, so the
   body is replaced by that command's output: a message describing a five-file change
   became three lines of `command not found`, and the commit succeeded anyway. Write
   the body to a file and pass `-F <file>`, or use a quoted heredoc (`<<'MSG'`), then
   read it back with `git log -1 --format=%B` before pushing.
6. **Re-verify LAST, and name the snapshot -- branch included.** A verdict is a claim
   about one commit on one branch at one instant. On a tree another process can write,
   `HEAD` moves between the measurement and the report, so a green gate reported from a
   `git log` taken minutes earlier describes a tree that no longer exists. Re-run the
   gate after the final write, and state the commit and the time alongside the result.
   When a verdict turns out to be stale rather than wrong, say which commit it was true
   at instead of defending it.

   **A flake repo's long-lived `feat/*` branches are normal**, so start from `git branch -a`
   rather than the branch you were handed. Everything else about proving a merge — the
   commands, the count semantics, the clean-tree guard — is in `verify-and-stop` under
   "Name the branch, not only the commit"; do not restate it here.

## References

- `references/planning-documents.md` — the milestone/recommendations/ADR set as one plan: one
  home per fact, interviewing the owner to close an undefined target, the sweep a reversed
  decision requires, verifying every identifier against the pinned source, and what a deferral
  or a "reached" criterion has to contain.
- `references/fetchurl-hash-modes.md` — flat vs recursive FOD hashes, and how to test
  a pin correctly.
- `references/clan-vars-generators.md` — authoring a `clan.core.vars.generators`
  entry, generating it without rotating anything else, and verifying that.
- `references/sops-store-coherence.md` — is the store wired right: clan's
  symlink-marker discovery, recipient↔key agreement, the orphaned-escrow check, and
  why a missing `.sops.yaml` is correct here.
- `references/testing-a-clan-flake.md` — `lib.runTests` and clan's `clanTest`,
  the ports pair, deployability checks, and how the gate wires into git hooks.
- `references/adding-machines-to-a-clan.md` — growing a clan from one machine to
  many: clan's directory discovery, the reserved `all`/`nixos` tags, the vars store
  as a build prerequisite, fleet-shaped assertions, the deploy target, third-party
  board support at the `specialArgs` seam, and how to read a clan service's
  interface -- role options, exports, vars generator -- from the pinned store.
- `scripts/install-into-wsl.sh` — copy Windows-staged files into a WSL repo with CR
  stripped and before/after hashes.
- `references/host-side-leakage-and-reclamation.md` — auditing and reclaiming what a
  VM/container experiment left on the host: what leaks, the audit commands, the
  preserve-before-delete order, the hash-comparison normalisation trap, and the
  `nix store gc` sequence.
- `references/patching-a-package-not-in-nixpkgs.md` — adding a plugin/dependency to an
  upstream package the consumer's nixpkgs does not carry: the upstream override seam
  vs a wrapper, the seeded-pkgs trick that stops an overlay being a silent no-op, why
  the extra package must be built with the TARGET's nixpkgs, and how to verify the
  result by artifact rather than by build log.
