---
name: reviewer-performance
description: "Review a Nix diff for build, closure, and eval cost."
version: 1.1.0
author: user, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
category: review-council
metadata:
  hermes:
    tags: [review, rubric, performance, closure, evaluation, nix]
    related_skills: [review-council-orchestrator]
---

# Performance Review Rubric (Nix / NixOS / Clan)

Review **only the diff** at the pinned SHA. This dimension carries a **low β** —
the orchestrator leans on your judgment, so honest uncertainty beats a confident
number.

## The determinism rule

> Absolute wall-clock numbers **never** enter the score. A performance finding is
> valid only as (a) a **relative regression against a pinned baseline on the same
> runner class**, or (b) a **structural mechanism** (IFD, overlay churn, closure
> growth) that is deterministic.

If you cannot measure it deterministically, mark the claim `AMBIGUOUS` and lower
your confidence.

## Scoring anchors (0–100)

| Score | Meaning |
|---|---|
| 95–100 | No measurable or structural cost, or strictly cheaper. |
| 80–94 | Negligible cost, no mechanism that compounds. |
| 60–79 | Real cost, bounded and local to this host. |
| 30–59 | Cost that compounds (fleet-wide rebuild, IFD on a hot path). |
| 1–29 | Serious regression (blocks evaluation, doubles closure). |
| 0 | Change makes the configuration fail to evaluate. |

## Checklist

**Evaluation cost**
- [ ] Import-from-derivation (IFD) introduced — anything forcing a build during evaluation.
- [ ] Overlay added or changed in a way that invalidates the whole `pkgs` fixpoint.
- [ ] `builtins.readFile` of a large file during eval; expensive `lib` recursion.
- [ ] `nix flake check` wall time materially increased (measure, do not guess).

**Closure size & build cost**
- [ ] `environment.systemPackages` grew with dev-only tools.
- [ ] A new runtime dependency pulled into the system closure unnecessarily.
- [ ] `home-manager` vs system layering changed so packages duplicate.
- [ ] A widely-shared input perturbed, forcing mass rebuilds.

**Cache-friendliness**
- [ ] Binary caches / `substituters` not configured for a new heavy dependency.
- [ ] A change that guarantees cache misses (e.g. rebuilding `nixpkgs` via an overlay).
- [ ] `nix.gc` / store growth left unmanaged.

## Commands (ground truth — run these first)

```bash
nix path-info -Sh --recursive <toplevel>          # closure size (human)
nix path-info --json --closure-size <path>        # closure size (machine: narSize, closureSize)
nix-tree <path> ; nix-tree --diff <old> <new>     # per-path size + diff totals
nix-diff <old.drv> <new.drv>                      # derivation-level rebuild surface
nix store diff-closures <before> <after>          # added/removed packages + size deltas
NIX_SHOW_STATS=1 nix eval .#<attr> 2>stats.txt    # cpuTime, thunk/GC counts
nix eval --option allow-import-from-derivation false .#<attr>   # IFD gate: 0 = no IFD
nix flake check --no-build                        # eval-only cost
```

> **Devshell only:** `nix-tree`, `nix-diff` and `nix-du` are contributor tooling, NOT
> in the shipped toolchain — a container review will not have them. This dimension
> ships `nix path-info`, `nix store diff-closures`, `nix eval` and `nix flake check`.

> **Correction:** `nix store du` **does not exist**. Use `nix path-info -Sh`,
> `du -sh /nix/store`, or (devshell) `nix-du`.

**Gate (multiplicative):** IFD present → **performance category × 0.6**.

IFD is the single most important performance code signal: any store path read
during evaluation pauses evaluation and serialises realisation, so it cannot be
parallelised.

## Evidence

Every finding carries `file`, `line_range`, the **mechanism** in words, and the
command you ran with its observed output. A regression ratio must name the
baseline it was measured against.

## Output

Findings as JSON per review.msg/v1, plus `score` 0–100 and a one-line rationale.
In `metrics`, list which signals were **measured** and which were **inferred**.

Write tersely: one sentence per `claim`, no hedging, no restating the diff. The
`caveman-review` skill is the format; the full contract is in the review prompt.
