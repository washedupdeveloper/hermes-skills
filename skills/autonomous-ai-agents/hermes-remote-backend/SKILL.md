---
name: hermes-remote-backend
description: "Use when running Hermes on a remote host or in WSL."
version: 1.5.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
category: autonomous-ai-agents
targets: [hermes]
metadata:
  hermes:
    tags: [hermes, serve, backend, remote, wsl, desktop, gateway, websocket]
    related_skills: [hermes-agent, hermes-profile-fleet, nixos-clan-flake]
writes: [$XDG_CONFIG]
leaves: one systemd user unit
side_effects: [systemd, port]
---

# hermes-remote-backend

**Heads-up.** Section 5 installs a systemd **user** unit and enables linger, so the backend keeps running after the shell that started it exits. It listens on `127.0.0.1:9119` on the host you run it on; nothing is written inside the project.

```bash
: "${SKILL_XDG_CONFIG:=${XDG_CONFIG:-$HOME/.config}}"
```

**Runtime.** Podman; `docker` is the accepted substitute — the policy and the differences that bite are in `docs/runtime.md`.

Run a Hermes backend on another host — a WSL distro, a LAN box, a VPS — and
attach the desktop app to it as a **Remote gateway**. The backend is `hermes
serve`; the desktop only *attaches*, it never starts a remote backend (SSH
connections excepted).

**WSL boundary rules live in `nixos-clan-flake`** (path translation, driving the
distro, mirrored networking). This skill owns the Hermes serving and attachment
side and points there rather than restating it.

## When to Use

- The desktop app should attach to a Hermes instance on another machine.
- A Hermes backend needs to run inside a WSL distro, headless and persistent.
- An agent process on Windows is being killed by code-integrity policy and the
  workload should move off the Windows side instead.
- A remote gateway shows in the desktop roster but will not open, or a saved
  connection breaks after every restart.
- The backend answers right after a WSL terminal is opened and is unreachable
  again later — the distro is stopping, not the server.

## 1. Decide the bind before anything else

`should_require_auth(host)` in `hermes_cli/web_server.py` gates on one thing:
whether the bind is loopback — `_LOOPBACK_HOST_VALUES = {"localhost",
"127.0.0.1", "::1"}`. Any other bind (including `0.0.0.0`) is public and
**forces an auth provider** (password or OAuth). `--insecure` is a deprecated
no-op since the June 2026 hardening — do not reach for it.

Prefer loopback. A public bind costs auth setup, TLS/proxy work, and a real
attack surface. Bind non-loopback only when the client genuinely cannot reach
the host's loopback.

**Test reachability before designing around it.** Start a throwaway listener
bound to `127.0.0.1` on the host and probe it from the client machine. If the
connection arrives with a loopback peer address, loopback is enough — no auth,
no firewall rule, no port forward.

### A guest's `127.0.0.1` is the guest, not the host

"Loopback is enough" holds for a client on the same machine and for WSL (§2). It
does **not** generalise to anything virtualised. Measured in a NixOS VM test, with
a control listener to prove the probe works:

| probe from the guest | sandbox on | sandbox off |
|---|---|---|
| control: a listener *inside* the guest | OPEN | OPEN |
| host service via `127.0.0.1` | CLOSED | CLOSED |
| host service via `10.0.2.2` | CLOSED | OPEN |

- `127.0.0.1` in a guest never reaches the host, in any configuration. Without the
  control line a CLOSED reads as a broken probe rather than a closed port.
- `10.0.2.2` is QEMU's SLIRP gateway — the loopback of whatever network namespace
  the QEMU process is in.
- A nix build sandbox gives the build its **own** network namespace, so by default
  that gateway is the sandbox's loopback and the host's services are invisible.
  `--option sandbox false` makes the host reachable at `10.0.2.2`.
- `--option sandbox false` alone changes nothing on a second run: it is not part of
  the derivation, so nix returns the cached result and the option looks inert. Add
  `--rebuild`, or the experiment "confirms" whatever it did last time.

WSL's mirrored networking is one layer below this, which is exactly why the
assumption is easy to make: there `127.0.0.1` genuinely reaches the host. A
container sharing the host's network namespace (`--network host`) behaves like a
host process; a VM does not.

