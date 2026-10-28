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

### Requirement: The installer is one the gate understands

A line that names the CLI SHALL use an installer the gate parses — `npm`, `npx` or `nix`. Any other
installer SHALL fail the check, naming the file and the line.

#### Scenario: An adopted installer

- **WHEN** a line reads `npm install -g @fission-ai/openspec@1.15.0`, or runs it through
  `nix shell … -c npx`
- **THEN** the check accepts the line and the version rule reads its spec

#### Scenario: A foreign installer

- **WHEN** a line reads `pnpm add -g @fission-ai/openspec@1.15.0`, `bun add -g`, or
  `yarn global add`
- **THEN** the check fails and names the line, because the version rule cannot read it

#### Scenario: An installer with no package at all

- **WHEN** a line pipes an archive into a shell, `curl … | sh`
- **THEN** the check fails: there is no package spec and no version for any rule to read

### Requirement: A run's cost is a number, not an inference

A workflow run SHALL publish how long each of its jobs took, in the run itself, without requiring
anyone to read two timestamps from an API response.

#### Scenario: A job is slow or vanishes

- **WHEN** a job runs long, or is cancelled without executing a step
- **THEN** the run's summary states that job's elapsed time and its conclusion

#### Scenario: A job is still running

- **WHEN** the cost is rendered while a job has not finished
- **THEN** that job shows no duration rather than zero, because zero is a claim about the work

#### Scenario: The number is read as a total

- **WHEN** the table is published
- **THEN** the run's span is distinguished from the sum of the jobs, because jobs overlap
