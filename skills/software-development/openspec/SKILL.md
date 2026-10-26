---
name: openspec
description: "Use when a repo has openspec/. Spec before code."
version: 1.1.0
author: user, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
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
openspec archive <name> --yes          # merges the delta into openspec/specs/
```

`openspec instructions <artifact> --change <name>` prints that artifact's template and rules.
It is the only template source. Do not restate a template here or in a repo doc.

Extracting the requirements from a conversation is `to-spec`'s job; slicing them into
vertical, blocking-aware tickets is `to-tickets`'. This skill owns the container, not the
method.

## Rules

- **The artifacts are the brief.** The proposal's Why and What Changes, the requirements, and
  `tasks.md` are what the work is judged against. Write them before the first edit.
- **A requirement is observable.** Each one carries at least one scenario of `WHEN` / `THEN` /
  `AND`. No implementation nouns, no file paths, no "use X".
- **A scenario names a path.** Every branch that can return before the guarded call needs its
  own scenario. Measured on one task: a spec that covered only the request path let `--dry-run`
  compose and print a refused base, and the implementing agent stopped exactly at the spec's
  edge, while an agent given the same requirements as prose validated that path too.
- **The delta only.** A change's `specs/<capability>/spec.md` holds `## ADDED Requirements`,
  `## MODIFIED Requirements` or `## REMOVED Requirements`. `openspec/specs/` is edited by
  `archive`, never by hand during a change.
- **A task is a commit.** `tasks.md` checkboxes are the plan. Tick one when its code and test
  land, and let the commit body name the tasks it closes.
- **The repo is the gate.** `openspec validate <name> --strict` runs in the repo's CI, not only
  by hand. A repo whose CI lacks it gets that step before its first change; the job block to
  append is `templates/ci-job.yml`, with the repository's own checkout pin.

## Verify

Before archive: `openspec validate <name> --strict`, the repo's tests, and every task ticked.
An unticked task is unfinished work, not a note.