**A NixOS test VM has no outbound network** — no DNS, and the gateway is closed —
so anything that fetches inside it (a package install, a `podman build` pulling a
base image) fails for a reason unrelated to what is being tested. Assert on WHICH
error came back, so a network failure stays distinguishable from a real one.

### A reachable gateway is not a runnable agent

The desktop *attaches* to `hermes serve`; anything that **drives** an agent — the
CLI, or a harness that shells out — uses the `hermes` **launcher** (`hermes -p
<profile> chat -q <prompt>`) and reads what that turn writes. Those are different
things, and a listening socket on the gateway port is evidence of neither: the
gateway can be up with no launcher at all (a desktop-only install), and the
launcher works with no gateway (every ordinary CLI install). "The port answers, so
Hermes is available" is how a host passes its own check and then fails every run.

Answer the question in **layers**, cheapest and most certain first, and never
promote a weak signal into a strong claim:

| layer | kind | what it establishes |
|---|---|---|
| L0 launcher | deterministic, local | the executable resolves (`$HERMES_BIN`, then `PATH`, then known locations). Presence only. |
| L1 version | deterministic, local | `hermes --version` runs — it **executes**. A file that resolves and cannot run fails every turn. |
| L2 profiles | deterministic, local | the profiles exist AND carry a provider. Credentials are per profile and not shared. |
| L3 gateway | optimistic, network | something is listening. A **hint**, never part of the verdict. |
| L4 capability | authoritative, costly | one real minimal turn. The only layer that proves anything, and the only one that costs money — so it is opt-in. |

The verdict names the **first** thing that would stop a run (`no-launcher`,
`unusable-launcher`, `no-profiles`, `no-credentials`), because that is the one
worth fixing; five statuses at equal weight bury it. Keep the port in the output
but label it a hint, so nobody reads it as the answer. Pin both directions with a
test: a live listener must not turn a missing launcher into "ready", and a dead
port must not spoil a working one.

**`hermes config get <key> --json` prints its warnings on stderr**, so stdout stays
parseable — a consumer must capture stdout only. Merging the streams (`2>&1`) turns
an advisory line ("install out of sync: …") into a parse error on a value that was
fine.

## 2. WSL specifics

With WSL2 `networkingMode=mirrored` (check `C:\Users\<user>\.wslconfig`),
Windows reaches a listener inside the distro on **`127.0.0.1`**, and the guest
sees the peer as `127.0.0.1` — genuine loopback, so the auth gate stays open.

- **Use `127.0.0.1`, never `localhost`.** `localhost` resolves to `::1` first;
a server bound IPv4-only fails the WebSocket handshake with a *timeout* while
plain HTTP still looks healthy. This is the single most confusing failure here.
- A connection to the guest's **LAN IP** from the Windows host does not work —
it hits the host's own stack. Loopback is the path that works.
- Prefer a native Linux install inside the distro over driving a Windows-side
binary: a Windows launcher spawning `hermes.exe` stays subject to Windows
code-integrity policy (WDAC / AppLocker / Smart App Control) and can be killed
mid-run. Nothing inside the Linux VM is subject to those.

## 3. Install

Look before installing. A NixOS distro may already carry `hermes` from
home-manager, and `nix profile add` puts a second copy ahead of it on `PATH`:

```bash
command -v hermes; nix profile list   # before
nix profile add github:NousResearch/hermes-agent#minimal   # smaller than #default, still ships hermes + serve
nix profile history                   # after: confirm you did not clobber a generation
```

`#minimal` is the right default for a headless backend.

**Resolve the interpreter, do not assume one.** A NixOS host has no system
`python3`, and on Windows the interpreter is not named `python3` either. Hermes
exports the pinned interpreter it runs on as `HERMES_PYTHON`; use it:

```bash
PY="${HERMES_PYTHON:-$(command -v python3 || command -v python)}"
```

Any skill or script that shells out to Python should resolve it this way — a
bare `python` is a portability bug, not a missing package.

## 4. Pin the session token

The server mints `_SESSION_TOKEN` per process (`secrets.token_urlsafe(32)`)
unless `HERMES_DASHBOARD_SESSION_TOKEN` is set. An unpinned token invalidates the
saved desktop connection on **every restart**, forcing a re-paste each time. Pin
it in the service environment.

