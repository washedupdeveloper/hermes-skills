# Tasks

## Contract and gate

- [x] 1. Add `writes` (two tiers), `side_effects`, `container_runtime`,
  `domain_contract` and `aliases` to `library/contract.json` as `skill-contract/v3`.
- [x] 2. Implement the rules in `scripts/scope.py` and call them from the one gate.
- [x] 3. Give every skill `writes: [none]` and `side_effects: [none]`.
- [x] 4. Add nine negative controls: missing `writes`, absolute root, `/home` in a
  fence, a system path that is only reported, a declared root without a heads-up,
  the same skill announced, an unknown side effect, an unmarked `docker`, and a
  marked one.

## Domains and runtime

- [x] 5. Write `CATEGORY.md` for the seven current domains.
- [x] 6. One runtime policy in `docs/runtime.md`; nine skills carry a pointer
  instead of the duplicated paragraph; the gate rejects an unmarked `docker` call.
- [x] 7. Correct `docs/milestone.md`, which named a `setup.sh` that never existed.

## Open

- [ ] 8. Move seven domains to ten: add `build`, rename the rest, update the
  README layout tree and the contract in one commit per domain.
- [ ] 9. Populate `scope_answers`, `scope_triggers` and `scope_out`, then make them
  required. **Partial:** the fields, the rule and its four controls are in
  (`scope_required: false`); nine skills carry a scope — `communication` (7),
  `note-taking` (1), `productivity` (1). The remaining 61 are unpopulated, so the switch
  stays off, and it cannot be turned on until they are. Which fields a long skill needs is
  a judgement per skill, not a mechanical fill.
- [x] 10. Write `scripts/routing-score.py` and record its score. 74/74 (100%) over a
  corpus of 74 prompts, floor 1.0 in `library/routing.json`, and the gate runs it with
  `--strict`: a tie, a miss, or a score below the floor fails the build.
- [x] 11. Declare the true `side_effects` and `**Heads-up.**` paragraphs. The premise
  said eleven skills; audited against the tree, thirteen mention a spawning command and
  ten of those document or check rather than act. Three instruct an effect:
  `hermes-remote-backend` [systemd, port], `hermes-wsl-backend` [systemd, port,
  background-process], `nixos-clan-flake` [container].
- [x] 12. Add `install.sh --check`: verify an existing install (present, pointing here,
  not stale) and exit 1 on any problem, without writing.
- [ ] 13. Archive this change once 8-12 are done.

## Found while running the gate

- [x] 14. Enforce LF in three places rather than by habit: `.editorconfig` (the
  editor), `.githooks/pre-commit` (refuses a staged CRLF file by name) and
  `scripts/dev-setup.sh` (the per-clone keys in one command).
- [x] 15. Adopt `openspec/SKILL.md` into `pins.openspecCliSites` so its pinned
  version is checked against `pins.nix`, write its two invocations as exact
  versions in a fence, and backtick the bare `npx` that the installer rule read
  as a package spec.
- [x] 16. Drop the invalid escape in `tests/e2e/test_gate_mutants.py`
  (`"\${{"`), which was a `SyntaxWarning` and a future error.

## Evidence

Re-run on 2026-11-26 under this repository's current loop. Every row is a command that was
run against this tree on that date, not a restatement of the original tick.

| claim | command | result |
|---|---|---|
| the contract is v3 and the gate reads it | `grep -m1 '"schema"' library/contract.json` | `"skill-contract/v3"` |
| every skill declares `writes` | `grep -l "^writes:" $(find skills -name SKILL.md) \| wc -l` | 70 |
| every skill declares `side_effects` | `grep -l "^side_effects:" $(find skills -name SKILL.md) \| wc -l` | 70 |
| all seven domains carry `CATEGORY.md` | `ls skills/*/CATEGORY.md \| wc -l` | 7 |
| the scope rules are one module in the gate | `grep -c "from scope import" scripts/validate.py` | 1 |
| the gate accepts the tree | `python scripts/validate.py` | `validate: 0 violation(s)` |
| every effect-instruction is declared | `python scripts/validate.py` | 0 violations |
| a scope is all three parts, or a failure | `pytest tests/unit/test_validate.py -q -k scope` | 7 passed |
| a named task selects exactly one skill | `python3 scripts/routing-score.py --strict` | 74/74, floor 100% |
| the scorer can fail | `pytest tests/unit/test_routing.py -q` | 5 passed |
| the catalog carries a scope where populated | `grep -l scope_answers $(find skills -name SKILL.md) \| wc -l` | 9 of 70 |
| `$XDG_CONFIG` is allowed and redirectable | `pytest tests/unit/test_validate.py -q` | 142 passed |
| `--check` verifies and never writes | `pytest tests/e2e/test_install_check.py -q` | 3 passed |
| a matching install passes | `sh install.sh $(mktemp -d) --check` | exit 0 |
| a missing or foreign entry fails | the two negative scenarios in that file | exit 1, named |
| the delta is structurally valid | `nix run .#openspec -- validate 2026-11-22-scope-and-purity --strict` | 1 passed |

### What the re-run found

- **Two uncommitted files were failing the validator** (CRLF in
  `skills/devops/nix-flake-checks/`). Normalised to LF, content untouched. The gate could
  not report 0 violations while they stood, so every evidence row above depended on it.
- **`docs/sdd.md` did not exist when this change was proposed**; the loop it states now
  applies to this change's remaining tasks (a test per scenario, an evidence row per task).
- **Task 11 needs a rule before it needs edits** — see `design.md`, "Decisions still open".
