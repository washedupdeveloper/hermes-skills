---
name: hermes-wsl-backend
description: "Use when running Hermes or commands inside a WSL2 distro."
version: 1.3.3
author: Storm, Hermes Agent
license: MIT
platforms: [linux, windows]
category: autonomous-ai-agents
targets: [hermes]
metadata:
  hermes:
    tags: [hermes, wsl, wsl2, backend, serve, gateway, systemd, desktop, remote]
    related_skills: [hermes-profile-fleet, hermes-project-handoff, nixos-clan-flake]
writes: [none]
side_effects: [systemd, port, background-process]
---

# hermes-wsl-backend

**Heads-up.** The steps below enable a systemd **user** unit inside the distro (so it survives a shell exit), listen on a local port, and start long jobs with `setsid nohup`. All of it lives outside the project directory.

Run the Hermes **backend** inside a WSL2 distro and attach the desktop app as a
client, so agent work executes in Linux and never crosses the Windows code-integrity
surface (WDAC / Smart App Control / AppLocker). Those policies block Windows-side
process spawns — `WinError 4551`, "An Application Control policy has blocked this
file" — and cannot inspect anything inside the Linux VM, so relocating the runtime
removes the failure instead of fighting the policy. Disabling those controls is not
the fix: Smart App Control cannot be re-enabled without reinstalling Windows.

The desktop becomes a client only. Profiles, sessions, skills, memory, cron and
credentials all live in the distro.

## When to Use

- Moving the Hermes runtime into WSL2, or troubleshooting a desktop that cannot
  reach the WSL gateway.
- **Driving any command into the distro from Windows** — a build, a test run, a script that
  writes a file. The quoting and launch rules below are the ones that apply, and this is the
  case they are most often needed for: a multi-line `sh -c` string or one carrying `$?`,
  `$(…)` or a glob is re-parsed by the distro's login shell and fails as a syntax error, an
  empty variable, or a `127` naming a file that exists.
- A run dying with an Application Control / `WinError 4551` block on a spawn.
- The gateway is unreachable after a reboot, or after a few minutes idle — or
  while the distro is running and the service reports `active` (check the
  local-delivery rule under Rules before touching the backend).
- Deciding whether a profile, credential, skill or repo copy belongs on the Windows
  side or in the distro.

## Topology

```
Windows: desktop app (client)  ──http/ws──▶  127.0.0.1:9119
                                                │
WSL2:   hermes serve  ◀── systemd user unit hermes-serve.service
        ~/.hermes/{profiles,skills,memories,cron,config.yaml}
```

## Rules (always on)

**WSL2 terminates the distro when the last `wsl.exe` session ends.** `loginctl
enable-linger` keeps the *service* alive across sessions but does **not** keep the
*distro* running — nothing on the Linux side can. A Windows-side session must be
held open, or the gateway vanishes within seconds of going idle. This is the most
likely reason a "durable" gateway is unreachable, and it is invisible from inside
the guest: the service reports `active` and the port reports listening while the VM
is already stopping.

**A gateway that looks up but times out everywhere: check `ip rule` first.** The
mirror image of the rule above — distro running, service `active`, port LISTEN —
yet every connect *times out* and is never refused, loopback included, and even
`ping 127.0.0.1` loses 100%. The kernel's local-delivery rule
`0: from all lookup local` has gone missing, so the kernel routes its own
addresses out the physical NIC: `ip route get 127.0.0.1` reads `… via <gw> dev
eth0 src <eth-ip>` instead of `local 127.0.0.1 dev lo`, a hanging connect shows
in `ss` as SYN-SENT *sourced from the eth0 address*, and `lo` counters stay
frozen while eth0 ticks up. Everything riding on local delivery dies with it:
the desktop's path in over the WSL mirror, the WSL DNS proxy (`10.255.255.254`
is a loopback address), and all outbound — which is why agent turns log "can't
reach the model provider" while the process log looks healthy. Look for a
`nixos-rebuild switch` shortly before the outage: read `journalctl -b` around
the switch window — such a switch restarts `systemd-networkd` when network
config changed, and that restart is the culprit — networkd's own foreign-rule
purge; the mechanism and its off switch are two paragraphs below.
A switch that ended `failed (status 4)` still applied the generation: status 4
marks a unit that failed to start, not a skipped activation, so do not dismiss
it as unrelated — on this workstation the recurring cause is a unit whose
secret is still clan's `/no-such-path` sentinel (see `nixos-clan-flake`). Discriminate from the other look-alikes by failure mode —
distro stopped or nothing listening: **refused**; local delivery broken:
**timeout, even to a surely-closed port** (a closed port that hangs instead of
refusing is packet-level breakage, not a dead app). Restore with
`sudo ip rule add pref 0 from all lookup local`, then *verify*, do not assume:
`ip route get 127.0.0.1` must read `local … dev lo`, the probes must answer from
both legs, and `hermes chat -q` in the distro must complete. One-shot matrix:
`scripts/gateway-reachability-probe.sh` (run inside the distro; it is written
CRLF on Windows — normalise with `tr -d '\r'` as its header shows).

