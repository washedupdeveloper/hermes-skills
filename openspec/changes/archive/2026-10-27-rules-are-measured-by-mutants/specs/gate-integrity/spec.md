# Spec Delta

## ADDED Requirements

### Requirement: A rule is measured against the states it forbids

Every rule in the gate SHALL be exercised by a mutant that puts a forbidden state into the tree,
and every mutant SHALL make the check fail. The harness SHALL restore the tree exactly — content
and mode — after each mutant.

#### Scenario: A forbidden state is in the tree

- **WHEN** a mutant introduces a floating runner, a range pin, an off-version site, a fifth
  adoption site, or a missing adopted file
- **THEN** the check exits non-zero and names the file and line

#### Scenario: A rule that cannot fire

- **WHEN** a rule is replaced with one that can never match
- **THEN** the negative control beside it fails

#### Scenario: The gate accepts a mutant

- **WHEN** a forbidden state is in the tree and the check still exits zero
- **THEN** the harness reports the rule as broken and exits non-zero itself

#### Scenario: A mutant is applied and removed

- **WHEN** a mutant has been run
- **THEN** the file it changed is byte-identical and keeps its mode, so the next mutant measures
  the same tree the first one did
