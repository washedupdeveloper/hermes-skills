# Tasks

## Communication contract

- [x] 1. Add the communication rule to `AGENTS.md`.
- [x] 2. Add the work-item/subagent handoff contract to the `openspec` skill.

## Dependency maintenance

- [x] 3. Add weekly Python dependency coverage to Dependabot.
- [x] 4. Add a scheduled Nix flake-lock refresh that opens a CI-gated PR.
- [x] 5. Add tests that guard the weekly schedules and the no-auto-merge rule.

## Close-out

- [x] 6. Run `openspec validate openspec-communication-and-deps --strict`.
- [x] 7. Run the repository gate and archive the change.
