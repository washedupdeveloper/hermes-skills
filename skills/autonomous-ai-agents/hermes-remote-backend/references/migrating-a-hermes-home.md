# Migrating a Hermes home to a remote backend

Moving Hermes work off one machine (typically Windows) onto a backend host — a
WSL distro, a LAN box, a VPS — so the desktop becomes a thin client. Companion
to the parent skill's install / serve / attach steps.

## Work vs application

`HERMES_HOME` mixes two things. Copy the first, leave the second.

**Work — migrate:**

- `profiles/` — per-profile `config.yaml`, `skills/`, `memories/`, `cron/`,
  `SOUL.md`, `sessions/`
- `memories/` — `MEMORY.md`, `USER.md`
- `cron/`
- `config.yaml` (the main one) and `SOUL.md`
- `auth.json` — credentials
- `shared-state.db`
- your project repos

**Application — leave:**

- the bundled source tree and `tools/` binaries (gigabytes, machine-specific)
- `installs/`, `lsp/`, `cache/`, `sandboxes/`, `logs/`, `backups/`

A multi-gigabyte home is typically ~150 MB of actual work. Measure both sides
(`du -sh <dir>/*/`) before choosing what to copy; do not tar the whole home.

## Exclusions when copying profiles

Per-profile caches and derived state rebuild themselves and dominate the size:

```
--exclude='./.deleted' --exclude='cache' --exclude='lsp' --exclude='logs'
--exclude='audio_cache' --exclude='image_cache' --exclude='assets'
--exclude='models_dev_cache.json' --exclude='models_dev_cache.etag'
--exclude='.skills_prompt_snapshot.json' --exclude='config.yaml.bak'
```

Keep `config.yaml` and `skills/` — those *are* the profile.

Copy repos with `cp -a` (or `git clone` when the remote is reachable) so
unpushed commits survive. A repo whose `origin` is a local bundle rather than a
forge exists only in the copies — say so when reporting, because nothing backs
it up.

## A profile gets skills by snapshot, not by inheritance

`hermes profile create --clone` copies the **bundled** skill set into the new
profile's own `skills/` directory. It does not give the profile the home's
`skills.external_dirs`, and a profile never reads the home's `skills/`.

So any skill authored outside the bundle — anything living in a mounted library
— is **invisible to every profile** until that profile's own `config.yaml` sets
`skills.external_dirs`. There is no error and no warning: the agent simply never
sees the skill, and a persona whose rubric tells it to load one proceeds without
it. A workflow can therefore look fully installed while missing its tooling, and
the only symptom is the agent behaving as though the skill did not exist.

Verify per profile rather than assuming, and check that `external_dirs` is
actually *active* — the default config ships it commented out, so a grep hit can
be a comment:

```bash
find "$HERMES_HOME/profiles/<name>/skills" -name SKILL.md | wc -l
grep -A3 '^skills:' "$HERMES_HOME/profiles/<name>/config.yaml"
```

Two consequences when porting:

- Set `skills.external_dirs` on **each profile that needs the library**, not
  just on the home, and point it at a path that exists on the new host.
- The snapshot is frozen at creation time. A profile created before a skill was
authored never gains it; re-running the workflow's installer, or adding the
mount, is what closes the gap.

## Config is usually portable as-is

Scan every config file for platform-specific strings before assuming a rewrite
is needed. A typical home is fully portable: `~`-based paths, no drive letters,
no absolute interpreter paths. Walk the main config and every
`profiles/*/config.yaml`, collecting string values that match `C:\`, `C:/`,
`\\`, `AppData`, `/c/`, `.exe`. Zero hits means copy verbatim — do not invent a
rewrite.

Two settings to reconcile deliberately rather than silently:

- `terminal.backend` — `local` vs `docker`. They differ in isolation; do not
  let a copy quietly downgrade one to the other. Weigh whether the container
  backend earns its keep first: on a host that is already a VM boundary (WSL2)
  it adds an image, a runtime and a mount for the store the analyzers live in,
  in exchange for isolation you already have. The backend is named `docker` but
  resolves its runtime as `HERMES_DOCKER_BINARY` → `docker` → `podman`, so Podman
  is a first-class drop-in (daemonless on Linux); on NixOS it needs
  `virtualisation.podman.enable = true`, not just the package on `PATH`.
- `skills.external_dirs` — must point at a path that exists on the *new* host,
  on the home **and** on every profile that needs it (see above).

## Verify after copying

- `hermes profile list` — every expected profile appears. A profile directory
  with no `config.yaml` is a stub, not a profile, and will not list.
- Skill name collisions: local (`$HERMES_HOME/skills`) outranks external
  (`skills.external_dirs`), so a collision means the local copy silently wins.
  Diff the two sets of `SKILL.md` directory names; count both.
- **Compare each profile's skill count against the library's.** A profile showing
  the bundled count only, with a library that holds more, is missing the mount —
  the failure is silent, so measure it rather than inferring it.
- Run one real agent turn under a profile (`hermes -p <profile> chat -q ...`) and
  confirm it completes. A roster entry proves nothing about credentials.
- When a workflow depends on external analyzers, confirm the probes actually
  ran on the new host rather than falling back to "tool absent" — that fallback
  is silent and looks like a clean result.

## Re-sync after the copy

If the source home stays live — and during a migration it does, because the
session doing the work runs on it — anything mutable diverges the moment you
touch it. A memory write or config edit after the copy leaves the destination
stale.

Re-copy `memories/`, `config.yaml` and `SOUL.md` at the end, and verify by size
or hash rather than assuming. A stale `MEMORY.md` on the backend is invisible
until a session there acts on outdated facts.
