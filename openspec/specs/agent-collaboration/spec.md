# agent-collaboration Specification

## Purpose
Durable work items, subagent briefs and handoffs: an OpenSpec change is the
authoritative record, and chat only points to it.

## Requirements

### Requirement: Every work item has an OpenSpec change

Every non-trivial work item, task assignment, status update and handoff MUST
identify an OpenSpec change under `openspec/changes/` and the task IDs it covers.

#### Scenario: An agent starts or delegates work

- **WHEN** an agent starts a work item or gives a task to a subagent
- **THEN** the brief names the OpenSpec change and task IDs, and the change's
  proposal and tasks are the authoritative brief

#### Scenario: A status or handoff is reported

- **WHEN** an agent reports progress or hands work to another agent
- **THEN** the report names the same change and task IDs, the changed files, and
  the evidence commands that were run

### Requirement: Chat is a pointer, not the record

A chat message MUST NOT be the only record of a work item or a handoff.

#### Scenario: The session ends

- **WHEN** a session ends after work has been reported in chat
- **THEN** the change directory still contains the proposal, task state and
  evidence needed by the next agent

### Requirement: The OpenSpec container is validated in CI

The repository's CI MUST validate all OpenSpec changes and specs with the pinned
CLI.

#### Scenario: A malformed change is pushed

- **WHEN** a change has a missing proposal, requirement, scenario or task
- **THEN** `openspec validate --all --strict` fails CI
