---
name: openspec
description: "Use when a repo has an openspec/ directory."
version: 1.2.1
author: user, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
category: software-development
metadata:
  hermes:
    tags: [openspec, spec, requirements, planning]
    related_skills: [to-spec, to-tickets]
writes: [none]
side_effects: [none]
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
nix run .#openspec -- list --specs                 # what the repo already promises
nix run .#openspec -- new change <kebab-name>      # creates openspec/changes/<name>/
nix run .#openspec -- instructions proposal --change <name>
nix run .#openspec -- status --change <name>       # the DAG: proposal -> specs + design -> tasks
nix run .#openspec -- validate <name> --strict     # before code, and again before archive
nix run .#openspec -- archive <name> --yes         # merges the delta into openspec/specs/
```

Run it through the flake. `nix run .#openspec` resolves the CLI from `flake.lock`, so the
version is the one this repository locked and nothing is installed into a profile:

```sh
nix run .#openspec -- validate <name> --strict
nix run .#openspec -- validate --all --strict
```

`npx` and `npm install -g` are what this replaces, not a fallback for it: they resolve outside
the lock, fetch from the network at run time, and leave a second version on PATH that the
lockfile does not describe. The flake exposes the app as `packages.openspec` for exactly that
reason — see `nix-flake-packaging`. A repository without the app gets one before it gets the
CLI.

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
- **A guarantee is only as strong as the shipped entry point's default.** A library rule can be
  bypassed by the action, CLI or config default that calls it: an action that passed
  `--samples 1` by default made a two-clean-sample requirement true in the library and absent
  from the gate users run. Read the shipped defaults (workflow inputs, CLI defaults, profile
  config), add a scenario for the default path, and gate it with a test; `validate --strict`
  and a green suite will not notice.
- **The delta only.** A change's `specs/<capability>/spec.md` holds `## ADDED Requirements`,
  `## MODIFIED Requirements` or `## REMOVED Requirements`. `openspec/specs/` is edited by
  `archive`, never by hand during a change.
- **A `MODIFIED` block replaces the whole requirement, so it must re-state every scenario.**
  Editing one scenario into a delta that carries only the scenarios you touched leaves the
  others to be dropped at archive, and `validate --strict` refuses it by name: `MODIFIED "<req>"
  omits scenario(s) the current spec still has: "<scenario>". The modified block has N scenarios;
  the current spec has M`. Copy the omitted scenarios into the delta verbatim. Read the current
  `openspec/specs/<capability>/spec.md` requirement before writing the delta for it — the delta
  is a replacement, not a patch. Same rule for the heading: it must match the current spec's
  text exactly or the delta reads as an addition and the old requirement survives beside it.
- **Done is archived, and `validate` cannot see the difference.** All tasks ticked means
  the change is finished; finish it with `archive <name> --yes` in the same commit as the
  last task. `validate --strict` checks a delta's shape and passes a fully ticked change
  that has sat in `changes/` for weeks — three did exactly that in one repository, at
  41/41, 11/11 and 16/16, long after their work merged. Put the state under the gate
  rather than in a convention: a job step or test that fails on any non-archive change
  whose `tasks.md` has no unticked box. The check is vacuous when nothing is open, which
  is the state a healthy repository is in most of the time.
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
- **The CLI comes from the project's own pin.** The npm one-shot runner runs
  for the moment and leaves a second copy in `~/.npm` that no lockfile describes — the
  next run may resolve differently and the version in the gate stops being the version in
  the review. If the repo has a flake, add `apps.openspec` backed by `pkgs.openspec` and
  call `nix run .#openspec -- …` from both CI and the developer's shell; the CLI is then
  a flake output like any other tool the repository depends on. `pkgs.openspec` trails the
  npm release (1.13.x against 1.15.0 when this was written) and validates current changes
  correctly, so pinning is not a capability loss.
- **The repo is the gate.** `openspec validate <name> --strict` runs in the repo's CI, not only
  by hand. A repo whose CI lacks it gets that step before its first change; the job block to
  append is `templates/ci-job.yml`, with the repository's own checkout pin.
- **Check for an existing change before creating one.** `openspec/changes/` may already hold the
  work: a change can be fully ticked and still unarchived, and a branch can carry its commits.
  List the directory and read the matching `proposal.md` and `tasks.md` first; creating a second
  change for the same behavior splits the record and loses the evidence already collected. If it
  exists, validate it and continue from its tasks instead of restarting.
- **A superseded claim inside an unarchived change is stale evidence, not history.** An open
  change's `tasks.md` evidence table records what was true when it was written; when a later
  change reverses one of those facts (a gate that drops a system, a flag that disappears), the
  old row becomes a false statement sitting in the tree. Correct the row in the same commit as
  the change that invalidates it — the change is still unarchived, so its record is still
  expected to describe the tree.

## Work communication contract

When the owner asks for OpenSpec as the communication medium, use the change as the record:

- Every non-trivial work item, task assignment, status update and handoff names the change and
  the task IDs it covers. Chat is a short pointer to the artifact, never the only brief.
- A subagent brief names the change and task IDs and does not add a competing prose brief.
- A subagent returns the same IDs, the files it changed and the evidence commands it ran.
- A **decision** is a row in `design.md`: the option taken, the options rejected, and what
  would falsify the choice. A decision recorded only in chat did not happen.
- A **verdict** is a row in `tasks.md`: the claim, the command that settles it, and the
  result. "Done" without an evidence command is unproven, and an unproven claim is not
  finished work.
- Pure refactors and dependency bumps use `skip_specs: true` when behavior does not change.
- The full route → profile → run → evidence loop is `references/agent-delivery.md`;
  the task-prompt skeleton is `templates/agent-task-prompt.md`. Keep `tasks.md` owned by
  the orchestrator and require every worker to write `collab/<task>.md` evidence.
- When the owner asks to see the work, render the change artifacts — proposal, design
  trade-off table, spec delta, tasks and evidence — into one standalone page; the archived
  path is `openspec/changes/archive/<date>-<name>/`. Chat carries the decision table, not a
  second copy of the spec.

## Verify

Before archive: `openspec validate <name> --strict`, the repo's tests, and every task ticked.
An unticked task is unfinished work, not a note.

`validate --strict` checks the delta's shape, not the checkbox state: a change with
0/N tasks complete still validates. Read `tasks.md` and grep for each capability before
calling the change done; "valid" is not "implemented". When the code and the delta
disagree, repair one of them — write the delta to the shipped contract, or implement the
delta — and never leave both standing.
