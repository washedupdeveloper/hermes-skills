# Design

## Context

This repository already carries `openspec/`, validates it in CI, and uses
OpenSpec for behavior changes. The missing piece is the rule that a work item's
brief and handoff live in the change rather than in chat. Dependency freshness
already covers pinned GitHub Actions; Python test pins and the Nix flake lock
have no recurring update path.

## Decisions

### The change is the brief

Every work item identifies a change and the task IDs it owns. A subagent brief
names those IDs instead of restating them; its return names the same IDs, files
and evidence. Chat is a short pointer to the artifact.

### Dependency sources

Dependabot covers GitHub Actions and Python requirements weekly. A scheduled
workflow runs `nix flake update`, and opens a branch and pull request only when
`flake.lock` changed. The existing CI gate remains required. No workflow
auto-merges.

### Same protocol in both repositories

`agentic-council-v2` and `hermes-skills` use the same change name and the same
task/handoff vocabulary so a subagent can move between them without a second
briefing format.

## Risks

The flake refresh needs `contents: write` and `pull-requests: write`. It uses the
repository token to update only its own branch and PR. If branch protection
rejects the push, the job fails visibly rather than reporting success.

## Migration

This change is the first consumer. Existing changes remain valid; future
behavior changes follow the same loop and dependency-only changes use
`skip_specs: true`.
