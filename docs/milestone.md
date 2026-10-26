# hermes-skills — Milestone Plan

**Goal.** This repository is the source of truth for the skills we author, and every promise it
makes about itself is a check that fails when the promise breaks — on any clone, not only on the
machine that wrote it.

**How to read this.** The claims below are the milestone. Each is settled by running something, so
"reached" is a measurement rather than an opinion. Anything this machine cannot settle is named as
such rather than assumed.

## Definition of reached

From a clean clone of `origin/main`:

| Claim | Settled by |
|---|---|
| the tree has the shape the specs describe | `nix flake check` (eval tier, `nix/tests.nix`) |
| every catalog skill loads in the real Hermes | `python3 scripts/verify-live.py` — 44 catalog skills, 43 expected on a host, 1 correctly hidden by `environments:` |
| every mechanical claim in the prose is true | `python3 scripts/claim-audit.py` — exit 0, 0 FALSE |
| the specs validate | `openspec validate --all --strict` |
| every path a spec names exists | `python3 -m pytest tests/unit/test_docs.py` |
| the layout the README declares is the layout on disk | the same suite |
| the initializer applies the declared state | `./setup.sh --check` — exit 0 |
| CI enforces the above on every push | the six jobs in `.github/workflows/ci.yml` green on the pushed SHA |

## Status

**Reached, 2026-10-26.** Every row above passes on the tree, and CI closed the last one: pushed as
`a54abdd` and `68b7a81`, and all nine check runs on `68b7a81` concluded success — `nix flake check`,
the three-OS test matrix, `claim audit`, `openspec validate --all --strict`, `setup.sh` e2e on two
systems, and `live hermes`.

The CI row needed the push rather than a sentence: `origin/main` carried no `openspec` job when this
was written, and 27 commits were unpushed, so the spec gate had never run anywhere but a
workstation. A milestone whose enforcement exists only on one machine is a local convention.

## The gaps that stood in the way

Ordered as they were closed, each one a defect rather than a task:

1. **No target existed.** The question "what is missing to reach the milestone?" has no referent
   without this document, and `grep -rni milestone` found nothing in the tree.
2. **A spec named a file that never existed.** `openspec/specs/skill-library/spec.md` had a
   scenario running `scripts/validate_skills.py`; frontmatter is gated by `nix/tests.nix` and that
   script was never written. `validate --strict` passes on shape, so nothing caught it. Closed by
   naming the gate, and by a new requirement that a spec's paths exist.
3. **"A known category" had no referent.** Nothing declared the category set, and the README layout
   tree — which readers take as that declaration — omitted `note-taking/`. Closed by parsing the
   tree in the suite and comparing it with the filesystem both ways.
4. **The README's ADR ledger was two entries behind** (`docs/adr/` held eight, the table six).
   Closed by listing every ADR and asserting the table against the directory.
5. **The spec gate was not on the remote.** ADR 0008 says enforcement is the repository's CI job;
   the workflow on `origin/main` had no `openspec` job at all. Closed by pushing.
6. **The CLI was not on PATH**, so the `validate --strict` that `AGENTS.md` requires could only run
   in CI. Closed by documenting the pinned invocation in `AGENTS.md`.

## Reached means the check would fail

A gate nobody has seen fail is decoration. Each new assertion was exercised against the broken case
before it was trusted:

- the spec-path check failed on the real defect, naming
  `openspec/specs/skill-library/spec.md: scripts/validate_skills.py`;
- the layout check failed on a README tree missing `note-taking/` (and on its first form, which
  parsed one category of seven because `re.M` was missing from the pattern);
- the ADR check fails if a row is dropped from the table or a file is added to `docs/adr/`;
- the spec-path check fails on an emptied `openspec/specs/` rather than passing over
  nothing, which is the only way that check could have been vacuous.

## Deferred on purpose

- **`verify-live.py` in the flake gate.** It needs the real Hermes binary, so it is a CI job and
  cannot be a `nix flake check`. Stated in `nix/checks.nix`, not worked around.
- **Scanning `openspec/changes/` for paths.** A delta names the files it is about to create, so the
  check would fail on the work it exists to allow. The live spec is the contract.
- **A devshell pinning the OpenSpec CLI.** The documented `nix shell nixpkgs#nodejs_22 -c npx -y
  @fission-ai/openspec@1` invocation is enough for one repository; a devshell is worth adding when a
  second consumer needs the same pin.
- **A `scripts/validate_skills.py`.** Writing it would give frontmatter a second owner beside
  `nix/tests.nix`. The requirement names the gate instead.
