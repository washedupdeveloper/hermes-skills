# Spec Delta

## ADDED Requirements

### Requirement: A stated count is checked

A document SHALL state a count only where a check derives it from the tree. A count no check derives
SHALL be replaced by a pointer to the list, directory or API that answers the question.

#### Scenario: A count the gate can derive

- **WHEN** a document states how many requirements or mutants there are
- **THEN** a check derives that figure from the tree and fails on a mismatch, naming the document

#### Scenario: A count nothing derives

- **WHEN** a document would state how many changes have landed, or how many check runs a commit has
- **THEN** it points at `openspec/changes/archive/` or the check-runs API instead, because a number
  copied from a command is stale by the next commit

#### Scenario: The sentence disappears

- **WHEN** the checked sentence is removed or reworded
- **THEN** the check fails, because an absent count is not a passing one

#### Scenario: The comparison is exercised

- **WHEN** the stated number is drifted by one
- **THEN** a test asserts the comparison rejects it, because a check never observed to fail is a guess
