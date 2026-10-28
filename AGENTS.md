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
nix flake check                    # the gate: eval + run tiers
python3 scripts/verify-live.py     # the REAL hermes loads every skill
python3 scripts/claim-audit.py     # exit 1 on any false claim
```

`nix flake check` is the whole gate, in two tiers: what the tree *says*
(`nix/tests.nix`, milliseconds) and *behaviour* (`nix/checks.nix` — the Python
suite, the prose claims, `setup.sh` against a stub). The rule is that an
assertion belongs in the cheapest tier that can make it, so a new check goes in
`nix/tests.nix` unless it needs an interpreter.

There is no build tier because there is no artifact: Hermes reads this tree in
place through `external_dirs`. A check that simulated an installer was deleted
rather than kept — see `nix/checks.nix`.

`scripts/verify-live.py` is the end-to-end check: it asks the real `hermes`
binary whether it discovers every catalog skill, and exits 2 when `hermes` is not
installed so it cannot be mistaken for a pass. It honours `environments:`, which
is Hermes' own offer-time gate — `hermes-s6-container-supervision` is *correctly*
absent outside an s6 container.

`nix flake check` sees only **git-tracked** files. A reference file that exists on
disk and is not `git add`ed is absent from the store copy, so a skill pointing at
it fails with a path that looks present — `git status` is the first check, and
`git add` is the fix.

It checks the mechanical claims in this repo's prose — counts, links, the description
ceiling, the setup script's behaviour — and classifies each `PROVEN` / `FALSE` /
`UNPROVEN`. A claim that cannot be checked from the repo alone must say so rather than
be asserted.

## Specs (OpenSpec)

A behavior change starts in `openspec/changes/<name>/` (proposal, spec delta, tasks), not in
code. `openspec list --specs` before proposing; `openspec validate <name> --strict` before
applying and before archive; `openspec archive <name> --yes` when the work lands.
Procedure: the `openspec` skill. Pure refactors and dependency bumps set `skip_specs: true`.

The CLI is not installed on this machine, and CI installs it per run. Both pin the same exact
version — 1.15.0, the one ADR 0008 was verified against — because `@1` is a range that resolves to
whatever 1.x is current, which is the mutable reference ADR 0005 rejects:

```bash
nix shell nixpkgs#nodejs_22 -c npx -y @fission-ai/openspec@1.15.0 <verb>   # e.g. validate --all --strict
```

Bumping it is a one-line change in every file `nix/pins.nix` lists under `openspecCliSites`, plus
the CI job, which the gate finds by reading the workflows directory. `nix/pins.nix` is the one
source: `nix flake check` fails, naming the path and line, if any of them carries a range, a bare
major, or no version at all — and it fails if a file starts naming the package without being listed
there, so a new adoption site is a failure rather than a silent copy. It also fails if a workflow or
the shipped template pins a `-latest` runner, or uses an installer the gate cannot read.

