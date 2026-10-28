# Spec Delta

## REMOVED Requirements

### Requirement: A touched Nix file is formatter-clean

**Reason**: it was a rule about the file a change edits, so it could not see files nobody edits —
four had drifted under it. **Migration**: replaced by "Every Nix file is formatter-clean".

## ADDED Requirements

### Requirement: Every Nix file is formatter-clean

Every tracked Nix file SHALL be clean under the repository's formatter check, except a file whose
bytes are a fixture another check compares. Each exemption SHALL be named inside the check, and the
check SHALL fail if an exempt file is missing.

#### Scenario: The tree is formatted

- **WHEN** the formatter check runs over the tracked Nix files
- **THEN** it exits successfully

#### Scenario: A file drifts

- **WHEN** any tracked Nix file is not formatter-clean
- **THEN** the check fails and names the file

#### Scenario: An exempt fixture

- **WHEN** a file is exempt because its bytes are a fixture
- **THEN** the exemption is named in the check
- **AND** the check fails if that file is missing, rather than silently checking one file fewer

#### Scenario: The scan finds nothing

- **WHEN** the file list comes back shorter than the tree can plausibly be
- **THEN** the check fails, because a scan over nothing passes every rule it contains