Generate it URL-safe and **free of `%`** — systemd expands `%` specifiers in a
unit file, so a raw base64 token corrupts silently and the desktop then fails a
auth it was told was correct. `openssl rand -base64 32 | tr '+/' '-_' | tr -d '=\n'`
is the shape to use.

## 5. Keep it up

A systemd **user** unit plus linger, so it outlives the shell that started it:

```ini
[Unit]
Description=Hermes backend
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

Save the unit as `$SKILL_XDG_CONFIG/systemd/user/hermes-serve.service`, then
`sudo loginctl enable-linger <user>` and `systemctl --user enable --now hermes-serve.service`.

`hermes serve --status` lists the running backend processes and `hermes serve
--stop` stops them — how to restart the server without hunting a PID or guessing
which of several `hermes` processes is the backend. Add `--skip-build` when the
web UI dist is already built and npm is unavailable.

**On WSL2 that is necessary but NOT sufficient — the distro is what stops.**
WSL2 terminates a distro the moment its last `wsl.exe` session ends. systemd and
logind linger keep the *service* alive only while the *distro* runs; they do not
hold the distro up. The signature is a gateway that answers immediately after any
`wsl.exe` call and is unreachable again ~30 s later. So the distro has to be kept
alive from the Windows side, and only a held-open session does that:

```vbs
sh.Run "wsl.exe -d <distro> --exec /run/current-system/sw/bin/sleep infinity", 0, True
```

Copy `templates/wsl-gateway-autostart.vbs`: it holds one hidden session and
re-establishes it if it drops.

Start it from the **Startup folder**, not Task Scheduler. `schtasks /create
/sc onlogon` and `Register-ScheduledTask` both fail with *Access is denied* — an
ONLOGON task requires elevation, the Startup folder does not. Use a path that
exists inside the distro: a NixOS guest has no FHS, so `/bin/sleep` is absent,
the session dies at once, and the reason appears only in WSL's relay stderr.

Prove the autostart from cold without a reboot: `wsl.exe --terminate <distro>`,
confirm `wsl.exe --list --running` no longer names it, then launch the Startup
entry and probe `127.0.0.1:9119` from the Windows side. The distro should come
back and the gateway answer within a few seconds. A distro that stays stopped
means the launcher never established a session — check the command's path inside
the guest before suspecting WSL.

## 6. Verify both legs

HTTP first:

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:9119/api/health   # /api/status is also 200
```

Then the **WebSocket** — the leg that fails in practice. It authenticates with
the token as a **query parameter**:

```
ws://127.0.0.1:9119/api/ws?token=<token>
```

The `Authorization: Bearer` and `X-Hermes-Session-Token` **header** paths are
rejected with **403**, and no token is 403. Probe with a real client
(`websockets`), not curl — curl's handshake is not representative and returns a
misleading 403. Success is `101` plus a first frame like
`{"jsonrpc":"2.0","method":"event","params":{"type":"gateway.ready"...}}`.

## 7. Attach the desktop

**Settings → Gateways → Add connection → Remote gateway**: unique name,
`http://127.0.0.1:9119`, auth = **Session token** (paste the pinned token). Then
**Test** — it probes HTTP *and* WS, so a pass means chat will actually work.

Do **not** hand-edit the desktop's `connections.json`
(`%APPDATA%/Hermes/connections.json`) while the app is running: it holds the
registry in memory and will overwrite you. Stop the app, or add the connection
through the UI.

## 8. Debug an empty or partial roster

An empty roster almost always means the desktop is looking somewhere other than
where the profiles live — not that the backend lacks them.

- **Confirm the backend serves them.** `/api/profiles` **requires the session
token** and answers `401 {"detail":"Unauthorized"}` without one, unlike
`/api/status` and `/api/health`, which are open. A token-less enumeration
therefore reads as "no profiles" rather than "unauthorized".
- **Confirm the desktop actually reached it.** `logs/gui.log` on the backend
records `Multi-profile hosting activated at startup (N servable profile homes)`
and each `ws accepted` / `ws closed … messages=N`. Zero messages means the app
never talked to this backend.
- **Check which gateway Sessions opens on.** In the desktop registry
  (`connections.json`), `primary` and `lastUsed` are different things: **setting a
  gateway Primary is the registry fallback and does not switch the Sessions
  workspace.** A `lastUsed` still pointing at `local` leaves Sessions on the
  app-managed backend, whose own home may hold no profiles at all. Switch the
  gateway in the Sessions sidebar, or restart the app to force re-enumeration.
