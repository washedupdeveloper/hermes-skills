# Milestone v3 — scope, purity and domain contracts

**Status: closed.** Contract `skill-contract/v3`. Every row below is enforced by the
gate; the change that carried them is archived at
`openspec/changes/archive/2026-11-22-scope-and-purity`.

| Claim | Settled by |
|---|---|
| every skill declares what it writes, from symbolic roots only | `python3 scripts/validate.py` — exit 0 |
| no fenced command carries a user-space absolute path | the same gate: `/home` and `C:\\Users\\` fail; `/usr`, `/etc`, `/var`, `/opt`, `/srv` are reported, and fail when written to |
| every domain states its question and what belongs elsewhere | the same gate, over `skills/*/CATEGORY.md` |
| no two skills claim the same trigger phrase | the same gate, once `scope_triggers` is populated |
| a new skill always has a home | the procedure: add the domain to `library/contract.json`, write its `CATEGORY.md`, add the README row — the gate fails an undeclared category |
| a prompt that names a task selects exactly one skill | `python3 scripts/routing-score.py --strict` — 74/74 (100%), floor 1.0 in `library/routing.json` |

## What is deliberately not a claim

The tree is **open for extension, closed for modification**: a new skill lands
inside an existing domain without editing another domain, and a new domain is
three additive edits (contract, `CATEGORY.md`, README row). The gate rejects an
undeclared category rather than filing it under a default bucket — a skill that
fits nowhere is a missing domain, not an `other/`.

## Persistence

The rule is not "no system paths". It is **no project state outside the project**.

- **Tier 1 — `$PROJECT`, `$ARTIFACTS`, `$SCRATCH`.** The reader's own tree.
  Artifacts persist under `$PROJECT/.artifacts`; `$SCRATCH` is ephemeral and is
  removed when the work ends. A skill that writes opens with the POSIX preamble
  (`: "${SKILL_PROJECT:=...}"`) so a user redirects output by exporting a
  variable instead of editing the skill.
- **Tier 2 — `$HERMES_HOME`, `$SYSTEM`.** Outside the project. Allowed only when
  the skill also declares `side_effects` and carries a `**Heads-up.**` paragraph
  naming what will appear on the reader's machine.
- `side_effects` is a closed vocabulary — `systemd`, `container`, `port`, `cron`,
  `background-process`, `credential`, `global-package` — so a typo cannot hide a
  daemon. Every skill states the list, `[none]` included.
- Any skill that writes also states `leaves`: the residue a reader should expect.

System paths may be read, cited, or be the subject of a skill; they may not hold
persisted project state.

## What closed this milestone

| item | how it closed |
|---|---|
| the taxonomy move, 7 domains to 10 | `docs`, `build` and `testing` added, one commit each; routing held at 74/74 through every move |
| skills that spawn while declaring `[none]` | audited: thirteen mention a spawning command, ten document or check rather than act, three instruct one, and all three now declare it with a `**Heads-up.**` |
| `scope_answers` / `scope_triggers` / `scope_out` | populated for all 70 skills and made required (`scope_required: true`); 140 trigger phrases, no duplicate |
| the routing measure | built, `scripts/routing-score.py`, 74/74 against a floor of 100%, and run by `nix flake check` |

## What the routing measure does not claim

It scores a prompt that **names a task**. A vague prompt routes to nothing, and that is the
correct answer: "the build is broken" names no task, so no skill should claim it.

Two single-skill domains (`note-taking`, `productivity`) kept their skills and had their
`CATEGORY.md` questions rewritten to match what the skill does, by the owner's decision. A
domain with one honest skill is a small domain; a domain whose question its own skill
cannot answer is a lie the catalog tells about itself.
