# AGENTS.md — working in this repo

The source of truth for locally-authored Hermes skills, mounted into Hermes through
`skills.external_dirs`. `README.md` has the full contract; this is the operational short version.

## Hard rules

1. **Not the bundled set.** A name in `$HERMES_HOME/skills/.bundled_manifest` is Hermes's, refreshed
   by `hermes update` — an edit here is overwritten there, and the divergence stays invisible until
   it bites. No fixes, no rewrites, no audits of it; scope skill work to this repo's `skills/`.
2. **Not the hub set.** Registry skills belong to their upstream and update with
   `hermes skills update`.
3. **No sync script.** Machines mount this repo; a copy-back makes it a mirror, and a mirror deletes
   whatever the pushing machine happens to lack.
4. **The mount is readable, not protected.** The background self-improvement review patches an
   existing skill in place, wherever it is found, `external_dirs` included — so an unattended agent
   can write here. The gate is git: such a write shows in `git status` / `git diff` and reverts with
   `git checkout`. Run `git status` before committing anything you did not write.

   `skills.create_dir` redirects *new* skills only, so it does not cover this. It is left unset, and
   agent-created skills land in `~/.hermes/skills/` to be promoted by hand. `./setup.sh` applies
   both settings.

## Adding a skill

- One directory per skill: `<category>/<skill-name>/SKILL.md`.
- Frontmatter carries at least `name` and `description`. The first 57 characters of `description` are
  all the model sees when choosing, so make them a self-contained trigger
  (`Use when <trigger>. <behaviour>.`).

## Precedence trap

A name that exists both in `$HERMES_HOME/skills/` and here resolves to the **local** copy, so edits
here have no effect and nothing says so. Delete the local copy first. The chain is stated once, in
[README.md](README.md#adding-or-changing-a-skill).

## Verify

```bash
nix flake check                    # the gate: eval + run tiers
python3 scripts/verify-live.py     # the real hermes loads every skill
python3 scripts/claim-audit.py     # exit 1 on any false claim
```

`nix flake check` is the whole gate: what the tree *says* (`nix/tests.nix`, milliseconds) and
*behaviour* (`nix/checks.nix` — the Python suite, the prose claims, `setup.sh` against a stub). A new
check goes in `nix/tests.nix` unless it needs an interpreter. There is no build tier because there is
no artifact: Hermes reads this tree in place.

`scripts/verify-live.py` asks the real `hermes` whether it discovers every catalog skill, and exits 2
when `hermes` is absent, so a missing binary cannot be mistaken for a pass. It honours
`environments:` — `hermes-s6-container-supervision` is *correctly* absent outside an s6 container.

`scripts/claim-audit.py` checks the mechanical claims in the prose — counts, links, the description
ceiling, the setup script's behaviour — and classifies each `PROVEN` / `FALSE` / `UNPROVEN`. A claim
this repo cannot settle is labelled, never asserted.

`nix flake check` sees only **git-tracked** files: a reference file on disk but not `git add`ed is
absent from the store copy, so the failure names a path that looks present. `git status` first,
`git add` to fix.

## Specs (OpenSpec)

A behaviour change starts in `openspec/changes/<name>/` — proposal, spec delta, tasks — not in code.
`openspec list --specs` before proposing; `validate <name> --strict` before applying and again after
archiving; `archive <name> --yes` when it lands. Procedure: the `openspec` skill. Pure refactors and
dependency bumps set `skip_specs: true`.

The CLI is not assumed to be on `PATH`: CI installs it per run, and both pin the same exact version —
1.15.0, the one ADR 0008 was verified against. `@1` is a range that resolves to whatever 1.x is
current, which is the mutable reference ADR 0005 rejects:

```bash
nix shell nixpkgs#nodejs_22 -c npx -y @fission-ai/openspec@1.15.0 <verb>   # e.g. validate --all --strict
```

Bumping it is a one-line change in every file `nix/pins.nix` lists under `openspecCliSites`, plus the
CI job, which the gate finds by reading the workflows directory. That file is the one source: the gate
fails, naming path and line, on a range, a bare major or a missing version — and fails if a file
starts naming the package without being listed there, so a new adoption site is a failure rather than
a silent copy. It also fails on a `-latest` runner, or on an installer it cannot read.