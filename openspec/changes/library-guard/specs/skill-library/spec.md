# Spec Delta

## ADDED Requirements

### Requirement: The skill contract has one home

The values that make a skill valid — the required frontmatter, the description index window, the
category set — SHALL be read from `library/contract.json` by every enforcer, and SHALL NOT be
restated as literals in a second file.

#### Scenario: A rule changes

- **WHEN** `library/contract.json` changes the window or the required field list
- **THEN** the eval tier and `scripts/skill-contract.py` enforce the new value without an edit of
  their own
- **AND** no second file states the previous value as a literal

#### Scenario: The runtime mirror disagrees with the file

- **WHEN** `library_guard.DEFAULTS` differs from `library/contract.json`
- **THEN** `tests/unit/test_library_guard.py` fails, naming the differing key
- **AND** the mirror is only reachable for a distribution installed away from this tree

#### Scenario: A category is added or removed

- **WHEN** a directory exists under `skills/` that the contract does not declare, or the contract
  declares one that is absent
- **THEN** the gate fails naming that category
- **AND** a contract that declares no categories fails rather than passing both scans

### Requirement: The contract is enforced where the writes happen

The repository SHALL enforce the contract's rules at the moment a `SKILL.md` is written, through the
same function the gate uses, and SHALL refuse a write into a skill that Hermes itself ships.

#### Scenario: A skill is written with a broken field

- **WHEN** a `write_file` or `patch` call writes a `SKILL.md` that misses a required field, mismatches
  its directory, exceeds the window, or carries CRLF
- **THEN** the tool result is returned with each violation appended, naming the field and the fix
- **AND** the write itself is not blocked, because the model is still editing the file

#### Scenario: A skill is written cleanly

- **WHEN** the written `SKILL.md` satisfies the contract
- **THEN** the tool result is returned unchanged

#### Scenario: A bundled skill is edited

- **WHEN** a write targets a skill directory whose name is listed in
  `$HERMES_HOME/skills/.bundled_manifest`
- **THEN** the call is blocked with a message naming `hermes update` as the reason the edit would be
  lost
- **AND** a write anywhere else, including this repository's mounted tree, proceeds

#### Scenario: The guard itself fails

- **WHEN** a hook raises
- **THEN** the tool call proceeds and the hook returns no directive, because a guard that can break a
  tool call is worse than a missing one

#### Scenario: The gate and the guard read one file

- **WHEN** the same `SKILL.md` is validated by `scripts/skill-contract.py` and by the runtime hook
- **THEN** both report the same violations, because both call `check_skill_text`