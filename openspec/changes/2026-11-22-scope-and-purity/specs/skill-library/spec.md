## ADDED Requirements

### Requirement: A skill declares its scope and its writes

Every `SKILL.md` MUST carry `writes`, drawn from the roots the contract allows,
and MUST open with the POSIX root preamble when `writes` is not `none`.

#### Scenario: A skill omits writes

- **WHEN** the gate reads a `SKILL.md` with no `writes`
- **THEN** it fails, naming the file and the `[none]` default

#### Scenario: A skill names an absolute path

- **WHEN** `writes` contains `/home/...` or any path outside the contract's roots
- **THEN** the gate fails and prints the allowed roots

### Requirement: Persistence is project-local

A skill MUST NOT persist project information outside the project. `$HERMES_HOME`
and `$SYSTEM` are outside it; a skill that writes there MUST declare a non-empty
`side_effects` list and MUST carry a `**Heads-up.**` paragraph naming what will
appear on the reader's machine.

#### Scenario: A skill writes outside the project silently

- **WHEN** a skill declares `$HERMES_HOME` or a non-`none` side effect and has no
  `**Heads-up.**` paragraph
- **THEN** the gate fails

#### Scenario: The reader is told

- **WHEN** the same skill carries a `**Heads-up.**` paragraph
- **THEN** the gate passes, and the paragraph names the effect

### Requirement: Side effects are a closed vocabulary

`side_effects` MUST use only tokens the contract declares: `none`, `systemd`,
`container`, `port`, `cron`, `background-process`, `credential`,
`global-package`.

#### Scenario: A free-form token hides a daemon

- **WHEN** a skill declares an effect the contract does not list
- **THEN** the gate fails and prints the vocabulary

### Requirement: Every domain states its question

Each category directory MUST contain a `CATEGORY.md` with a `**Question.**` line
and a `**Not here.**` list whose skill names exist in the catalog.

#### Scenario: A domain has no contract

- **WHEN** a category exists without `CATEGORY.md`
- **THEN** the gate fails, naming the directory

#### Scenario: A "not here" pointer rots

- **WHEN** `CATEGORY.md` names a skill that does not exist
- **THEN** the gate fails, naming the pointer

### Requirement: A trigger phrase has one owner

Two skills MUST NOT declare the same normalized trigger phrase.

#### Scenario: Two skills claim one phrase

- **WHEN** two skills declare the same trigger
- **THEN** the gate fails, naming the second skill and its current owner

### Requirement: One runtime, one marked fallback

Skills are written for the contract's primary container runtime. A fenced
command that invokes the fallback runtime MUST carry a
`# docker-fallback: <reason>` marker.

#### Scenario: An unmarked docker call

- **WHEN** a fenced command invokes `docker` without the marker
- **THEN** the gate fails

#### Scenario: A deliberate exception

- **WHEN** the same line carries the marker and a reason
- **THEN** the gate passes

### Requirement: A renamed skill resolves

`library/aliases.json`, when present, MUST map old names to existing skills and
MUST NOT shadow a real skill name.

#### Scenario: An alias points nowhere

- **WHEN** an alias targets a skill that does not exist
- **THEN** the gate fails