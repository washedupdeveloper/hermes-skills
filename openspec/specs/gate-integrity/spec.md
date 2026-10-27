# gate-integrity Specification

## Purpose
The repository's own gate is a measurement: it rejects the states the repository says it forbids,
in every spelling claimed, fails closed when a scanned file is absent, and states no more than it
checks.

## Requirements

### Requirement: A forbidden state is rejected in every named spelling

A gate assertion SHALL fail when the tree contains the state that assertion forbids, for every
spelling the repository claims to forbid, and SHALL name the offending path and line. A negative
control SHALL fail when the rejection rule it guards is disabled.

#### Scenario: A runner label arrives through a matrix

- **WHEN** a workflow takes its runner from `runs-on: ${{ matrix.os }}` and the matrix lists
  `os: [ubuntu-latest]`
- **THEN** the gate fails, naming the workflow and the line that carries the floating label
- **AND** the same holds for a bracketed list, a block list and a quoted scalar

#### Scenario: A range hides behind a trailing comment

- **WHEN** an install step reads `npm install -g @fission-ai/openspec@1  # pinned`
- **THEN** the gate fails, naming that line
- **AND** `@^1.15.0`, `@~1.15.0`, `@latest`, `@1.15`, a versionless package, and the `npx -y` form
  the documentation teaches each fail the same assertion

#### Scenario: The rejection rule itself is broken

- **WHEN** the rule that detects a floating runner is replaced by one that never matches, and a
  workflow is changed to `runs-on: ubuntu-latest`
- **THEN** the suite fails
- **AND** a control that exercises a different rule than the assertion calls does not satisfy this

### Requirement: A scanned set fails closed

The set of files the gate reads SHALL be fixed. A member that is missing, renamed, untracked or
outside the store copy SHALL fail the gate rather than shrink the scan.

#### Scenario: An adopted file disappears

- **WHEN** the template this repository tells other repositories to adopt is renamed or deleted
- **THEN** the gate fails, naming the missing path
- **AND** no assertion passes on an empty input set

#### Scenario: The adopted file is present and wrong

- **WHEN** the template exists and pins a range
- **THEN** the gate fails, naming the template and the line

### Requirement: Enforcement prose states only what is checked

A document that says a command fails on a state SHALL name only the sites that command reads, and
every site it names SHALL be in the scanned set. A claim the repository cannot check SHALL say so
rather than be asserted.

#### Scenario: The sentence enumerates a site the gate never reads

- **WHEN** the prose names a file as enforced and that file is absent from the scanned set
- **THEN** a test fails, naming the prose line and the unscanned site

#### Scenario: The count and the tree disagree

- **WHEN** the prose says a value moves in three places and the tree holds four
- **THEN** the verification fails until the prose or the tree is corrected

### Requirement: Secret-scan hits carry a recorded disposition

Every credential-shaped hit the repository's own secret probe reports SHALL be removed, or matched
by an allowlist entry that names the fixture and the test that owns it. A supply-chain finding on
an install step SHALL be closed or recorded as accepted together with its boundary.

#### Scenario: A fixture re-fires on every run

- **WHEN** the secret probe scans the repository and a test fixture matches a credential rule
- **THEN** an allowlist entry names that fixture path and the test that writes it
- **AND** a subsequent probe run over the working tree reports no findings

#### Scenario: An install step remains unpinned in integrity

- **WHEN** an install step resolves its dependency closure at run time with no lockfile or
  integrity hash
- **THEN** the accepted-risk record names what the version pin does not close and the permission
  boundary that bounds it, or the step is changed to close it

### Requirement: A touched Nix file is formatter-clean

A change SHALL leave every Nix file it modifies clean under the repository's formatter check.
Formatting debt in files the change does not touch SHALL be recorded per path and line, not
summarised as a count.

#### Scenario: The changed file is checked

- **WHEN** the formatter check runs over a Nix file the change modifies
- **THEN** it exits successfully
- **AND** a file that already failed before the change does not make that claim true

#### Scenario: Debt elsewhere is reported

- **WHEN** a formatter or linter reports findings in files outside the change
- **THEN** the report names each path and line with a disposition
- **AND** the repository-wide check is not described as clean

### Requirement: Gate cost is measured

The gate's eval-time cost SHALL be compared with a pinned baseline and SHALL add no work to a
runtime path. An unmeasured cost SHALL be reported as a gap, never as zero.

#### Scenario: Assertions are added at eval time

- **WHEN** a change adds assertions that read files during evaluation
- **THEN** the report states the tier, the files read, and the measured eval-time delta
- **AND** it states that no Python or shell path gained work, or names the path that did

#### Scenario: No baseline exists

- **WHEN** no pinned eval-time baseline is available
- **THEN** the report calls the cost unmeasured
- **AND** it does not report the added cost as zero

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
