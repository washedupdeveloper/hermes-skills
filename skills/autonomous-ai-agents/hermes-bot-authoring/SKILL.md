---
name: hermes-bot-authoring
description: "Author Hermes Bots: personas, capability sets, rubrics."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [hermes-agent, bots, profiles, personas, soul-md, capabilities, toolsets, multi-agent]
    related_skills: [project-kickoff-planning]
---

# Authoring Hermes Bots

A **Bot is a Hermes profile** — isolated config, memory, skills, and credentials under
`~/.hermes/profiles/<name>/`. Bot Mode is a UI over that primitive, so "create a specialist bot"
means: create a profile, then give it a persona (`SOUL.md`), a capability set (toolsets), and a
rubric (a skill).

## When to Use

- Creating or configuring specialist agents, a bot roster, or a multi-agent team.
- Giving an agent a persona (`SOUL.md`), a restricted capability set, or a rubric.
- Turning a hand-made agent into a version-controlled, reinstallable definition.

Not for planning a whole project — use `project-kickoff-planning` for that, and load its
`hermes-multi-agent-design` reference for the design layer of a multi-agent pipeline. Not for moving
a bot roster to another machine — use `hermes-project-handoff`.

## Procedure

1. **Create the profile.**
   ```bash
   hermes profile create <name> --clone --no-alias --description "<one-line role>"
   ```
   - `--clone` copies `config.yaml`, `.env`, `SOUL.md`, `skills/` from the ACTIVE profile —
     including the source `SOUL.md` you are about to replace.
   - `--no-alias` skips wrapper-script creation (use when the bot is invoked as `hermes -p <name>`).
   - `--description` is read by the kanban orchestrator for routing; keep it a real role sentence.

2. **Configure a profile that is NOT active.** Prefix every command with `HERMES_HOME=<abs profile dir>`:
   ```bash
   HERMES_HOME="<profiles>/<name>" hermes config set <key> <value>
   HERMES_HOME="<profiles>/<name>" hermes tools list     # verify the result
   ```
   Plain `hermes config set` edits the ACTIVE profile only. On Windows pass forward-slash native
   paths (`C:/Users/...`).

3. **Capabilities are the toolset list.** Set it explicitly:
   ```bash
   HERMES_HOME="<dir>" hermes config set platform_toolsets.cli '["file","terminal","skills"]'
   ```
   An explicitly-saved list (even `[]`) is **authoritative** — it overrides the platform default
   bundle. This is how you build a **leaf** agent: simply omit `delegation`, `kanban`, `cronjob`.
   Give `delegation` only to the orchestrator.

4. **Register it as a Bot** so it appears in the desktop roster. Write `<profile>/profile.yaml`:
   ```yaml
   description: "..."
   description_auto: false
   ui_meta:
     hermes-bots:
       title: Human Readable Name
   ```

5. **Write the persona** to `<profile>/SOUL.md` (schema below).

6. **Install the CORE skills; declare the OPTIONAL ones.**
   `<profile>/skills/<name>/SKILL.md` is a **core** skill: copied in, always
   present, always loaded — the bot cannot do its job without it. Skills it may
   need only sometimes are **optional**: never copied, resolved by name from the
   mounted library via `skills.external_dirs`, and loaded on demand. Declare both
   lists in the version-controlled source so the installer can act on them.

7. **Keep a version-controlled source of truth.** Keep `bots/<name>/{SOUL.md,profile.yaml,bot.yaml}`
   and `skills/<rubric>/SKILL.md` in a repo, plus an **idempotent** install script that re-copies
   them into the profiles and reapplies the config. Never hand-edit a profile's `SOUL.md` — the next
   install overwrites it.

## Pitfalls

- **`SOUL.md` is a protected agent-instruction file.** A `write_file` to it raises an approval prompt;
  if it times out the write is **BLOCKED**, and you must not retry it or route around it via another
  path. Because `--clone` copies a `SOUL.md` you then must replace, get explicit approval before
  writing personas — and before creating a batch of profiles.
- **`write_file` refuses to overwrite an existing file the session has not read.** Read it first, or
  `rm` it and write fresh. Applies to profile files as much as repo files.
- **A fan-out larger than 2 children is refused in a one-shot run.**
  `delegation.oneshot_max_children` defaults to `2` and is a **cumulative per-session** budget for
  `hermes chat -q`; the model gets a **tool error**, not a partial result, and a well-behaved agent
  then does the work inline (and may describe the run as if the children had executed). Set
  `delegation.oneshot_max_children=0` (unlimited) on any orchestrator profile.
  `delegation.max_concurrent_children` (default 10) is the separate *per-call* batch cap.