- **Two registrations of one backend collapse to one row.** The roster groups by
  the backend's `install_id`, so a `local` entry and a remote entry reporting the
  same id render as a single agent rather than two. Compare `install_id` on each
  side (`~/.hermes/install_id`, and `/api/status`) — distinct ids are what let two
  backends appear separately.
- **The same profile names listed under two gateways is expected, not a bug.** A
  profile belongs to the machine that hosts it, so a `local` entry and a remote
  entry legitimately show the same names when both hold a copy — the rail groups
  them per gateway precisely so the two sets never read alike. Only same-named
  profiles *within one backend* would be a real duplication, and the `install_id`
  collapse above is what merges those. Likewise, registering a remote gateway does
  not move the session onto it: the client stays on whichever gateway it is
  already using until the user switches, and that is a valid state, not a
  half-finished setup.
- **The app renders the roster from its own cached registry.** After any
  backend-side fix the app must restart to re-read `connections.json` and
  re-enumerate; nothing done on the backend refreshes it. When your session runs
  *inside* that desktop app, restarting it ends your own session — ask the user to
  restart, and say precisely what to report back (the profile rail's contents, and
  whether the gateway row reads *Reachable*).

## 9. Migrate the work, not the application

Starting the server alone leaves an empty roster. Move the *work* — profiles,
memories, cron, credentials, config and the project repos — and leave the
application behind: the bundled source tree, `tools/`, `installs/` and caches
are machine-specific and rebuildable.

See `references/migrating-a-hermes-home.md` for the inventory, the exclusion
list, the config-portability check and the post-copy re-sync.

## Pitfalls

- **Do not generalise WSL's loopback to a VM or container.** `networkingMode=mirrored`
  is a WSL2↔Windows property. Inside a VM `127.0.0.1` is the guest and the host is at
  QEMU's `10.0.2.2` — and only with the build sandbox off (see §1). Designing around
  the assumption gives a gateway that answers from one context and times out from
  another, which reads as a flaky server rather than as a wrong address.
- `localhost` in a WS URL times out against an IPv4-only bind — use `127.0.0.1`.
- Token in a header → 403. It must be `?token=` on the WS URL.
- An unpinned token breaks the saved connection on every restart.
- The roster is per `(gateway, profile)`: profiles live on the machine that owns
them. Porting a workflow to a remote backend means porting its profiles **and**
its `skills.external_dirs` — starting the server alone gets you an empty roster.
- **A profile gets skills by snapshot, not inheritance.** `hermes profile create
  --clone` copies only the *bundled* set, so a mounted library is invisible to a
  profile unless that profile's own config sets `skills.external_dirs`. No error
  is raised — a persona told to load such a skill simply proceeds without it, and
  the workflow looks installed while missing its tooling. Measure it: compare each
  profile's `SKILL.md` count against the library's. See
  `references/migrating-a-hermes-home.md`.
- **A skill present both locally and in a mounted library resolves to the LOCAL
  copy, silently.** `skills.external_dirs` ranks below the home's own `skills/`, so
  editing the mounted library changes nothing, and the two drift with no error and
  no way to see it from the workflow's behaviour. Keep names unique across the two,
  or delete the local copy when moving a skill into the library. Before believing a
  change landed, enumerate both roots for `SKILL.md` and classify each against
  `$HERMES_HOME/skills/.bundled_manifest` — that file is what separates the skills
  Hermes owns (refreshed by `hermes update`) from the ones you authored, and a
  bundled name added to a library gets two owners.
- Verify a spawned agent turn actually completed (`hermes chat -q ...` against
  the remote) before declaring the backend good; HTTP 200 only proves the process
  is listening.
- Re-sync mutable state after the copy. While the source home stays live — which
  it does, since the migrating session runs on it — memory writes and config
  edits make the destination stale. Re-copy `memories/` and `config.yaml` last
  and verify by size, rather than assuming the copy is still good.
- A profile directory with no `config.yaml` is a stub, not a profile: it will
  not appear in `hermes profile list` and carries no credentials. Do not count
  it when reporting what migrated.
