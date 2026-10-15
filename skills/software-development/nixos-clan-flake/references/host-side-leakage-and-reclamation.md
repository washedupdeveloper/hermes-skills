# Host-side leakage from VM and container experiments

A `runNixOSTest` guest is ephemeral. The half of the work that ran on the host is
not, and nothing in the Nix lifecycle cleans it up. This is the audit, the order of
operations, and the traps.

## What leaks

1. **The build directory.** `nix build` writes `result -> /nix/store/…` into the
   current working directory — not into the store, not into a temp dir. A probe
   per throwaway flake is a directory per throwaway flake.
2. **The `result` symlink as a live GC root**, at
   `/nix/var/nix/gcroots/auto/<hash> -> <dir>/result`. It pins the closure.
3. **Host users** created for the experiment, with their homes, `subuid`/`subgid`
   ranges, and anything they own outside `$HOME`.
4. **State directories written outside scratch** — a second application home, logs,
   bundles, run output.
5. **Unpacked rootfs trees**, usually under `/tmp`.

## Audit

```bash
# candidate leftovers in $HOME
ls -la ~ | grep -E '^d.* (rc-|tmp-|test-|probe)'

# which of them hold a live GC root
ls -la /nix/var/nix/gcroots/auto/ | grep -E 'rc-|result'

# the receipt for a stray user: name, uid, home, shell, creating process
journalctl | grep -E 'useradd|groupadd'
awk -F: '$3>=1000' /etc/passwd
id <user>; grep -n <user> /etc/subuid /etc/subgid

# what that user owns outside its own home
find / -xdev -uid <uid> 2>/dev/null | grep -v '^/home/<user>'

# the real disk cost
 du -sh /tmp/* 2>/dev/null | sort -rh | head -25; du -sh /tmp
```

`journalctl | grep useradd` is the highest-value command here: it names the uid, home,
shell and the process that created the account, which converts "where did this come
from" into a fact and rules the guest in or out immediately. Do not infer host
leakage from a guest experiment — a user created *inside* a `runNixOSTest` VM dies
with its disk image and never appears in the host's `/etc/passwd`.

## Preserve before deleting

A leaked scratch checkout can hold the only copy of something gitignored — run
output, logs, per-run state directories. Before any `rm -rf`:

1. **Diff the leaked tree against the live repo.** `git log --oneline`,
   `git merge-base --is-ancestor <leaked-HEAD> HEAD`, and per-file `sha256sum`. A
   leaked clone whose HEAD is an *ancestor* of the live HEAD is superseded, not
   lost; a *divergent* one is not.
2. **Copy anything unique out with `cp -a` as root**, then
   `sudo chown -R <user>:users <dst>` so the user can actually read it afterwards.
3. **Verify the copy, then delete the source.** Report the count and the hashes.

Confirm scope with the user before the destructive step and name explicitly what is
being kept versus removed.

**A bundle is only a safety net if it contains the commit you are protecting —
verify it, do not assume.** A directory of hand-rolled `.bundle` files from earlier in
the session reads like "the work is safe", and six of them were all **stale**: their
tips sat 1–19 commits behind the live branch, so none covered the unpushed HEAD.
Before deleting anything a bundle is meant to protect:

```bash
git rev-parse HEAD                 # what must be preserved
git bundle list-heads <bundle>     # what the bundle actually holds
git bundle verify <bundle>         # is it even a complete bundle
```

Then make a fresh one (`git bundle create <dst> --all`) somewhere durable and
re-verify its heads. Note also that a git *remote* can itself be a bundle path
(`git remote -v`): if that path is a Windows-side `C:/...` string it will not resolve
inside the distro, so an `ahead N` against it means unpushed work with no working
destination — not work that is safe elsewhere.

## The hash-comparison normalisation trap

A hash comparison across two trees is only meaningful if the paths are normalised to
the same anchor.

```bash
# WRONG — greedy .* anchors on the LAST occurrence of the name
find "$A" -type f -exec sha256sum {} \; | sed 's|.*review-council/||'
find "$B" -type f -exec sha256sum {} \; | sed 's|.*tarverify/||'

# RIGHT — strip each path to a common anchor
find "$A" -type f -exec sha256sum {} \; | sed 's| .*review-council/| |'
```

`s|.*name/||` is greedy, so two trees whose paths contain the same directory name at
different depths yield different relative paths and a diff in which *every* line
appears changed. When a diff shows all lines changed but the digests look identical,
suspect the normalisation before the content — compare the hash column alone
(`awk '{print $1}'`) to separate the two questions.

## Reclaim

```bash
rm -f <dir>/result                  # drop the GC root FIRST
rm -rf <dir>                        # then the directory
nix-store --query --roots <path>    # lists roots; also prunes stale ones as a side effect
nix-collect-garbage -d              # now the closure is actually reclaimable
```

Order matters both ways: deleting the directory without deleting `result` leaves a
dangling root with the store still pinned; deleting `result` without the directory
leaves the directory to accumulate again. Measure before and after (`du -sh`,
`nix path-info -Sh`) and report the numbers rather than asserting space was freed.

## Reclaiming the store with `nh clean`

On a host that runs `nh`, do the store/profile/generation half with it rather than by
hand — it prunes generations, gcroots and the store in one ordered pass. **Use the
keep policy the flake itself declares**; do not invent one:

```bash
grep -rn 'clean' <flake>/machines/*/configuration.nix   # e.g. clean.extraArgs
nh clean all --keep-since 7d --keep 4 --dry             # read the plan first
nh clean all --keep-since 7d --keep 4
```

`--dry` prints the plan as `OK`/`DEL` lines per gcroots and per profile, so you can
name exactly which generations go before anything is removed. `nh clean all` covers
every profile including root's; `nh clean user` is the unprivileged subset. It runs
`nix store gc` at the end (`--no-gc` to skip), so run it **after** the directories and
GC roots are gone — otherwise the closure you just unpinned is not yet collectable.

Measured on a 26 GiB store: one `nh clean all --keep-since 7d --keep 4` deleted 7857
paths and freed 16.5 GiB, taking the store to 8.3 GiB and the disk from 31 GiB to
13 GiB used. Report the store size and the disk delta, not just "cleaned".

Deleting a generation is not reversible — if a rollback story depends on an older
generation, `--keep` is the number that protects it. Confirm the policy with the owner
when the flake does not declare one.