- **`--clone` copies the source `.env`** (credentials). Fine for same-machine bots; never ship a
  cloned profile's `.env`.
- **Restricting capabilities is a config edit, not a code change.** Verify with `hermes tools list`
  under the right `HERMES_HOME` — a bare command shows the *active* profile's list, which is how a
  restriction looks like it did not apply.
- **Split a bot's skills into a static core and an optional on-demand set.** Core = what it cannot
  function without: install those explicitly and make the installer *refuse* to build a member whose
  core skill is missing. A bot that runs without its rubric reviews with nothing and reports nothing,
  silently. Optional = everything else: leave it out of the profile and let the bot load it by name
  from the mounted library when the work calls for it. Both halves cost tokens on every turn if you
  get it wrong — an always-loaded skill's description sits in the bot's index, and a checklist it did
  not need is paid for on every sample. **Choose the core set from an explicit list, never a glob** —
  a glob makes the set a side effect of adding a file to the repo, so a new rubric silently reaches
  every bot. And if a core skill *routes* to an optional one, declare that name too, or the bot is
  told to load something nothing guarantees is reachable.
- **An installer that copies from a read-only source is once-only.** Nix store paths and read-only
  mounts carry mode `0444`, and a mode-preserving copy leaves the *destination* read-only — so the
  second run dies with `EACCES` on the file the first run just wrote. Unlink the destination before
  copying, then `chmod` it back to writable, or the install works exactly once and later runs appear
  to succeed while changing nothing. Prove idempotence by running it twice.

## Where a voice must live to apply at all

`SOUL.md` is **slot #1 of the system prompt**: injected every turn, in every session,
and never chosen by the model. A skill is chosen per task and may not be chosen — so a
*standing* communication contract ("always be concise", a house voice) belongs in
`SOUL.md`. Put it only in a skill and it applies when the model happens to pick that
skill, which is a suggestion, not a voice.

- **A profile is its own `HERMES_HOME`.** Hermes reads `SOUL.md` only from
  `$HERMES_HOME`, so the global `~/.hermes/SOUL.md` does **not** reach a bot. A profile
  with no `SOUL.md` of its own has no voice — ship one per member.
- **Read once, at session start.** An edit does not reach a session already running:
  the identity slot is part of the cached prefix. Verify in a NEW session, not the one
  you edited from.
- **Always-on means always paid.** Budget it like an always-loaded pointer — keep only
  the rules that change behaviour, and put the long form in an on-demand skill the
  `SOUL.md` names. A few hundred tokens per turn is the price of it actually applying.
- **A repo cannot inject it, only carry it.** Version-control the voice as a delimited
  fragment plus the one-line extraction command, and apply it per machine. A global
  voice and a bot voice then become two applications of one text instead of two copies
  that drift.
- **`--clone` inherits the ACTIVE profile's `SOUL.md`.** A new bot silently starts with
  the wrong voice until you replace that file — read the inherited one rather than
  assuming a fresh default.

## Persona schema (`SOUL.md`)

Write personas as **prompts for a model**, not documentation for a human. Every line must change
behaviour or be deleted. Use one fixed schema so no bot can be misread:

| Section | Purpose |
|---|---|
| one-line stance | Identity + default posture; resolves ambiguity before any rule is read. |
| `## Rules` | Numbered. Each is a claim AND the action it forces. No rule without a consequence. |
| `## Targets` | The concrete patterns this role looks at — turns an attitude into a checklist. |
| `## Refusals` | Failure modes the persona must not fall into (prevents sycophancy and padding). |
| `## Output` | The exact artifact to emit. Without it a persona produces prose, not findings. |
| `## Iterate until` | The exit condition: criticise → propose fix → re-check → resolved or escalated. |

Schema rules: **no ambiguity, no pedanticism, no waste.** Define shared doctrine, contracts, and
taxonomies ONCE in a framework document and reference them — never restate them in every persona.
See `references/persona-schema.md` for the skeleton, a worked example, and the user's standing bar.

## Verification

- `hermes profile list` shows the new profile(s).
- `HERMES_HOME=<dir> hermes tools list` shows exactly the intended toolsets enabled.
- The persona in the profile is byte-identical to the repo copy (`wc -c` both).
- Smoke run: `hermes -p <name> chat -q '<one task that exercises the rubric>'`.