**Who deletes it, and why it recurs: networkd's foreign-rule purge.** Once
networkd manages any link — a WireGuard interface is enough, because nixpkgs'
`networking.wireguard.useNetworkd` defaults to true as soon as `interfaces !=
{}` — every networkd **start** (boot, restart, switch) reviews routing policy
rules and deletes the ones it does not own, the kernel's local rule included.
Measured: a canary rule and `pref 0` survive `systemctl stop`, both vanish on
`start`, and with `SYSTEMD_LOG_LEVEL=debug` the journal shows the
`Remembering foreign …` / `Removing …` chatter. The off switch lives in
**networkd.conf**, not in the per-link file: `[Network]
ManageForeignRoutes=false`, `ManageForeignRoutingPolicyRules=false`,
`ManageForeignNextHops=false`; with those set, a restart leaves foreign rules
alone (A/B-verified live). NixOS reverts `/etc` hand-edits at the next
boot/switch (etc activation restores the symlinks), so land the flags in the
system config (`systemd.network.config.networkConfig`) and rebuild; until then,
re-add the rule once per boot (which restores the guest's own loopback only —
the Windows leg stays down until a protected boot; see below). On a live
system, an `/etc/systemd/networkd.conf.d/*.conf` drop-in with the same flags
works and survives reboots (unmanaged path), which is a usable stopgap before
the flake change lands.

**After the switch that lands the flags, verify the effective config, not a
file's presence.** `systemd-analyze cat-config systemd/networkd.conf` must show
all three flags coming from the store's `networkd.conf`; the full `ip rule` set
above must survive the switch's own networkd restart — a switch restarts
networkd whenever network config changed, which is exactly when an unprotected
purge strikes, so that is the moment to check. Once the flags live in the
system config the drop-in is redundant; judge the landed state by the effective
config, never by the drop-in's survival.

**Restoring the rule fixes the guest, not necessarily the Windows leg — and
the real casualty is WSL's mirror plumbing.** A healthy mirrored guest carries
a rule set that `ip rule show` *does* display once it survives:
`0: from all iif eth0|loopback0|eth1 ipproto tcp|udp lookup local` (inbound
mirror delivery), `1: … lookup 127` / `… lookup 128` (tables 127/128 via the
`169.254.73.249` helper on `loopback0`), and a local-table fallback. The
networkd purge deletes these together with the kernel's local rule — and it
re-runs at **every boot**, so an unprotected VM loses the whole mirrored stack
seconds after it starts, and **no reset heals it**: VM restarts, a
WSL-service restart, a `networkingMode` toggle, even a Windows reboot all
re-run the boot that re-purges. The one-liner alone restores only the guest's
own loopback. Diagnose by diffing `ip rule` against the healthy signature
above; cure by suppressing the purge at boot (previous paragraph).

**Verify the Windows leg passively when Windows-side probes are unavailable.**
The desktop app writes its gateway-health cycles to
`%LOCALAPPDATA%\hermes\logs\desktop.log`: `[fleet-roster] <conn>: … connect
ETIMEDOUT 127.0.0.1:9119` every ~10 min is the failure signature; a successful
attach shows in the backend's `gui.log` as `ws accepted peer=127.0.0.1:…`.
Reading those beats poking the socket and needs no commands on the Windows side.

