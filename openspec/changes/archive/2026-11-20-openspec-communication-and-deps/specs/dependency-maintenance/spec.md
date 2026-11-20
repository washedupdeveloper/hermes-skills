## ADDED Requirements

### Requirement: Dependencies are checked weekly

Every dependency source the repository relies on MUST have an automated check at
least once per week.

#### Scenario: A weekly check finds an update

- **WHEN** the weekly Dependabot or flake-lock job finds a newer dependency
- **THEN** it opens or updates a pull request against the default branch

#### Scenario: A weekly check finds nothing

- **WHEN** the weekly job finds no newer dependency
- **THEN** it exits successfully without opening a pull request

### Requirement: Dependency updates are never auto-merged

A dependency update MUST pass the repository gate and a human decision before it
is merged.

#### Scenario: A dependency pull request is green

- **WHEN** a dependency pull request passes the gate
- **THEN** it remains open for review; no workflow merges it automatically
