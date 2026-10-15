---
name: hermes-s6-container-supervision
description: "Modify or debug s6 services in the Hermes Docker image."
version: 1.1.0
author: Hermes Agent
license: MIT
platforms: [linux]
environments: [s6]
metadata:
  hermes:
    tags: [docker, s6, supervision, gateway, profiles]
    related_skills: [hermes-agent, hermes-profile-fleet]
---

# Hermes s6-overlay Container Supervision

Load this when working **inside the hermes-agent Docker image**: adding or removing
a supervised service, debugging a per-profile gateway, or changing `cont-init.d` boot
scripts. If you are just *using* Docker to run Hermes, read
`website/docs/user-guide/docker.md` instead.

## Architecture at a glance

```
/init                                  ← PID 1 (s6-overlay v3.2.3.0)
├── cont-init.d                        ← oneshot setup, runs as root
│   ├── 01-hermes-setup                ← docker/stage2-hook.sh
│   │   ├── UID/GID remap, chown /opt/data and /opt/data/profiles
│   │   ├── seed .env / config.yaml / SOUL.md
│   │   └── skills_sync.py
│   └── 02-reconcile-profiles          ← hermes_cli.container_boot
│       ├── chown /run/service (hermes-writable for runtime register)
│       └── walk $HERMES_HOME/profiles/<name>/gateway_state.json
│           → recreate /run/service/gateway-<name>/
│           → auto-start only those with prior_state == "running"
│
├── s6-rc.d (static services, in /etc/s6-overlay/s6-rc.d/)
│   ├── main-hermes/run                ← exec sleep infinity (no-op slot)
│   └── dashboard/run                  ← if HERMES_DASHBOARD=1, runs `hermes dashboard`
│
├── /run/service (s6-svscan watches; tmpfs)
│   └── gateway-<name>/                ← runtime-registered per-profile
│       ├── type        ("longrun")
│       ├── run         ("#!/command/with-contenv sh ... exec s6-setuidgid hermes hermes -p <n> gateway run")
│       ├── down        (marker — present means "registered but don't auto-start")
│       └── log/run     (s6-log → $HERMES_HOME/logs/gateways/<n>/current)
│
└── CMD ("main program")               ← /opt/hermes/docker/main-wrapper.sh
    └── routes user args: bare exec | hermes subcommand | hermes (no args)
```

## Key files

| Path | Role |
|---|---|
| `Dockerfile` | s6-overlay install + cont-init.d wiring + `ENTRYPOINT ["/opt/hermes/docker/entrypoint-dispatch.sh"]` |
| `docker/entrypoint-dispatch.sh` | PID-1 dispatcher: exec's `/init` + main-wrapper when the image owns PID 1; on wrapped runtimes (Fly Machines, `docker run --init`) skips `/init` and runs stage2-hook + main-wrapper directly, restoring the s6 helper PATH first. |
| `docker/stage2-hook.sh` | UID remap, chown, seed, skills sync. Runs as `cont-init.d/01-hermes-setup`. |
| `docker/cont-init.d/02-reconcile-profiles` | Calls `hermes_cli.container_boot` on every boot to restore profile gateway slots from the persistent volume. |
| `docker/main-wrapper.sh` | The container's CMD. Routes user args, drops to hermes via `s6-setuidgid`, exec's the chosen program. |
| `docker/s6-rc.d/main-hermes/run` | No-op `sleep infinity` — the slot exists so the s6-rc user bundle is valid. |
| `docker/s6-rc.d/dashboard/run` | Conditional service — `exec sleep infinity` unless `HERMES_DASHBOARD` is truthy. |
| `hermes_cli/service_manager.py` | `S6ServiceManager`: `register_profile_gateway`, `unregister_profile_gateway`, `start/stop/restart/is_running`, `list_profile_gateways`. |
| `hermes_cli/container_boot.py` | `reconcile_profile_gateways()` — walks persistent profiles, regenerates s6 slots, emits `container-boot.log`. |
| `hermes_cli/gateway.py::_dispatch_via_service_manager_if_s6` | Intercepts `hermes gateway start/stop/restart` and routes to s6 inside a container. |

## Why the CMD is the main program (not an s6-supervised service)

Two s6-overlay v3 mechanics block supervising main hermes:

1. **`cont-init.d` scripts receive no CMD args** — so the stage2 hook cannot parse
   `docker run <image> chat -q "hi"` to set `HERMES_ARGS` for a service `run` script.