**Bind loopback and skip auth entirely.** A non-loopback bind always requires an
auth provider — `--insecure` is a documented no-op since the June 2026 hardening —
so bind `127.0.0.1`. Under `networkingMode=mirrored` a Windows client reaches a WSL
loopback listener **as true loopback** (the guest sees peer `127.0.0.1`), so no
firewall rule, port forward, password or OAuth is needed. Read `.wslconfig` for
`networkingMode` before designing around a forwarded port. That same mirror makes anything
bound to `0.0.0.0` inside the distro reachable from the LAN at the host's address, so
`ss -ltn` is the exposure list, not an internal detail.

**Use `127.0.0.1`, never `localhost`.** `localhost` resolves to `::1` first while
the server binds IPv4 only, so the WebSocket handshake times out — often while
plain HTTP appears to work. Use the literal address in every URL you hand the user
and in every probe you write.

**Pin the session token.** It is generated per process (`secrets.token_urlsafe`), so
a saved desktop connection breaks on every service restart. Set
`HERMES_DASHBOARD_SESSION_TOKEN` in the unit to a fixed value.

**`hermes serve` and `hermes gateway` are different servers, and only one runs the kanban
dispatcher.** `hermes serve` is the backend the desktop and remote clients attach to;
`hermes gateway` is the messaging gateway, and the kanban dispatcher lives inside it
(`kanban.dispatch_in_gateway`, default on). On a serve-only topology there is no
dispatcher, so a board card sits `ready` indefinitely with nothing claiming it — and
`hermes kanban daemon` refuses to start as deprecated. Before concluding anything about a
stalled board, ask what a tick would actually do; this spawns nothing:

```bash
hermes kanban dispatch --dry-run   # what a tick would reclaim/promote/spawn
hermes kanban dispatch             # run one tick now
hermes kanban daemon --force       # standalone dispatcher, when no gateway exists
```

The `--force` standalone daemon is the working answer on a serve-only box; running it as
a systemd user unit is what makes it survive a restart.

**Restarting the dispatcher does not disturb work already in flight** — measured, not
assumed. A spawned worker detaches from the dispatcher's cgroup, so it shows the systemd
user manager as its parent rather than the dispatcher, and `systemctl restart` with the
default `KillMode=control-group` cannot reach it. The tick log then reads
`reclaimed=0 crashed=0` and the *new* dispatcher simply claims the next ready card.

Two consequences for how you test durability:

- A dispatcher restart is **invisible** to a running task, which is stronger than "the
  round can be resumed". Do not read a clean restart as evidence that re-claiming works.
- The re-claim path is exercised only by a worker that genuinely dies (reboot, OOM,
  killed process). That is a separate test, and it is the one people skip because the
  restart test already passed.

**NixOS has no FHS.** `/bin/sh` and `/bin/true` exist through the WSL compat layer;
most others do not — `/bin/sleep` and `/usr/bin/time` are absent. Use
`/run/current-system/sw/bin/<tool>`. Time a command with bash's own counter rather than
`time`: `SECONDS=0; cmd; echo "elapsed=${SECONDS}s"`. There is no system `python3`

either: run Python as `nix shell nixpkgs#python3 -c python3 script.py`. The two
 derivations do not share site-packages, so a pytest run needs one invocation that owns
both — `nix run nixpkgs#python3Packages.pytest -- tests/ -q` works, while `nix shell
nixpkgs#python3 nixpkgs#python3Packages.pytest -c python3 -m pytest` reports
`No module named pytest`.

**The kernel belongs to Windows, not to the distro.** `uname -r` reads
`<upstream>-microsoft-standard-WSL2`, installed by the Windows-side WSL package
(`Microsoft.WSL.Kernel`): no `nixos-rebuild`, kernel package or module inside the distro can
change it, and a kernel CVE is fixed by updating WSL, not by rebuilding the system. Read the
pairing with `wsl.exe --version` (WSL build plus kernel version). `wsl --update` serves the
stable channel, which can lag a fix the project has already published; `wsl --update
--pre-release` installs the newest published kernel. A kernel outside both channels is
replaced through `.wslconfig` (`kernel=` a `bzImage`, `kernelModules=` a modules VHD) built
with `Microsoft/config-wsl` from the WSL kernel tree. The mirror also means a service bound
to `0.0.0.0` in the guest is reachable from the LAN at the host's own address — list what
is exposed with `ss -ltn` before calling the machine unexposed.

