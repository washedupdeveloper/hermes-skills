# 0008 — OpenSpec as the spec container, per repository

Date: 2026-10-25
Status: accepted

## Context

The library already carried four ways to write down what to build: `to-spec`, `to-tickets`,
`project-kickoff-planning` and `wayfinder`. None of them left a durable artifact in the repo
that a later session, or a different agent, could be held to. A brief written in a conversation
dies with the conversation.

OpenSpec supplies a container: `openspec/specs/<capability>/spec.md` as the source of truth,
`openspec/changes/<name>/` as a proposal plus a delta spec plus tasks, a CLI that prints the
template for each artifact, and `validate --strict` as a structural check.

## Decision

1. A repository may carry `openspec/`. When it does, every behavior change starts as a change
   directory and merges through `openspec archive`.
2. The trigger is the repository, not the session. `AGENTS.md` states the rule, because Hermes
   injects that file at startup (`agent/subdirectory_hints.py`).
3. Enforcement is the repo's CI job, not a promise in prose: `openspec validate --all --strict`
   on every push.
4. The method stays in the library. `to-spec` asks the questions, `to-tickets` slices, and
   `openspec` owns the container and points at `openspec instructions` for the format. The
   format is not restated anywhere.
5. `skip_specs: true` covers refactors, typo fixes and dependency bumps.

phoenix, this repository and review-council were initialised with one seeded capability each.

## Evidence

A controlled pilot, run to decide whether the container earns its cost. One task (an unsafe URL
guard in a small HTTP client), two isolated agents on the same model, the same five
requirements: one briefed in prose (278 tokens), one given a validated change (874 tokens across
4 files).

- Both implementations passed an eight-point requirement probe, including the guard inside the
  I/O function before any socket work.
- The prose arm validated the CLI's `--dry-run` path. The spec arm did not: `--dry-run` printed
  a refused base with exit 0, because the guard lived in `request()` and no scenario covered an
  early return.
- Council, advisory, two samples, whole-repo: prose 52.96, spec 50.07. The two high findings in
  the spec arm named exactly that branch.
- The spec arm was faster (123s against 176s) and wrote fewer tests (12 against 17).
- Archive, tested without a model: a delta written before another change merged was **refused**,
  with the dropped scenario named ("current spec contains scenario(s) not present in the
  modified block: ..."); refreshed, it merged and all three scenarios survived.

The pilot is small: one task, one model, two samples, and both aggregates sit below the
calibrated threshold because the review target is a scratch repository. The delta is the signal,
not the absolute score.

## Consequences

- A spec narrows behavior to its scenarios. An unstated path is not implemented, and the
  implementation still looks complete. The `openspec` skill now requires a scenario for every
  branch that can return before the guarded call.
- `validate --strict` checks shape, not coverage or truth. The council is the check on the
  spec's coverage, not only on the code's quality.
- Ceremony is about 874 tokens and four files per change. The unit is one change per task or
  branch; several commits tick tasks in the same change.
- The CLI is an external toolchain (Node 20.19+, npm). The local install is user-scoped; CI
  installs it per run.
- `archive` replaces a MODIFIED requirement as a whole block, so a delta written before another
  change merged is refused, with the dropped scenario named. Verified against 1.15.0. Treat the
  refusal as a required refresh, not an error to bypass; one change at a time per requirement.

## Rejected

- **Forcing every session into the flow.** OpenSpec is a per-project container. A question has
  no spec, and pretending it does adds artifacts nobody reads.
- **A hand-rolled requirement format.** It would duplicate the container and its validator.
- **Specs as the reply format.** The reply contract (`communication/reply`) already covers what
  a final message must contain, labelled by evidence class.