- `/api/profiles` is authenticated while `/api/status` is not: a token-less
  enumeration returns 401, which is easy to misread as an empty roster.
- **Do not hand-write the home `config.yaml`.** It is classified a protected
  agent-instruction file and a direct write is refused. Use `hermes config set`,
  which also works per-profile via `HERMES_HOME=<profile dir>`, and hand any
  home-level edit you cannot express that way to the user.
- **`Cannot save configuration: … managed by home-manager` is a hard refusal, not
  a warning.** `save_config()` returns early whenever `is_managed()` is true, so the
  write never happens: `hermes config set` becomes a silent no-op, and any installer
  that configures a profile (its toolsets, its metadata) half-completes while still
  printing success. `get_managed_system()` decides this from a `.managed` marker file
  in `HERMES_HOME` (or the `HERMES_MANAGED` env var), so a marker left behind by an
  earlier experiment keeps refusing writes long after the declarative config is gone —
  the install can be a plain `nix profile add` with a perfectly writable `config.yaml`.
  Diagnose by reading `$HERMES_HOME/.managed`; when the system config declares no such
  install, delete the marker (or set `HERMES_MANAGED=false`) and re-run the installer.
  Treat a refused write as a failure and fix the cause — never assume it landed.
- **Copying a profile is not installing it.** After porting, re-run the
  workflow's own installer when it ships one — such installers are typically
  idempotent and refresh `SOUL.md`, the profile definition, the rubric skill and
  the toolset list from version control, none of which a directory copy
  guarantees. If such an installer reports success but the profile still lacks its
  capability set, suspect the managed-config refusal above: the installer's own
  `hermes config set` calls are exactly what it swallows.
- **A deployment can sit behind its source, and that reads as broken.** A skill,
  profile, or tool whose files are synced from a repository is a *deployment*, not
  a copy: it silently lags, runs the old code, and reports the old behaviour with
  nothing to say a newer version exists. When a workflow behaves as though a
  feature were never built, check drift before diagnosing the feature — the
  workflow's own `--check` mode if it ships one, otherwise diff deployment against
  source. Both directions lose work, so edit the source and re-sync; an edit made
  to the deployed copy is overwritten by the next sync.
- **Linger does not keep a WSL distro running.** It keeps a *service* running
  inside a distro that is already up. Availability on WSL2 needs a Windows-side
  session held open (see §5), or the gateway disappears on its own a few seconds
  after the last `wsl.exe` call returns.
- **A probe that boots the thing it measures invalidates itself.** Any
  `wsl.exe -d <distro> …` call starts the distro, so a reachability test that
  runs one first will always then succeed. Check state with `wsl.exe --list
  --running` (it does not boot anything) and probe only with a client that stays
  on the Windows side — curl against `127.0.0.1:9119` — so the measurement does
  not create the condition it is testing.
- **A keepalive you start yourself cannot hold the distro for the user.** A
  `wsl.exe -d <distro> --exec … sleep infinity` launched from your own tool call
  is torn down when that call returns, so the distro stops a few seconds later
  and the evidence reads exactly like "the keepalive does not work". Nothing an
  agent starts from a tool call outlives it: install the Windows-side autostart
  (§5) and let the user's logon own the session. Before concluding the mechanism
  fails, confirm a holder is actually alive — `wsl.exe --list --running` reports
  the distro's state without booting it, and a keepalive whose command was never
  valid (an absent `sleep` path, say) is indistinguishable from one that ran and
  was reaped.
- **A stopped distro and a broken backend look the same from outside.** Both
  give a connection refused on `127.0.0.1:9119`. **A third look-alike times out
  instead of refusing**: the distro is up and the service `active`, but the
  guest's local-delivery routing rule is gone, so no connect ever completes —
  not even to a surely-closed port. `refused` means nothing is listening;
  `timeout` means the packets are not arriving or not returning, and the fix is
  never on the Hermes side. Settle which it is *before* changing anything on the
  backend: `wsl.exe --list --running` names the culprit in one line, whereas any
  `wsl.exe -d …` probe boots the distro and destroys the evidence. For the third
  case, see `hermes-wsl-backend`'s local-delivery rule and its
  `gateway-reachability-probe.sh` under that skill's `scripts/`.