**`wsl --shutdown` ends every distro at once — including the backend serving you.** Never
run it, or `wsl --terminate <distro>`, from a session whose Hermes backend lives inside that
distro: the tool call dies with the VM and the desktop loses the gateway mid-turn. Prepare
the command, state what it will interrupt, and let the user run it from Windows.

**A repo on this setup exists twice** — a Windows clone and a distro clone — and nix
runs only in the distro's. Confirm which one a tool reads before concluding a change
had no effect; the two drift silently.

**A temp worktree is removed as a worktree, not with `rm -rf`.** `git worktree add --detach /tmp/x`
writes `.git/worktrees/<id>` in the parent repo; deleting the directory directly leaves that entry
stale, so the next `git worktree add` to the same path fails or silently reuses it. Remove it with
`git worktree remove --force /tmp/x` and `git worktree prune`, then check `git worktree list` shows
only the real checkout. This matters more here than elsewhere because a throwaway worktree under
`/tmp` is the normal way to review a revision without dirtying the distro checkout.

## Driving work in the distro from Windows

**A long job started from a tool call dies with the call.** Launch it detached so it
outlives the session that started it:

```bash
setsid nohup "$PY" scripts/long_job.py --out "$OUT" > "$OUT/job.log" 2>&1 < /dev/null &
disown
```

Pass `-u` to Python or the log stays empty while the job runs: stdout is block-buffered
once redirected, so an empty log is not evidence of failure, and reading it as one wastes
a debugging pass. Judge progress by the job's output files, not by its log. Confirm it is
alive with `pgrep -af` on the script name, and check for its `hermes` children to tell
"working" from "stuck".

**A write-capable command belongs in a sandbox, not the distro's home.** The
distro's `/tmp` is disk-backed and never auto-cleaned, and a command that writes
to `$HOME` leaves state the next session inherits. Run it through bwrap with a
read-only root, a private `/tmp` and an overlay `$HOME`; writes vanish with the
process. Rebind any file the command needs from `/tmp` read-only after the tmpfs,
or it will not be found. Recipe, process-group kill rule and non-NixOS fallback:
the `ephemeral-cleanup` skill's sandboxing reference.

**`hermes config get` prints a list as YAML bullets, not JSON.** A script that greps it
for a JSON-shaped value (`[a, b]`) matches nothing, so the value reads as absent and
whatever depended on it is silently skipped — a config write that no-ops with no error.
Ask for the machine-readable form:

```bash
hermes config get skills.external_dirs --json      # ["~/path/to/skills"]
```

**Write the script to a file; do not inline it in `bash -c`.** Any `-c` string that
carries a shell construct is re-parsed by the distro's login shell, so the construct runs
in the wrong shell — or is rejected before bash sees it. It is not only `$VAR`: `$?`
(fish: "`$?` is not the exit status"), `$(…)`, `$'…'` (fish: "not a valid variable"), a
loop variable inside double quotes (`"$d"` arriving empty), and a redirection inside
command substitution all fail this way. A quoted glob inside command substitution is the
same failure with a worse symptom: `$(find "$d" -name "*.py")` dies as fish `No matches for
wildcard` / `Unmatched wildcard`, and the call can burn its whole timeout instead of
returning that error — a probe that returns blank or times out while reading as well-formed
prose is this, not a slow filesystem. A **single line** is enough: `bash -c 'S=/nix/store/x;
head $S/f'` reads `/f`. The symptom is silent — a command that "ran" but did nothing, or a
fish parse error quoting text you never wrote — so when a WSL command behaves nothing like
the same text in a shell you control, this is the cause, not your script. **The
wrong-directory variant is the expensive one, because the error names your target.**
`cd X && echo "$(git branch --show-current)"` in a `-c` string evaluates the substitution
in the *caller's* directory, so the `git` inside it answers about the wrong tree and prints
`fatal: not a git repository` about a directory that plainly is one — measured, and nearly
reported as "that checkout is not under git". Never conclude anything about a target from a
one-liner's error; put the same text in a file under the scratch dir and run that before
believing it.

**An empty variable does not fail — it collapses the argument.** `ls $D` with `$D` unset
lists the current directory, and `grep -rn PATTERN $D` becomes a recursive grep of it: run
from the Windows home that is the whole user profile — minutes of permission-denied noise
and a capture far too large to read. A trailing `2>&1 | head` bounds what you *see*, not
the work. Never parameterise a path in an inline string; write it literally, and when a
recursive search must be inline, pass the path explicitly and narrow it (`-l`,
`--include=`).

