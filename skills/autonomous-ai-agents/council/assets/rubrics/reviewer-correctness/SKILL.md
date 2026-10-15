---
name: reviewer-correctness
description: "Review a Nix diff for eval errors and option misuse."
version: 1.1.0
author: user, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
category: review-council
metadata:
  hermes:
    tags: [review, rubric, correctness, evaluation, testing, nix]
    related_skills: [review-council-orchestrator]
---

# Correctness & Testing Review Rubric (Nix / NixOS / Clan)

Review **only the diff** at the pinned SHA. Correctness is the one dimension with
a **hard deterministic gate**.

## Hard gate

> A failing `nix flake check`, a configuration that does not evaluate, or a changed
> `system.stateVersion` **caps this category at 0**. Report the cap explicitly with
> the command and its real output. Never soften it.

## Scoring anchors (0–100)

| Score | Meaning |
|---|---|
| 95–100 | Evaluates clean, options typed correctly, behaviour covered by a check. |
| 80–94 | Evaluates clean; a minor guard or test is missing. |
| 60–79 | Evaluates, but a real semantic gap (wrong type, wrong precedence). |
| 30–59 | Wrong effective behaviour, or an unguarded misconfiguration risk. |
| 1–29 | Fails to evaluate on some path, or silently overrides an intended value. |
| 0 | `nix flake check` fails, a config does not evaluate, or `stateVersion` changed. |

## Checklist

**Evaluation**
- [ ] Every affected `nixosConfigurations.<host>` still evaluates.
- [ ] New module options declared with a `type` and a sane `default`.

**Option semantics**
- [ ] Wrong type: `types.str` where `types.lines` is needed, `types.path` vs
      `types.str`, `types.listOf` vs a single value.
- [ ] A value that cannot satisfy its declared type.
- [ ] Missing `default` on a required option used elsewhere.

**Precedence**
- [ ] `lib.mkDefault`/`mkForce`/`mkIf`/`mkMerge` producing an effective value
      different from the intent.
- [ ] A `mkForce` that silently defeats a value another module sets.

**Immutability**
- [ ] `system.stateVersion` or `home.stateVersion` changed (must never change after install).

**Guards**
- [ ] Missing `assertions`/`warnings` where a misconfiguration should fail loudly.

**Tests & CI**
- [ ] Non-trivial new module with no `checks` entry.
- [ ] Behaviour testable by `runNixOSTest`/`nixosTest` but untested.
- [ ] git-hooks/CI not running `nix flake check`.

**Lock discipline**
- [ ] `flake.lock` not matching `flake.nix`.
- [ ] Inputs updated without intent in the diff.

## Commands (ground truth — run these first)

```bash
nix flake check --no-build --keep-going        # HARD GATE; --keep-going collects all errors
nix flake check --keep-going                   # full: builds every checks.* and toplevel (slow)
nix eval .#nixosConfigurations.<host>.config.system.build.toplevel.drvPath   # option typecheck
nix eval --option pure-eval true .#<attr>      # detects impurity (network, abs paths, currentSystem)
nix-instantiate --parse <file>                 # syntax errors, cheap pre-check
nixos-rebuild build --flake .#<host>           # build before switch (needs a Linux host)
nixos-option <option.path>                     # confirm an option exists, its type/default/value
clan vars check --flake .                      # GATE: all generated vars present & current
nix-fast-build --flake .#checks --result-format json --result-file out.json  # per-check pass/fail
nixfmt --check <files>
```

Quote the real output. **Never assert that something "should evaluate"** — if you
did not run it, mark the claim `AMBIGUOUS`.

**Multiplicative gates (not averaged):**
- `nix flake check` fails → **correctness category = 0**
- `clan vars check` fails → correctness × 0.5

`clan vars check` reports "missing" until `clan vars generate` has run once.

**Scope note:** `nixpkgs-hammering` targets *nixpkgs package expressions*, **not**
NixOS/Clan modules — use it only if the flake gains `packages`.

## Output

Findings as JSON per review.msg/v1, plus `score` 0–100 and a one-line rationale.
Put the commands you ran and their exit codes in `metrics`.

Write tersely: one sentence per `claim`, no hedging, no restating the diff. The
`caveman-review` skill is the format; the full contract is in the review prompt.
