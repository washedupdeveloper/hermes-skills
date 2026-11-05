---
name: reviewer-correctness
description: "Review a Nix diff: eval, options, runtime evidence."
version: 1.2.0
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

Review **only the diff** at the pinned SHA. Correctness is the one dimension with a
**hard deterministic gate**.

## Hard gate

> A failing `nix flake check`, a configuration that does not evaluate, or a changed
> `system.stateVersion` **caps this category at 0**. Report the cap explicitly with
> the command and its real output. Never soften it.

## Runtime gate — what the page does, not what the diff says

Source checks cannot answer a runtime question. A component that reads correctly can throw on
hydration; a route that resolves in a unit test can 404; a selector mocked in a test can be absent
from the real DOM. Reviewing that by reading produces a confident wrong answer, which is worse than
"not observed" — so this dimension has a second gate, and it is evidence or a stated absence:

```bash
council probes browser --repo .                       # static entry: index.html, dist/index.html, …
COUNCIL_WEB_URL=http://127.0.0.1:3000 council probes browser --repo .
COUNCIL_BROWSER_CMD='nix run nixpkgs#chromium --' council probes browser --repo .
```

> **Observed failure** (page did not load, an empty render, a page error, a missing asserted
> selector) → **cap this category at 30**, and the finding cites the DOM dump and screenshot paths
> the probe reported.
>
> **`ran: false`** — no driver, or no web entry point — → **cap this category at 60** and the
> rationale MUST contain `runtime not observed`. It must never say "appears correct", "should
> work" or "looks right": those are the sentences an unobserved runtime produces.
>
> An unobserved runtime **never** scores 100, and a page with no probe result at all is
> `AMBIGUOUS`, not clean.

`browser` is beta-bearing: when it cannot run, the harness reports a lower confidence, not a pass.
That is the intended failure mode — the report says less was measured, instead of scoring what it
did not see.

## Scoring anchors (0–100)

| Score | Meaning |
|---|---|
| 95–100 | Runtime **observed** clean, evaluates clean, options typed correctly, behaviour covered by a check. |
| 80–94 | Evaluates clean and the page loads; a minor guard or test is missing. |
| 60–79 | Evaluates, but a real semantic gap (wrong type, wrong precedence) — or the runtime could not be observed at all. |
| 30–59 | Wrong effective behaviour, an unguarded misconfiguration risk, or a runtime failure the change caused. |
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

**Runtime (any browser-facing change)**
- [ ] The page loads without a page error, or the report says `runtime not observed` and is capped.
- [ ] The app mounted: visible text, or a media element, in the rendered DOM.
- [ ] Every selector a feature depends on is asserted in `.review-council/web-assertions.json`
      (or the finding says which selector you could not confirm).
- [ ] The finding carries the DOM dump and screenshot paths the probe reported — evidence, not
      prose.
- [ ] Client-side routing and state were exercised, not just first paint, when the change touches
      them.

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
council probes browser --repo .                # GATE (web): load the page and report what it did
COUNCIL_WEB_URL=http://127.0.0.1:3000 council probes browser --repo .   # a dev server you started
COUNCIL_BROWSER_CMD='nix run nixpkgs#chromium --' council probes browser --repo .  # no chromium on PATH
nix-fast-build --flake .#checks --result-format json --result-file out.json  # per-check pass/fail
nixfmt --check <files>
```

> **Devshell only:** `nix-fast-build` is a contributor accelerator, not in the
> shipped toolchain; its per-check results come from `nix flake check`, which ships.

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
