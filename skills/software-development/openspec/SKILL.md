---
name: openspec
description: "Use when a repo has an openspec/ directory."
version: 1.1.2
author: user, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
category: software-development
metadata:
  hermes:
    tags: [openspec, spec, requirements, planning]
    related_skills: [to-spec, to-tickets]
---

# OpenSpec

A repo with `openspec/` states its behavior as requirements. Every change is a proposal plus
a spec delta, written before the code and merged when the work lands.

## When it applies

- A repo containing `openspec/`: every change to behavior, a public API, a config contract, or
  a user-visible output.
- A repo without it: only on the owner's word. Then run `scripts/bootstrap.sh`, commit the
  result, and start the first change.
- Pure refactors, typo fixes and dependency bumps: a change with `skip_specs: true` in
  `.openspec.yaml`, and one line in the proposal's Why saying behavior does not change.

## The loop

```
openspec list --specs                  # what the repo already promises
openspec new change <kebab-name>       # creates openspec/changes/<name>/
openspec instructions proposal --change <name>
openspec status --change <name>        # the DAG: proposal -> specs + design -> tasks
openspec validate <name> --strict      # before code, and again before archive
`openspec archive <name> --yes`          # merges the delta into openspec/specs/
```

When the CLI is not on PATH, run the same pinned command through `npx`
(`npx -y @fission-ai/openspec@1.15.0 …`) rather than skipping validation. On a
Nix host with no Node on PATH, borrow one for the command:
`nix shell nixpkgs#nodejs -c npx -y @fission-ai/openspec@1.15.0 validate <name> --strict`.

After `archive`, a **new capability** gets a placeholder `## Purpose`. Replace it
by editing `openspec/specs/<capability>/spec.md` directly; a `## Purpose` in a
delta is ignored when the capability is created, and `validate --all --strict`
keeps failing until the main spec has a real purpose.

`openspec instructions <artifact> --change <name>` prints that artifact's template and rules.
It is the only template source. Do not restate a template here or in a repo doc.

Extracting the requirements from a conversation is `to-spec`'s job; slicing them into
vertical, blocking-aware tickets is `to-tickets`'. This skill owns the container, not the
method.

## Rules

- **The artifacts are the brief.** The proposal's Why and What Changes, the requirements, and
  `tasks.md` are what the work is judged against. Write them before the first edit.
- **A requirement is observable.** Each one carries at least one scenario of `WHEN` / `THEN` /
  `AND`. No implementation nouns, no file paths, no "use X". The scenario heading takes exactly
  four `#`s (`#### Scenario:`); at the wrong level the validator ignores it without complaint.
- **A scenario names a path.** Every branch that can return before the guarded call needs its
  own scenario. Measured on one task: a spec that covered only the request path let `--dry-run`
  compose and print a refused base, and the implementing agent stopped exactly at the spec's
  edge, while an agent given the same requirements as prose validated that path too.
- **The delta only.** A change's `specs/<capability>/spec.md` holds `## ADDED Requirements`,
  `## MODIFIED Requirements` or `## REMOVED Requirements`. `openspec/specs/` is edited by
  `archive`, never by hand during a change.
- **A task is a commit.** `tasks.md` checkboxes are the plan. Tick one when its code and test
  land, and let the commit body name the tasks it closes.
- **Validate without Node when the host has none.** A container, sandbox or agent runtime that
  ships no Node still has to check a change before presenting it as a handover:
  `references/shape-check-without-the-cli.md` encodes the CLI's own structural rules, treats an
  empty change as invalid rather than absent, and says how to test the checker against a change
  the tool actually produced.
- **When the CLI is unavailable, read an archived change in the same repo and copy its shape**
  rather than inventing one. The minimum is `.openspec.yaml` (`schema`, `created`), a `proposal.md`
  with Why / What Changes / Capabilities / Impact, a `# Tasks` checklist, and one
  `specs/<capability>/spec.md` per capability. A directory holding only `.openspec.yaml` is an
  empty change, not a scaffold.
- **The repo is the gate.** `openspec validate <name> --strict` runs in the repo's CI, not only
  by hand. A repo whose CI lacks it gets that step before its first change; the job block to
  append is `templates/ci-job.yml`, with the repository's own checkout pin.

## Work communication contract

When the owner asks for OpenSpec as the communication medium, use the change as the record:

- Every non-trivial work item, task assignment, status update and handoff names the change and
  the task IDs it covers. Chat is a short pointer to the artifact, never the only brief.
- A subagent brief names the change and task IDs and does not add a competing prose brief.
- A subagent returns the same IDs, the files it changed and the evidence commands it ran.
- Pure refactors and dependency bumps use `skip_specs: true` when behavior does not change.
- The full route → profile → run → evidence loop is `references/agent-delivery.md`;
  the task-prompt skeleton is `templates/agent-task-prompt.md`. Keep `tasks.md` owned by
  the orchestrator and require every worker to write `collab/<task>.md` evidence.

## Verify

Before archive: `openspec validate <name> --strict`, the repo's tests, and every task ticked.
An unticked task is unfinished work, not a note.

`validate --strict` checks the delta's shape, not the checkbox state: a change with
0/N tasks complete still validates. Read `tasks.md` and grep for each capability before
calling the change done; "valid" is not "implemented". When the code and the delta
disagree, repair one of them — write the delta to the shipped contract, or implement the
delta — and never leave both standing.
