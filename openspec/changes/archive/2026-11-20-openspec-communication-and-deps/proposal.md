# Proposal

## Why

Work briefs and handoffs currently live in conversation and disappear with the
session. This library already uses OpenSpec for behavior changes, but it does
not state that work communication itself is an OpenSpec artifact, and its
weekly dependency coverage covers GitHub Actions only.

## What Changes

- State the communication contract in `AGENTS.md` and the `openspec` skill:
  every work item, task assignment, status and handoff names a change and task
  IDs; chat is a pointer.
- Add weekly Python dependency coverage to Dependabot.
- Add a scheduled Nix flake-lock refresh that opens or updates a CI-gated pull
  request; no auto-merge.
- Keep the existing OpenSpec CI validation.

## Capabilities

### New Capabilities

- `agent-collaboration`: durable work items, subagent briefs and handoffs.
- `dependency-maintenance`: weekly dependency checks and update pull requests.

### Modified Capabilities

None.

## Impact

`AGENTS.md`; the `openspec` skill; `.github/dependabot.yml`; a new dependency
workflow; the repo gate and documentation. No skill behavior changes beyond the
communication contract.
