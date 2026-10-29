# hermes-skills — Milestone

**Goal.** This repository is the source of truth for the skills we author, and every promise it makes
about itself is a check that fails when the promise breaks — on any clone, not only the machine that
wrote it.

Each claim below is settled by running something, so "reached" is a measurement rather than an
opinion.

## Definition of reached

From a clean clone of `origin/main`:

| Claim | Settled by |
|---|---|
| the tree has the shape the specs describe | `nix flake check` (eval tier, `nix/tests.nix`) |
| every catalog skill loads in the real Hermes | `python3 scripts/verify-live.py` — 44 catalog skills, 43 on a host, 1 correctly hidden by `environments:` |
| every mechanical claim in the prose is true | `python3 scripts/claim-audit.py` — exit 0, 0 FALSE |
| the specs validate | `openspec validate --all --strict` |
| every path a spec names exists | `python3 -m pytest tests/unit/test_docs.py` |
| the layout the README declares is the layout on disk | the same suite |
| the initializer applies the declared state | `./setup.sh --check` — exit 0 |
| CI enforces the above on every push | every check run green on the head of `main` |

## Status

**Reached, 2026-10-26; re-measured 2026-10-28.** Every row passes. The measurement is the check-runs
API against the head of `main`, not this sentence: `nix gate`, the three-OS test matrix, `live hermes`,
`claim audit`, `setup.sh` e2e on two systems, `openspec validate --all --strict`, `gate mutants` and
`cost`, all successful.

Reaching it was not the end. Changes have landed since, and the list of them is
`openspec/changes/archive/` — a directory, which cannot go stale the way a count does. Each one closed
a real defect: assertions that caught only the spellings they were written around, rules whose
derivations could not tell a right tree from a wrong one, prose stating figures no clone could settle.

The contract is **16 requirements across two capabilities** — `gate-integrity` (11) and
`skill-library` (5) — measured by **25 mutants**. `openspec validate --all --strict` holds the specs;
`tests/unit/test_milestone_doc.py` holds these two figures, deriving both from the tree so this
paragraph fails the gate the moment it drifts.

## Reached means the check would fail

A gate nobody has seen fail is decoration. Each assertion was exercised against the broken case before
it was trusted:

- the spec-path check failed on the real defect, naming
  `openspec/specs/skill-library/spec.md: scripts/validate_skills.py`;
- the layout check failed on a README tree missing `note-taking/`, and on its first form, which parsed
  one category of seven because `re.M` was missing;
- the ADR check fails if a row leaves the table or a file joins `docs/adr/`;
- the spec-path check fails on an emptied `openspec/specs/` rather than passing over nothing.

## Deferred on purpose

- **`verify-live.py` in the flake gate.** It needs the real Hermes binary, so it is a CI job; stated
  in `nix/checks.nix` rather than worked around.
- **Scanning `openspec/changes/` for paths.** A delta names files it is about to create, so the check
  would fail on the work it exists to allow. The live spec is the contract.
- **A devshell pinning the OpenSpec CLI.** The documented `nix shell` invocation is enough for one
  repository; a devshell earns its place when a second consumer needs the same pin.
- **A `scripts/validate_skills.py`.** It would give frontmatter a second owner beside `nix/tests.nix`;
  the requirement names the gate instead.