# Skill Library Specification

## Purpose

The contract this repository keeps with the agent that loads its skills: one home per fact,
a validated frontmatter, and generated copies that are never edited by hand.

## Requirements

### Requirement: One home per fact

A rule SHALL exist in exactly one skill. A second copy is either a pointer or a check, never
restated prose.

#### Scenario: A repeated rule

- **WHEN** a rule is found in two skills
- **THEN** one of them is reduced to a pointer or replaced by a check
- **AND** the remaining home states the rule whole

### Requirement: Every skill validates

Each `SKILL.md` SHALL carry `name`, a `description` of at most 57 characters starting with a
trigger, `version`, `author`, `license`, and `platforms`; and each skill directory SHALL sit
under a known category.

#### Scenario: The validator runs

- **WHEN** `scripts/validate_skills.py` runs over `skills/`
- **THEN** it reports every skill valid
- **AND** the repository's gate fails on any invalid skill

### Requirement: A generated copy is not a source

The council skill SHALL be generated from `review-council` and synced; a lesson written into
the copy alone SHALL be ported into the source before the next sync.

#### Scenario: A sync overwrites the copy

- **WHEN** `council setup skill` runs
- **THEN** every deployed file matches its source byte for byte
- **AND** a lesson that existed only in the copy is first moved into the source