Put the script
under the scratch dir and invoke it by path, passing native paths:

```bash
wsl.exe -d <distro> -- /bin/bash /mnt/c/<scratch>/job.sh
```

**Or pipe the script in on stdin, which needs no file on the share.** `bash -s` reads the
program from stdin, so nothing is re-parsed by the login shell and the write-and-run ordering
trap disappears — compose the heredoc and the pipe in one call:

```bash
cat > "$TMPDIR/scan.sh" <<'EOF'
cd ~/projects
for d in */; do echo "== $d"; git -C "$d" status --porcelain | head; done
EOF
wsl.exe -d <distro> -- bash -s < "$TMPDIR/scan.sh"
```

Quote the heredoc delimiter (`<<'EOF'`) so `$dir` and friends reach the distro intact, and
remember stdin is the script: a `read` or any prompt inside it consumes the remaining program
text instead of waiting. Use this for read-only scans; use the by-path form above for anything
that must survive long enough to be re-run.

**Write the script before you launch it.** A `terminal` call that is promoted to background starts
immediately — before the `write_file` in your *next* call — so the launcher runs against a path
that does not exist yet and exits 127 (`bash: …/job.sh: No such file or directory`). A call merely
queued behind a long-running one does the same. Both look like failures in the notification stream
and are indistinguishable from a real bug unless you remember the ordering. Compose the write and
the run in a single turn, and treat a 127 naming your own script as this, not as a missing file.

**The share is one-way: read-only into the distro.** `\\wsl.localhost\<distro>\…` is a fine read
path from Windows — `read_file`, grep, `git log` all work — and a dead write path. It is also a
slow path for anything that walks the tree: `du -sh *`, `find` and a recursive `ls` over the
share stall past a 180 s timeout because every stat crosses 9p, so a scan that "timed out" says
nothing about the size of the directory. Run recursive scans inside the distro (the piped
invocation below) and read only the summary back. A `patch` or
`write_file` against it dies with `mkdir: cannot create directory '//wsl.localhost': Read-only file
system`, which looks like a permissions problem and is a mount property. To edit a distro file, write
the edit as a script under the Windows scratch dir, run it with the invocation above, then read the
result back over the share. Never conclude the edit failed without that read-back.

**A multi-edit script must apply its edits cumulatively, not each against the original.**
Planning several replacements from one read of a file computes every `new` from the pristine
text, so the last write wins and each earlier edit vanishes with no error at all. Read once,
apply each replacement to the accumulated string, assert the anchor occurs exactly once
before applying it, and write nothing until every anchor has been found — a drifted anchor
is then a refusal instead of a silent partial edit. `git diff --stat` is the check: a file
you expected to change in three places showing one is this bug.

**A file copied in from the Windows share lands executable.** `/mnt/c` carries the Windows
mount's `0777`, so `cp` into the distro leaves mode `755` and `git add` records a new mode
bit on a text file — visible in the commit as `create mode 100755 LICENSE`. `chmod 644`
before staging (keep `755` only for scripts), and audit with
`git ls-files -s | awk '$1=="100755"'`.

**Native Windows binaries take native paths, verbatim.** `git.exe`, `python.exe` and `hermes.exe` do
not translate MSYS forms: `/c/Users/…` and `/mnt/c/…` arrive as relative-looking strings and resolve
to `C:\c\Users\…`, so the call fails with "No such file" on a path a directory listing shows as
present. Pass
`C:/Users/<you>/…` (forward slashes are fine) to anything that is not a bash builtin or an MSYS
program. The expensive instance is an output flag — `-o`, `--output`, `--prefix` — where the tool
writes nothing, exits non-zero, and the next step in the same script silently operates on a file
that was never created. Gate anything destructive on the artefact existing, not on the command
having been issued.

## Procedure

1. **Confirm the distro and the networking mode.**
   ```bash
   wsl.exe -l -v                       # distro name and state
   cat /mnt/c/Users/<you>/.wslconfig   # want networkingMode=mirrored
   ```

2. **Install the backend.** The `#minimal` output is the smallest that ships
   `hermes` with `serve`:
   ```bash
   nix profile add github:NousResearch/hermes-agent#minimal
   command -v hermes
   ```
   On a non-Nix distro use the standard Linux installer. Check `nix profile history`
   first if a package may already exist — an add can replace a pre-existing entry.

