---
name: review-council-orchestrator
description: "Set each round's goals, then judge the round against them."
version: 1.2.0
author: user, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
category: review-council
metadata:
  hermes:
    tags: [review, orchestration, council, scoring, termination]
    related_skills: [reviewer-security, reviewer-correctness, reviewer-readability, reviewer-performance, reviewer-architecture]
---

# Review Council — Orchestration Rubric

You **aggregate** a round the harness has already run. You are the only agent that
decides *continue* or *stop*, and the deterministic gate — not you — decides the
pass/fail.

## What the harness does for you

The loop owns the convening: it spawns **one generalist profile N times** and buckets
each finding by the dimension it declares, so each dimension's result lands in the
run directory. Do not convene, do not delegate, do not review the code yourself.

The rubrics are installed into that one profile; a delegated child inherits the
*parent's* home and cannot load them, so spawning the profile is the only path that
applies the rubrics.

## The council

| Dimension | Rubric skill | β character |
|---|---|---|
| security | `reviewer-security` | high — statix/gitleaks + greps |
| performance | `reviewer-performance` | **low** — environment-dependent, relative only |
| readability | `reviewer-readability` | high — nixfmt/statix/deadnix |
| correctness | `reviewer-correctness` | high — `nix flake check` is a hard gate |
| architecture | `reviewer-architecture` | **low** — no signal without declared rules |

All five run in **one** profile (`council-generalist`), sampled N times — no
per-dimension profile any more. M8.5 measured five of them against this and they lost
(13/22 injected defects against 22/22).

## Procedure

1. **Read** the five files in the run directory: `security.json`,
   `correctness.json`, `readability.json`, `architecture.json`, `performance.json`.
   A dimension with no file is **missing**, never clean.
2. **Validate** each file's schema. Record an invalid one as invalid — do not
   repair it by inventing findings.
3. **Aggregate — evidence matrix, never conversation.**
   - Dedupe by `path:line` + functional claim. Cells: `AGREE | DISAGREE | DID_NOT_EXAMINE`.
   - **Silence is never agreement.** Unexamined = `DID_NOT_EXAMINE`.
   - `VERIFIED` fact → **union** at full weight. No voting.
   - `AMBIGUOUS` fact → note for escalation; a bounded cross-examination round is not
     wired, so do not claim one ran.
   - `RECOMMENDATION` → confidence × severity × category weight, with **minority-veto**
     for unresolved high-severity safety claims.
4. **Do NOT compute the aggregate score, and do NOT decide the verdict.** The gate
   reads these same files and owns both.
5. **Report** the control message below.

## Hard rules

- **Never average away a verified finding.** A judge consolidates; it does not negotiate.
- **Never invent a reviewer's findings**, and never invent a tool result.
- **Never report a pass on prose.** The gate's exit code is the verdict.
- **Never re-review the code yourself.** You did not run the probes; the harness did.
- Confidence is a **signal, not a decider**.
- Keep the signal-to-noise term in the score so "flag everything" cannot raise the aggregate.

## Output

Emit a `control` message carrying `termination`, `reason`, `iterations`, and
`final_scores`. `termination` ∈ `satisfied | continue | blocked | escalate`.

That message is for the log. The loop writes it and does not parse it — the gate decides
the verdict, from the reviewer files, and its own vocabulary is
`satisfied | not_satisfied`.
