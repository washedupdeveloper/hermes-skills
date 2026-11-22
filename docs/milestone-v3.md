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

## Portability

No skill may assume a location the reader does not choose. A skill that writes
opens with `: "${SKILL_PROJECT:=...}"` (and `SKILL_SCRATCH`, `SKILL_ARTIFACTS`),
so a user redirects output by exporting a variable; nothing is written to the
reader's `$HOME` by default, and the defaults land in the project or a temp dir.
`# portable-ok: <reason>` opts a single line out, and the reason is greppable.

## Open items

- The taxonomy move (7 domains to 10) has not started; `build` is not yet in
  `library/contract.json`'s `categories`.
- `scope_answers`, `scope_triggers` and `scope_out` are specified but neither
  required nor populated.
- The routing measure does not exist yet.
