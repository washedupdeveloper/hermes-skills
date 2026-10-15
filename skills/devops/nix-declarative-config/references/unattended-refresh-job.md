# Unattended refresh job — design rules

Depth behind the `Keeping the provisioned source current` section. Read before writing or changing an unattended job that advances `flake.lock` for branch-tracked inputs (the flake input refresh is the reference implementation).

## One job, a list of inputs

Generalise over a list rather than writing one job per input. Structure that works:

- A `for input in $inputs` loop, one section of the report per input, and a `continue` on every failure so one bad input does not hide the rest.
- **Snapshot and restore the lock *per input*.** A whole-lock snapshot restored on any failure discards the other inputs' good updates. `cp "$lock" "$state/flake.lock.$input.before"` before that input's update, restore only on its own failure.
- Aggregate `moved` / `failed` flags, then write **one** report with a header and a closing verdict. A per-input report file makes the no-op case ambiguous.
- Clean up the scratch files (`sections`, `.section.*`, `*.before`) at the end; leave only the report. Verified: the state dir holds `report.md` and nothing else after a run.
- Verification is per input, because the right check depends on what the input feeds. A self-contained artifact (`.#caveman-skills`) can be *built*; an input that feeds the machine configuration should be *evaluated* (`nix eval --raw .#nixosConfigurations.<host>.config.system.build.toplevel.drvPath`). Evaluation catches the renamed and removed options a branch bump actually breaks, at a fraction of the cost. **Say in the report which was done** -- an eval check does not catch a build failure, and implying otherwise is worse than the gap.

## Update semantics

- Tracking the branch means no `rev` in the input and `nix flake update <input>` to move it. Before promising an update path, check what the repo actually publishes (`tags`, `releases`): a repo whose releases are only binary artifacts has no artifact release to follow, so the branch is the only track.
- **An unattended refresh must record what it did, not run silently.** These are prompt documents that steer the agent's behaviour, and an external search path is not an install path, so nothing scans their contents; a silent auto-update lets upstream rewrite the agent's instructions unreviewed. Write the report on **every run that reaches a verdict, including the no-op path** — a job that writes one only when something changed is indistinguishable from a job that never ran, and "already current" is the common case, not the exception. The *notification* can stay change-only; the *report* cannot.
- The report must name the exact next action (`run \`nh os switch\``), because the job deliberately does not activate. A report that only says what changed leaves the user to infer whether they are already running it.

## Lock safety — the job must be strictly non-regressing

- An unattended job that advances `flake.lock` must **snapshot the lock and restore it when the new revision does not build**. Nobody is watching the job, so leaving a bad upstream revision locked turns one failed build into a broken `nh os switch` days later.
- Guard the **lock update** as well as the build. `nix flake update` fails on its own (a renamed or removed input, an unfetchable ref) and can leave `flake.lock` half-written; restore the snapshot on that path too, or the next switch breaks for a reason the job never reported.
- Only the *new* build is fatal. Any step whose failure is merely informative — building the previous revision to diff against, which may have been garbage-collected — must be written `$(cmd 2>/dev/null || true)` with its consumer guarded by `[ -n "$x" ]`. Under `set -e` a bare `$(cmd)` aborts the whole job over a failure that does not matter, and the refresh silently never happens.
- Read the old revision with `jq -r '.nodes.<input>.locked.rev // empty'`. The `// empty` matters on the first run, before any switch has locked the input: plain `jq -r` prints the literal string `null`, and the change detection then reports a bogus revision.

## Environment and diagnostics

- Pin the job's `PATH` with `lib.makeBinPath [ … ]` and `set -euo pipefail`. A systemd unit gets no login shell, so `nix`, `git`, `jq`, `diff` and `comm` are absent unless declared.
- Capture the output of any command whose failure the report explains: `if ! log=$(nix flake update <input> 2>&1); then …`. A report that names the failing step without its stderr sends the reader to the journal for the one line you already had in hand.
- An empty state directory is the diagnostic signature to hand the user: which files exist there tells you which line the job died on. A lone lock snapshot with no report means the run reached the backup and then took one of the silent exits — name that, and check the unit's journal before guessing at the cause.

## Interaction with home-manager and direnv

- Keep the refresh job and home-manager from fighting over the same symlink: either home-manager owns it and you refresh by rebuilding, or the timer owns the pointer and home-manager owns only the parent directory.
- `direnv` has **no exit hook**. Never design a toggle around cleaning up on `cd` out — export a variable instead and let the now-missing path be skipped.

## Testing it

Do not settle for `bash -n` on a body extracted with a regex. The Nix `''` string
still contains interpolations at that point (`export PATH=${ lib.makeBinPath [...] }`,
`${username}`), and a partially-substituted body **can pass `bash -n` while being
nonsense**. Build the real script and test that:

```console
nix build --impure --print-out-paths --expr \
  'let f = builtins.getFlake "/path/to/repo";
       pkgs = f.inputs.nixpkgs.legacyPackages.x86_64-linux;
   in pkgs.callPackage /path/to/repo/modules/<job>.nix { username = "you"; }'
```

Then `sed` the absolute paths (`flake=`, `state=`, the `PATH` export) to a temp
dir and drive the branch matrix against stub binaries: normal, upstream
unchanged, update fails, new revision fails verification, previous revision
unbuildable, input absent from the lock. Assert on the **lock contents after
each run**, not just the report -- per-input rollback is the whole point and a
report alone will not show it. A stub returning a store path that does not exist
is a useful accident: it exercises the `[ -d "$old_out" ]` guard.

## Backticks in generated shell

Two separate traps, both silent:

- In a Nix `''` string, `\`` is a **literal backslash followed by a backtick**, not an escape. An "escaped" backtick reaches the output as `` \` `` -- visible in a generated report as `\`value\``. Use a plain backtick.
- In shell, a backtick inside a **double-quoted** string is command-substituted. Put the format string in single quotes and pass values as arguments: `printf -- '- upstream: `%s`\n' "$old"`, never `echo "... `$x` ..."`.

Check both mechanically before committing: `grep -n '\\`'` and `grep -nE '"[^"]*`'` over the job file must both come back empty.
