# Milestone v3 — scope, purity and domain contracts

**Status: open.** Contract `skill-contract/v3`. Rows 1-4 are enforced by the gate
today; rows 5-6 need the taxonomy move and the routing measure.

| Claim | Settled by |
|---|---|
| every skill declares what it writes, from symbolic roots only | `python3 scripts/validate.py` — exit 0 |
| no fenced command carries a user-space absolute path | the same gate: `/home` and `C:\\Users\\` fail; `/usr`, `/etc`, `/var`, `/opt`, `/srv` are reported, and fail when written to |
| every domain states its question and what belongs elsewhere | the same gate, over `skills/*/CATEGORY.md` |
| no two skills claim the same trigger phrase | the same gate, once `scope_triggers` is populated |
| a new skill always has a home | the procedure: add the domain to `library/contract.json`, write its `CATEGORY.md`, add the README row — the gate fails an undeclared category |
| a prompt that names a task selects exactly one skill | `python3 scripts/routing-score.py` (not built yet) |

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

## Open items

- The taxonomy move (7 domains to 10) has not started; `build` is not yet in
  `library/contract.json`'s `categories`.
- 11 skills spawn something (systemd, containers, `nix profile add`, global npm)
  while declaring `side_effects: [none]`. Declaring them truthfully is the next
  backfill, and each needs its `**Heads-up.**` paragraph.
- `scope_answers`, `scope_triggers` and `scope_out` are specified but neither
  required nor populated.
- The routing measure does not exist yet.
