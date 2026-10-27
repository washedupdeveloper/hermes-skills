# Spec Delta

## MODIFIED Requirements

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