3. **Seed the provider config file-to-file.** Copy the `custom_providers` block and
   the `model` keys from the source config into the distro's `~/.hermes/config.yaml`.
   Never route a key through stdout, and never hand-type one.

4. **Clear a stale managed marker** if `hermes config set` is refused — see Pitfalls.

5. **Write the systemd user unit and enable linger.**
   ```ini
   [Unit]
   Description=Hermes backend (loopback)
   After=network.target

   [Service]
   Type=simple
   ExecStart=%h/.nix-profile/bin/hermes serve --host 127.0.0.1 --port 9119
   Environment=PATH=%h/.nix-profile/bin:/run/current-system/sw/bin:/usr/bin:/bin
   Environment=HERMES_DASHBOARD_SESSION_TOKEN=<pinned>
   Restart=on-failure
   RestartSec=5

   [Install]
   WantedBy=default.target
   ```
   ```bash
   systemctl --user daemon-reload
   systemctl --user enable --now hermes-serve.service
   sudo loginctl enable-linger "$USER"
   ```

6. **Hold the distro open from Windows.** A hidden launcher in the Startup folder —
   no elevation required:
   ```vbs
   Set sh = CreateObject("WScript.Shell")
   Do
     sh.Run "wsl.exe -d <distro> --exec /run/current-system/sw/bin/sleep infinity", 0, True
     WScript.Sleep 5000
   Loop
   ```
   Save as `<Startup>/hermes-wsl-gateway.vbs` (CRLF). The loop advances only when the
   session ends, so it re-establishes rather than spins.

7. **Migrate the work.** Copy `profiles/`, `memories/`, `cron/`, `SOUL.md`,
   `auth.json` and `config.yaml`; leave the app's own trees behind (`tools/`,
   `installs/`, `lsp/`, `cache/`, the source checkout). Scan the configs for
   host-specific values first — `~`-based paths migrate verbatim, absolute ones do
   not. Re-run the fleet installer rather than trusting copied profile directories.

8. **Verify both legs.** HTTP alone is not proof; the WebSocket is the leg that
   fails in practice:
   ```python
   from websockets.asyncio.client import connect
   async with connect(f"ws://127.0.0.1:9119/api/ws?token={TOKEN}") as ws:
       print(await ws.recv())      # first frame: gateway.ready
   ```

## Pitfalls

- **The session token travels in the QUERY STRING** (`/api/ws?token=…`), not an
  `Authorization` header — a header-token handshake is rejected `403`. Read the token
  from the served page's `__HERMES_SESSION_TOKEN__`.
- **A stale `~/.hermes/.managed` marker silently refuses every config write.**
  `save_config()` returns early when a marker or `HERMES_MANAGED` is present, so
  `hermes config set`, profile installers and the desktop's own settings writes all
  fail with "managed by <package manager>" — and a script using `set -e` aborts
  mid-way. If the install was a plain `nix profile add` with a writable config, the
  marker is stale: remove it, or set `HERMES_MANAGED=false`.
- **Task Scheduler `ONLOGON` tasks require elevation.** Both `Register-ScheduledTask`
  and `schtasks /create /sc onlogon` fail with "Access is denied". The Startup folder
  is the no-admin equivalent.
- **Do not restart the desktop app to fix its own reachability.** If the app is
  hosting the session, restarting it ends the session; prefer a change the client
  picks up on reconnect, or tell the user to restart.
- **A copied profile set can include dead entries.** A directory in `profiles/` with
  no `config.yaml` is a stub, not a profile — it will not appear in
  `hermes profile list`. Re-run the fleet installer instead of trusting a directory
  listing.
- **Do not hand-write the desktop's connection registry.** The app owns that file and
  rewrites it while running; register a gateway through its UI instead.

## Verification

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:9119/api/health   # 200
curl -s http://127.0.0.1:9119/api/status | grep -o '"auth_required":[a-z]*' # false
systemctl --user is-active hermes-serve.service                             # active
wsl.exe --list --running                                                    # Running
```

Then the WebSocket handshake above, and one real agent turn under a profile:

```bash
hermes -p <profile> chat -q 'Reply with exactly: ok'
```

A reply proves the profile's credentials and model resolve inside the distro.
