# Skill Library Specification

## Purpose

The contract this repository keeps with the agent that loads its skills: one home per fact,
a validated frontmatter, and generated copies that are never edited by hand.

## Requirements

### Requirement: One home per fact

A rule SHALL exist in exactly one skill. A second copy is either a pointer or a check, never
restated prose. A value that must move in lockstep across files — including a pinned CLI version
— SHALL have one machine-readable source, and every adopted copy SHALL be checked against it
rather than maintained as a literal.

#### Scenario: A repeated rule

- **WHEN** a rule is found in two skills
- **THEN** one of them is reduced to a pointer or replaced by a check
- **AND** the remaining home states the rule whole

#### Scenario: A pinned version is copied into a fourth file

- **WHEN** a version this repository tells other repositories to adopt is edited in one file and
  not in the others
- **THEN** the gate fails, naming every file that still carries the previous value
- **AND** the bump procedure the prose describes lists every location the gate checks

### Requirement: Every skill validates

Each `SKILL.md` SHALL carry `name`, a `description` of at most 57 characters starting with a
trigger, `version`, `author`, `license`, and `platforms`; and each skill directory SHALL sit
directly under a category the repository's layout declares.

#### Scenario: The validator runs

- **WHEN** `nix flake check` runs over `skills/`
- **THEN** it reports every skill valid
- **AND** a skill missing a required field, or whose name does not match its directory, fails the
  gate

#### Scenario: The declared layout and the filesystem disagree

- **WHEN** a category exists under `skills/` that the README layout tree does not declare, or one
  the tree declares is absent
- **THEN** the suite fails naming the category

### Requirement: A generated copy is not a source

The council skill SHALL be generated from `review-council` and synced; a lesson written into
the copy alone SHALL be ported into the source before the next sync.

#### Scenario: A sync overwrites the copy

- **WHEN** `council setup skill` runs
- **THEN** every deployed file matches its source byte for byte
- **AND** a lesson that existed only in the copy is first moved into the source

### Requirement: A spec names only paths that exist

Every repository-relative path a spec names SHALL exist in the tree, and the suite SHALL fail
naming the spec and the path when one does not.

#### Scenario: A spec names a file that is not there

- **WHEN** a spec under `openspec/specs/` names a path that does not exist
- **THEN** the suite fails, naming that spec and that path

#### Scenario: Every path a spec names exists

- **WHEN** every path named in the specs exists in the tree
- **THEN** the check passes
