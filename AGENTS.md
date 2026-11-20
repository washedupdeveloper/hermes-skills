# AGENTS.md — working in this repository

The source of truth for the skills this library ships. A host reads this tree by one of two routes:
a mount it declares once (`external_dirs`, a symlinked skills directory), or a copy made by
`./install.sh`. `README.md` has the full contract; this is the operational short version.

## Hard rules

1. **Not what a host ships.** A skill directory named in a host's bundled manifest is that host's,
   refreshed by its own updater — an edit here is overwritten there, and the divergence stays
   invisible until it bites. Identify the class before touching a skill.
2. **Not what a registry owns.** An installed skill belongs to its upstream and updates with the
   registry's own command. Reference it (see `docs/upstream.md`); do not vendor it.
3. **No sync script.** Hosts mount this repo or link it; nothing copies the library back. A
   copy-back makes it a mirror, and a mirror deletes whatever the pushing machine happens to lack.
4. **A mount is readable, not protected.** An unattended writer — a self-improvement review, another
   agent — can patch an existing skill in place, wherever it is found. The gate is git: such a write
   shows in `git status` / `git diff`. Run `git status` before committing anything you did not write,
   and stage explicit paths rather than `git add -A`.
5. **The contract is one file.** `library/contract.json` holds the required frontmatter, the index
   window, the category set, the hosts and the external skills. `scripts/validate.py` reads it; no
   other file restates it. Change a rule there, never in two places.

## Line endings

LF everywhere — in the repository and in the working tree, on every host. The tree is mounted into
WSL and Linux, where a CRLF shebang fails as `bad interpreter: …^M`, and a CRLF/LF pair reports
drift that is not there.

`.gitattributes` (`* text=auto eol=lf`) is the tracked half: it overrides `core.autocrlf`, so a
Windows checkout is byte-identical to a Linux one. The other half is per clone, because git does not
track its own config:

```bash
git config core.autocrlf false
git config core.eol lf
git config core.safecrlf true    # git add refuses a CRLF file instead of normalising it silently
```

`safecrlf` is what makes this a check rather than a convention: a writer that emits CRLF fails at
`git add` with `fatal: CRLF would be replaced by LF in <path>`, naming the file, and nothing is
staged. Without it the blob is normalised, `git status` goes clean, and the file on disk keeps its
CRLF — the failure this repository has hit twice, invisible until a script breaks in WSL. Fix the
file (`tr -d '\r' < f > f.lf && mv f.lf f`), never the check.

The gate cannot do this job: `nix flake check` and CI both read a git-tracked tree, which is already
LF, so worktree CRLF is visible to neither.

## Adding a skill

- One directory per skill: `skills/<category>/<name>/SKILL.md`, `<name>` equal to the directory.
- Frontmatter carries at least `name` and `description`. The first 57 characters of `description`
  are all an agent sees when choosing, so make them a self-contained trigger
  (`Use when <trigger>. <behaviour>.`).
- A skill that only makes sense inside one host declares `targets: [<host>]` and gets a row in the
  README's host-scoped table.
- Support files live in `references/`, `scripts/`, `templates/`, `assets/` beside the skill, and are
  cited by relative path from the skill's own directory — a pointer that climbs out of it dangles
  wherever the skill is read on its own.

## Precedence trap

A host that resolves a local skills directory before a mounted one will read the local copy
silently: edits here then appear to do nothing. Keep names unique across the two, and delete a local
copy when a skill moves in.

## Work communication

Every non-trivial work item, task assignment, status update and handoff is an OpenSpec change:

- Start with `openspec/changes/<name>/`; its proposal and `tasks.md` are the authoritative brief.
- A subagent brief names the change and the task IDs it owns. It does not carry a second prose brief
  that contradicts the change.
- A subagent returns the same change and task IDs, the files it changed, and the evidence commands
  it ran.
- Chat is a short pointer to the change, never the only record of the work.
- Pure refactors and dependency bumps use `skip_specs: true` when behavior does not change.

Use the `openspec` skill for the loop: `openspec instructions`, `openspec validate --strict`, and
`openspec archive`. The CLI is pinned to 1.15.0 in CI.

## Dependency maintenance

Dependency sources have a weekly automated check: Dependabot for GitHub Actions and Python, and
the `dependencies` workflow for the Nix flake lock. Updates are pull requests; CI must pass and a
human merges them. No workflow enables auto-merge.

## Verify

```bash
./scripts/ci-local.sh                  # every CI job this machine can run, in order
python3 scripts/validate.py            # every rule, over the whole tree
python3 -m pytest tests/ -q            # the code the skills ship, and the gate's negative controls
python3 scripts/claim-audit.py         # exit 1 on any claim in the prose that is FALSE
nix flake check                        # optional: the same gate under a pinned toolchain
```

`python3 scripts/validate.py` is the gate. It needs nothing but a Python 3 standard library, which is
the whole point of this repository's shape — a contributor on any OS runs the same command CI runs.
Exit 1 names each violation with its file; exit 2 means the scan found no skills, which is a wrong
directory, not a pass.

`ci-local.sh` runs the workflow's jobs as the commands they are, and names the ones no single
machine can run: the Windows leg unless you are on Windows, and `cost`, which reads a GitHub
run id. The hosted matrix is Linux and Windows only — macOS runners are not on this account's
plan, and GitHub cancels those jobs in a second with nothing run — so a macOS leg has to be run
by hand on a Mac. `nix develop` provides the interpreter, pytest, actionlint and nixfmt.

`nix flake check` runs `validate.py`, the Python suite, the prose audit and the formatter, then the
eval-tier assertions about this repository's own CI (workflow pins, runner labels, the OpenSpec CLI
pin). Those last checks need Nix; nothing about using the library does.

`nix flake check` sees only **git-tracked** files: a support file on disk but not `git add`ed is
absent from the store copy, so a skill citing it fails as a dead reference while the file sits beside
it. `git status` first, `git add` to fix.

## Specs (OpenSpec)

`openspec/` holds the decision records this repository already made — a change's proposal, spec
delta and tasks. A behaviour change to the gate or the layout starts there. The CLI is pinned exactly
(1.15.0 in `nix/pins.nix` and the CI job) because a range resolves to whatever the range is now;
`@1` is the mutable reference ADR-0005 rejects.

```bash
nix shell nixpkgs#nodejs_22 -c npx -y @fission-ai/openspec@1.15.0 validate --all --strict
```
