# AGENTS.md — working with this skill repo

This repo is the **source of truth for locally-authored Hermes skills**. It is mounted
read-only into Hermes via `skills.external_dirs`. Read `README.md` for the full
contract; this file is the operational short version.

## Hard rules

1. **Do not add, edit, or audit bundled skills.** Anything whose name appears in
   `$HERMES_HOME/skills/.bundled_manifest` is owned by Hermes and refreshed by
   `hermes update`. Two owners for one file is a defect — and an edit here is
   **overwritten on the next `hermes update`**, so the work is lost and the
   divergence is invisible until it bites. Treat the bundled set as out of scope
   entirely: no fixes, no rewrites, no optimisation passes, no critique reports.
   Check with: `grep -q "^<name>:" "$HERMES_HOME/skills/.bundled_manifest"`
   Scope any skill audit to this repo's own `skills/` tree.
2. **Do not add registry/hub skills.** They are owned by their upstream and updated by
   `hermes skills update`.
3. **Do not add a sync script.** Machines mount this repo; they do not push their
   library into it. A copy-back script is how a repo silently becomes a mirror and
   starts deleting skills it does not happen to have.
4. **This repo is the source of truth — and an external mount is NOT read-only.**
   `skills.external_dirs` makes this tree *readable* by Hermes, not protected. The
   background self-improvement review patches an existing skill **in place, wherever
   it is found**, and that includes skills under `external_dirs`. So an unattended
   agent can write here.

   The gate is **git**, not permissions: this repo is tracked, so such a write is
   visible in `git status` / `git diff` and reverts with `git checkout`. Run
   `git status` before committing anything you did not write yourself.

   `skills.create_dir` does **not** cover this — it redirects *new* skills only. It is
   deliberately left unset, so agent-created skills land in `~/.hermes/skills/` and are
   promoted here by hand. `./setup.sh` applies both settings.

## Adding a skill

- One directory per skill: `<category>/<skill-name>/SKILL.md`.
- `SKILL.md` needs YAML frontmatter with at least `name` and `description`; the first
  57 characters of `description` should be a self-contained trigger
  (`Use when <trigger>. <behaviour>.`).
- Keep the description's trigger short — it is what the model sees when choosing a
  skill, and it is the only part that loads before the skill is opened.

## Precedence trap

A skill name that exists both in `$HERMES_HOME/skills/` and here resolves to the
**local** copy, and the copy here is silently ignored. Before adding a skill that
already exists locally, delete the local one — otherwise you edit this repo and see no
effect. The chain and its consequences are stated once, in
[README.md](README.md#adding-or-changing-a-skill).

## Verify

```bash
nix flake check                    # the gate: eval + build + run tiers
python3 scripts/claim-audit.py     # exit 1 on any false claim
```

`nix flake check` is the whole gate. It is three tiers — what the tree *says*
(`nix/tests.nix`, milliseconds), what the *shipped artifact* carries
(`nix/checks.nix`, seconds), and *behaviour* (`setup.sh` against a stub, plus the
prose claims). The rule is that an assertion belongs in the cheapest tier that can
make it, so a new check goes in `nix/tests.nix` unless it needs an artifact or an
interpreter.

`nix flake check` sees only **git-tracked** files. A reference file that exists on
disk and is not `git add`ed is absent from the store copy, so a skill pointing at
it fails `skills-shipped` with a path that looks present — `git status` is the
first check, and `git add` is the fix.

It checks the mechanical claims in this repo's prose — counts, links, the description
ceiling, the setup script's behaviour — and classifies each `PROVEN` / `FALSE` /
`UNPROVEN`. A claim that cannot be checked from the repo alone must say so rather than
be asserted.
