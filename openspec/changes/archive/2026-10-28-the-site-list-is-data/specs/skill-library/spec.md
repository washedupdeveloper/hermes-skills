# Spec Delta

## ADDED Requirements

### Requirement: A list is data, not a description

Where more than one file adopts the same pinned thing, the set of files SHALL be a list the gate
reads, and no prose SHALL state its size.

#### Scenario: A site is added

- **WHEN** a file starts adopting the CLI
- **THEN** it is added to `openspecCliSites` in `nix/pins.nix`, and the gate checks it there

#### Scenario: A site is unlisted

- **WHEN** a file names the CLI without being listed
- **THEN** the gate fails and names that file

#### Scenario: A listed site is missing

- **WHEN** a listed path does not exist
- **THEN** the gate fails and names the path, rather than checking one file fewer

#### Scenario: The list empties

- **WHEN** the list has no entries
- **THEN** the check fails, because every rule built on it would pass vacuously

#### Scenario: Prose states the size

- **WHEN** documentation describes how many files adopt the pin
- **THEN** it points at the list instead of counting, because the count is what drifts