2. **`/run/s6/basedir/bin/halt` does not propagate an exit code** — containers always
   exit 143 (SIGTERM) regardless. Per the s6 author: to shut down with a code you
   must let the CMD exit.

So the dispatcher prepends the wrapper to user args — `docker run <image> --version`
becomes `/init main-wrapper.sh --version`, and `--version` is not intercepted by
`/init`'s POSIX shell. The wrapper drops to hermes via `s6-setuidgid`, then exec's the
program, so the program's exit code becomes the container exit code.

**Trade-off:** main hermes is unsupervised under s6, matching its behaviour under
tini. Dashboard supervision is the only *new* guarantee; per-profile gateways under
`/run/service/` get full supervision.

## Quick recipes

```sh
# Verify s6 is PID 1  (expect s6-svscan)
docker exec <c> sh -c 'cat /proc/1/comm; readlink /proc/1/exe'

# Inspect a profile gateway  (/command/ is NOT on docker-exec PATH — use absolute)
docker exec <c> /command/s6-svstat /run/service/gateway-<name>
#   "up (pid …) …"                       → running
#   "down (exitcode N) … want up, …"     → crash loop
#   "down … normally up, ready …"        → user stopped it

# Bring a service up / down / restart
docker exec <c> /command/s6-svc -u /run/service/gateway-<name>
docker exec <c> /command/s6-svc -d /run/service/gateway-<name>
docker exec <c> /command/s6-svc -t /run/service/gateway-<name>

# Watch the cont-init reconciler log
docker exec <c> tail -n 50 /opt/data/logs/container-boot.log

# Run the docker test harness  (expect 19 passed, 0 xfailed)
docker build -t hermes-agent-harness:latest .
HERMES_TEST_IMAGE=hermes-agent-harness:latest scripts/run_tests.sh tests/docker/ -v
```

**Add a new static service:**

1. Create `docker/s6-rc.d/<name>/type` with `longrun\n` and `docker/s6-rc.d/<name>/run`
   (use `#!/command/with-contenv sh` + `# shellcheck shell=sh`).
2. Drop to hermes via `s6-setuidgid hermes` at the top of run (unless you need root).
3. Create empty `docker/s6-rc.d/<name>/dependencies.d/base` so it waits for the base bundle.
4. Create empty `docker/s6-rc.d/user/contents.d/<name>` so it joins the user bundle.
5. The `COPY docker/s6-rc.d/` in the Dockerfile picks it up automatically.

**Change the per-profile gateway run command:** edit
`S6ServiceManager._render_run_script` in `hermes_cli/service_manager.py` — it is also
called by `hermes_cli/container_boot.py::_register_service`, so it is the single source
of truth. Update the matching assertion in
`tests/hermes_cli/test_service_manager.py::test_s6_register_creates_service_dir_and_triggers_scan`.

## Pitfalls

- **"command not found" via `docker exec`.** `/command/` is on PATH only for processes
  spawned by the supervision tree. Always use the absolute path `/command/s6-svstat`.
  The `hermes` binary works because the Dockerfile adds `/opt/hermes/.venv/bin` to the
  runtime `ENV PATH`.
- **Profile directory ownership.** The reconciler runs as hermes; a root-owned profile
  dir makes it fail with `PermissionError`. `stage2-hook.sh` chowns
  `$HERMES_HOME/profiles` to hermes on **every** boot — don't remove that block.
- **Files written by `docker exec` are root-owned.** `docker exec` defaults to root;
  pass `--user hermes` or rely on the next stage2 chown sweep. Don't write under
  `$HERMES_HOME/profiles/<name>/` as root manually.
- **"s6-supervise not running".** The service dir is on tmpfs and was wiped on
  restart. The reconciler hasn't run yet, or it failed — check
  `docker logs <c> | grep '02-reconcile'`.
- **Gateway starts then exits (`down (exitcode 1)`).** Usually the profile has no model
  or auth configured. Run `hermes -p <profile> setup`; s6 keeps restarting it, which is
  the desired behaviour — the next attempt succeeds and stays up.
- **Reconciler skipped a profile.** It keys on the **presence of `SOUL.md`** as the
  "real profile" marker. Add one (even empty) to opt back in.
- **"The container exits 143!"** Something invoked `s6-svscanctl -t` or
  `/run/s6/basedir/bin/halt`; both begin stage-3 shutdown but return 143. Let the CMD
  exit normally instead — do **not** try to control the exit from a finish script.
