---
name: hermes-profile-fleet
description: "Install and package a fleet of Hermes profiles portably."
version: 1.1.0
author: user, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
category: autonomous-ai-agents
metadata:
  hermes:
    tags: [hermes, profiles, multi-agent, packaging, portability, installation, orchestration]
    related_skills: [council, hermes-agent]
---

# hermes-profile-fleet

Package a set of specialist Hermes profiles — an orchestrator plus workers, with
the skills, scripts, and gate they need — as one portable, slash-invokable
distribution that installs on any machine with no repo clone and no hardcoded path.

## When to Use

- Building or maintaining a multi-profile system: an orchestrator that fans out to
  specialist workers.
- Making such a system installable by someone else, or from another machine.
- Diagnosing why a profile run fails immediately after an install or import (auth,
  toolsets, missing skills, missing shell).

## Rules (always on)

**Never hardcode a machine path.** Resolve everything at runtime:

- The skill's own directory: `skill_view(name=...)` returns `skill_dir`. Fall back
  to `$HERMES_HOME/skills/<category>/<name>`.
- The Hermes home: `hermes profile show default` prints `Path:`, and that **is** the
  home — profiles live at `<home>/profiles`. `hermes config get home` does not
  exist; never build a resolver on it. Env fallbacks in order: `HERMES_HOME`, then
  `%LOCALAPPDATA%\hermes` (Windows), then `~/.hermes`.

**Bundle the assets inside the skill.** Ship `scripts/` and `assets/` (profile
personas, rubrics, config fragments) under the skill directory so an install needs
no clone. Have the install script probe for **both** layouts — `<root>/bots` +
`<root>/skills` in the repo, `<root>/assets/bots` + `<root>/assets/rubrics` in the
installed skill — so the same script works from wherever it sits.

**A profile export/import never carries credentials.** `hermes profile export`
excludes `.env` by design. After an import, or after `profile create --clone`, a
profile has no working key until you provision one. Treat an HTTP 401 right after
install as a provisioning step, not as breakage.

**An imported profile can carry a provider that does not resolve.** If
`model.provider` names a provider with no matching `custom_providers` entry, the
request goes out with a placeholder key and the endpoint rejects it. Repoint
`model.provider` to `custom:<name>` and `model.base_url` at that provider's URL, and
make sure the entry carries `api_key` and lists the profile's model.

**`hermes config set` cannot create a `custom_providers` entry.** To add or edit one,
round-trip the profile's `config.yaml` with a comment-preserving YAML writer
(ruamel — the writer Hermes itself uses), and back the file up first.

**A skill becomes `/<name>` from its frontmatter `name`,** and only when it lives
under the active `$HERMES_HOME/skills/`. A skill written to `~/.hermes/skills/` while
`HERMES_HOME` points elsewhere is invisible — Hermes never scans it. This is silent:
the skill loads fine by path and simply never appears as a command.

**The desktop app memoizes the skill-command table in-process.** A new or renamed
skill does not show up until the app restarts or `/reload-skills` runs. Restarting
before the skill exists in the scanned directory changes nothing.

**Verify with a smoke test, not an assumption.** After install, confirm the fleet
(`hermes profile list`) and prove one profile end to end:

```bash
hermes -p <bot> chat -q 'Reply with exactly: SMOKE_OK'
```

A printed `SMOKE_OK` proves the profile's credentials and model resolve.

## Procedure

1. **Author** the profile definitions in the source tree: persona (`SOUL.md`),
   `profile.yaml`, capability set (toolsets), and each profile's rubric skill.
2. **Sync into the skill's `assets/`** with a script that resolves its destination
   from the Hermes home, so the repo (source of truth) and the skill (distribution)
   cannot drift.
3. **Write the installer** (`scripts/install-bots.sh`): idempotent — create the
   profile only if missing, then always refresh persona, rubric, toolsets, and any
   extra config from the version-controlled definitions. Read either layout.
4. **Install**, then smoke-test each profile.
5. **Provision credentials** per profile (`hermes -p <bot> setup`).
6. **Verify invocation** on the target surface (desktop palette, TUI, CLI).

## Pitfalls

- Reviewers/workers should be **leaves**: no `delegation`, `kanban`, or `cronjob` in
  their toolsets. Only the orchestrator gets those, so a worker cannot fan out on
  its own.
- A one-shot `hermes chat -q` fan-out is capped by
  `delegation.oneshot_max_children` (**default 2**), a cumulative per-session budget.
  Set it to `0` on the orchestrator or any batch larger than two silently fails and a
  well-behaved agent falls back to doing the work inline.
- Installing profiles does not install the *shell* the worker runs commands with. If
  a run reports no shell, that is a Hermes install concern (`hermes pm install`), not
  a fleet concern.
