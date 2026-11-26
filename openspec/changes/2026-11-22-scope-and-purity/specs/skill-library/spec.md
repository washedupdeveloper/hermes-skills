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

#### Scenario: A skill installs a systemd user unit

- **WHEN** a skill tells the reader to write a unit into the user's config directory
- **THEN** it declares `writes: [$XDG_CONFIG]`, opens with the redirectable preamble
  (`: "${SKILL_XDG_CONFIG:=${XDG_CONFIG:-$HOME/.config}}"`), and names the exact file

#### Scenario: The root is allowed but the reader cannot redirect it

- **WHEN** a skill declares `$XDG_CONFIG` without the preamble
- **THEN** the gate fails and names the missing preamble

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

### Requirement: A skill states its answers, its triggers and its exclusions

A skill that states its scope MUST state all three: `scope_answers` (at most three, each 3-160
characters), `scope_triggers` (the phrases a reader or router arrives by) and `scope_out`
(at most five named exclusions). Two of the three is a half-answer.

#### Scenario: A trigger with no answer

- **WHEN** a skill declares `scope_triggers` and not `scope_answers`
- **THEN** the gate fails, naming the missing fields and saying a scope is all three

#### Scenario: An answer that is a paragraph

- **WHEN** a `scope_answers` entry is longer than 160 characters
- **THEN** the gate fails and prints the length

#### Scenario: The catalog must carry a scope everywhere

- **WHEN** `scope_required` is true in the contract and a skill declares none
- **THEN** the gate fails, naming the three fields to add

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

### Requirement: An install can be verified without changing it

`install.sh --check` MUST report whether an existing target matches this library and MUST
exit non-zero when it does not. It MUST NOT write to the target. An entry that is missing,
points outside this library, or is a copy that no longer matches is a problem.

#### Scenario: The install matches

- **WHEN** every shipped skill is present in the target and resolves to this library
- **THEN** `--check` exits 0 and names the target

#### Scenario: A skill is missing

- **WHEN** a shipped skill has no entry in the target
- **THEN** `--check` exits 1 and names it

#### Scenario: An entry points elsewhere

- **WHEN** an entry exists but resolves outside this library
- **THEN** `--check` exits 1 and reports it as foreign

#### Scenario: A copy no longer matches

- **WHEN** an entry is a copy whose contents differ from this library
- **THEN** `--check` exits 1 and reports it as stale

#### Scenario: A link and a copy both count as installed

- **WHEN** the target reads this library through links on one host and through copies on
  another
- **THEN** `--check` exits 0 on both, because what matters is that the target reads this
  library, not how it got there
