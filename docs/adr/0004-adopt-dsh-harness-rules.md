# Adopt four harness rules from DeepSeek Harness, reject its framework

DeepSeek Harness (`dsh`) was read as a design document: an all-plugin TypeScript harness
built on Cordis, where the model adapter, the tool registry, the session log and the agent
loop are all replaceable plugins. Four of its rules are adopted here as Hermes practice and
as a skill (`agent-harness-design`); the framework itself and three of its habits are
rejected, with the reason.

**Adopted, because this repo can already fail a gate on each one.**

1. **A registration is an effect.** Every contribution returns a disposer, and teardown
   unwinds it. The defect it prevents is the one this repo already knows: `setup.sh` merges
   `skills.external_dirs` instead of overwriting, because a contribution that cannot be
   unwound is a contribution you cannot remove.
2. **Model-visible means logged.** Anything reaching a model request must be
   reconstructable from the session log. This repo writes skills that change what the model
   sees on every turn; a rule that is not in the log cannot be audited after the fact.
3. **Wire each invariant into a gate, with a negative control.** The eval tier already
   exercises the description window at 57 and 58 characters rather than inferring it. That
   single test is the pattern; it is now applied to every predicate in `nix/lib.nix` and
   `nix/tests.nix`, so a rule that silently matches everything fails.
4. **One home per fact, with a decision record per decision.** This repo has `docs/adr/`,
   and the failure mode is already visible in ADR-0003: a copy drifts from its source and
   nothing notices. One home, plus a record of what was given up, is the cheapest defence.

**Rejected, each for a measured cost.**

- **Cordis as a dependency.** Adopting the framework to obtain these properties would
  rebuild Hermes around a second runtime; every rule above is a discipline this repo can
  keep without it.
- **Per-file 100% coverage on `src/`.** dsh pays for it across ~60 packages. Here the
  eval tier plus one negative control per rule covers the same claims at milliseconds.
- **Bilingual documentation pairs.** Two files per fact is a second home for the fact, and
  only the pairing gate keeps them equal — exactly the drift ADR-0003 records.
- **Branded ids at every boundary.** Worth it at dsh's package count; overhead in a tree of
  Markdown files.

The transferable rule that made the rest legible: **an assertion belongs in the cheapest
tier that can make it.** This repo already states it in `nix/tests.nix`, which is why the
adoption is an extension of the existing gate rather than a new one.
