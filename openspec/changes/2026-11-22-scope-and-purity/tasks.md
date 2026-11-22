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
- [ ] 9. Populate `scope_answers`, `scope_triggers` and `scope_out`, then make
  them required.
- [ ] 10. Write `scripts/routing-score.py` and record its score.
- [ ] 11. Declare the true `side_effects` for the 11 skills that spawn something
  and add their `**Heads-up.**` paragraphs.
- [ ] 12. Add `install.sh --check`.
- [ ] 13. Archive this change once 8-12 are done.