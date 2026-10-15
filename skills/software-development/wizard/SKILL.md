---
name: wizard
description: "Generate a wizard for steps only a human can do."
version: 1.0.0
author: Matt Pocock (mattpocock), adapted by user, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
category: software-development
metadata:
  hermes:
    tags: [wizard, setup, credentials, onboarding, bash, handoff]
    source: mattpocock/skills@v1.3.1
    related_skills: [handoff]
---

# wizard

A **wizard** is a bash script that walks a human, step by step, through a manual
procedure: tedious to do by hand, and tedious to re-explain every time. It opens each
URL, says exactly what to click and copy, captures the values, writes them where they
belong, confirms at every stage, and shows how many stages remain.

Use it for provisioning, credentials, CI secrets, an unfamiliar third-party dashboard,
a one-off migration, or a cutover.

**Do not use it for anything the agent can do itself.** A wizard exists precisely for
the steps that require a human — logging in, approving, clicking through a UI.

## Scope the procedure

Read the repo first; do not ask cold.

- **For setup** — `.env`, `.env.example`, `.env.*`, the README, `docker-compose*`,
  framework config, and `.github/workflows/*` (every `secrets.*` / `vars.*` reference
  is a value the wizard must produce).
- **For a migration** — the current state, the target state, and the irreversible
  actions between them.

Show the user the ordered stages and the values each produces, and let them add,
drop or reorder.

**Done when** every stage is named in order and, for each captured value, you know
(a) where the human gets it, (b) where it is written, and (c) whether it is secret.

## Map each stage's journey

For each stage write the precise path a human follows — which URL, what to do there,
where the value appears, which variable it fills. "Dashboard → Developers → API keys
→ Reveal test key → copy."

Where you do not actually know the current UI or the exact command, **say so** and
ask or check the docs. Never invent steps that may not exist; a wizard that sends
someone to a screen that is not there is worse than no wizard.

## Author it

Copy `templates/wizard-template.sh` to the target path. Replace the example stage with
one `stage` per step, in dependency order, using the library helpers (`stage`, `say`,
`open_url`, `ask`, `ask_secret`, `write_env`, `set_secret`, `set_var`, `pause`,
`confirm`). Set `TOTAL_STAGES`.

Hold the bar the template sets:

- open the URL **before** asking for its value
- `ask_secret` for anything secret (hidden entry)
- `write_env` every persisted value
- `set_secret` only what CI actually needs
- `confirm` before any irreversible action
- one focused task per stage — each `stage` clears the screen, so nothing the human
  needs should scroll away

Never hand-edit the library above the `STAGES` marker; that consistency is the point.

A wizard is **ephemeral by default**: built for one run, written to a scratch or
`scripts/` path, deleted when done. Commit it only when the user wants a repeatable
setup path that should live in the repo — then link it from the README so the next
person runs the script instead of asking an agent.

## Verify without running it

- `bash -n <script>`; `shellcheck` if available.
- `chmod +x`.

Do **not** run it end to end — it opens browsers and blocks on human input. Trace it
statically instead: every value from the scoping step is captured and lands where you
said, and every `set_secret` name exactly matches a `secrets.*` reference in CI.

Then tell the user how to run it.

## Verification

- [ ] Every stage traces to concrete instructions a stranger could follow
- [ ] No invented UI steps — anything unknown was asked or checked
- [ ] Secrets use hidden entry and are never echoed
- [ ] Each `set_secret` name matches a real CI reference
- [ ] Library above the marker untouched; `bash -n` clean
