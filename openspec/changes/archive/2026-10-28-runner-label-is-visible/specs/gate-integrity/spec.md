# Spec Delta

## ADDED Requirements

### Requirement: A runner label is visible in the file that names it

A `runs-on:` value SHALL be a label the repository can read, or an expression naming a matrix key
whose values it can read. A workflow SHALL NOT use `include:`, which can add matrix values the
written list does not show.

#### Scenario: A literal label

- **WHEN** a workflow declares `runs-on: ubuntu-24.04`
- **THEN** the check accepts it

#### Scenario: A matrix expression

- **WHEN** a workflow declares `runs-on: ${{ matrix.os }}` and lists that key's values in the file
- **THEN** the check accepts it, because the token scan reads those values

#### Scenario: An opaque expression

- **WHEN** a workflow declares `runs-on: ${{ inputs.os }}`, `${{ env.RUNNER }}`, or any expression
  that does not name a matrix key
- **THEN** the check fails and names the line

#### Scenario: A matrix assembled from include

- **WHEN** a workflow that uses a matrix expression contains `include:`
- **THEN** the check fails, because the values it would add are not in the file and cannot be read
