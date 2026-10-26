# Spec Delta

## MODIFIED Requirements

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

## ADDED Requirements

### Requirement: A spec names only paths that exist

Every repository-relative path a spec names SHALL exist in the tree, and the suite SHALL fail
naming the spec and the path when one does not.

#### Scenario: A spec names a file that is not there

- **WHEN** a spec under `openspec/specs/` names a path that does not exist
- **THEN** the suite fails, naming that spec and that path

#### Scenario: Every path a spec names exists

- **WHEN** every path named in the specs exists in the tree
- **THEN** the check passes
