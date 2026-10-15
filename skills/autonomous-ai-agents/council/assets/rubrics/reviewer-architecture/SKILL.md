---
name: reviewer-architecture
description: "Review a Nix diff for layering, interfaces, and reuse."
version: 1.1.0
author: user, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
category: review-council
metadata:
  hermes:
    tags: [review, rubric, architecture, layering, modules, nix]
    related_skills: [review-council-orchestrator]
---

# Architecture & Design Review Rubric (Nix / NixOS / Clan)

Review **only the diff** at the pinned SHA. Architecture is judged **in context**,
not line-by-line.

## The β rule

> Architecture has **no deterministic signal** unless the repo declares
> architecture rules (import-linter-style contracts, ArchUnit equivalents, explicit
> module boundaries). Without them this dimension is LLM judgment: emit
> `claim_type: RECOMMENDATION`, mark confidence honestly, and expect a **low β**.
> Overconfidence here is the most expensive mistake in this dimension.

## Scoring anchors (0–100)

| Score | Meaning |
|---|---|
| 95–100 | Clean layering, no duplication, interfaces explicit, composes naturally. |
| 80–94 | Sound; a small structural wrinkle. |
| 60–79 | Works, but the change makes a future change harder. |
| 30–59 | Wrong layer, or duplication that will drift. |
| 1–29 | Structural coupling that will cause defects; import cycles. |
| 0 | The change is incoherent with the repo's model. |

## Checklist

**Flake structure**
- [ ] New file placed against the repo's auto-import convention.
- [ ] flake-parts module organisation consistent with siblings.

**Layering**
- [ ] Concern implemented in the wrong layer: flake module vs NixOS module vs
      home-manager module vs clan module.
- [ ] Host-specific config leaking into a shared module, or vice versa.

**Interfaces**
- [ ] `specialArgs` vs `_module.args` used correctly and consistently.
- [ ] `inputs` threaded the way the rest of the repo threads them.
- [ ] No import cycle; no hidden coupling through globals.

**Reuse**
- [ ] Logic duplicated across machines/modules that belongs in `lib/`.
- [ ] A helper already in `lib/` re-implemented inline.

**Topology (Clan)**
- [ ] Machine/module composition consistent with the clan model.
- [ ] A machine that should compose a module does not.

**Separation of concerns**
- [ ] Secrets vs configuration vs generated `vars` kept distinct.
- [ ] The right system owning each concern.

**Evolution**
- [ ] `nixos-unstable` vs release pinning trade-off made deliberately.
- [ ] The change has a sane upgrade path.

## Commands

```bash
# module set evaluates as modules (deterministic)
nix eval --expr 'let l = (builtins.getFlake (toString ./.)).inputs.nixpkgs.lib; in (l.evalModules { modules = [ ]; }).config' --impure
nix eval .#nixosConfigurations.<h>.options --apply builtins.attrNames    # declared option set
clan machines list ; clan machines build <m> --dry-run                   # topology + config validity
clan show ; clan select ; clan vars list <m>                            # meta / values / vars
```

| Signal | Method | Determinism |
|---|---|---|
| Module evaluates | `lib.evalModules { modules = [...]; }` | deterministic |
| Import cycles | evaluation failure ("infinite recursion") under `nix flake check` | deterministic |
| `specialArgs` vs `_module.args` | grep both mechanisms in `flake.nix`/`clan.nix` | deterministic |
| Dead module files | `deadnix` + "not reachable from flake.nix imports" | deterministic |
| `mkIf`/`mkMerge` misuse | grep/AST: `mkIf` outside a `config` attrset, `mkIf` on `_module.args` | heuristic |
| Layering violation | a module under `modules/home/` importing `nixosModules` | heuristic |
| Declared-but-never-defined option | count `mkOption` vs `config.<x> =` per module | heuristic |

Heuristic signals **require human confirmation** — mark them as such.

**Rule of thumb:** `specialArgs` is only for arguments needed during module
*structure* resolution (imports); everything else belongs in `_module.args`. `mkIf`
is entirely useless for `_module.args`.

**No mature deterministic linter exists for NixOS module design.**
`nixpkgs-hammering` targets nixpkgs package expressions, not NixOS/Clan modules.
Architecture remains the lowest-β dimension.

## Evidence

`file`, `line_range`, and the **structural consequence** in words ("this couples X
to Y", "this duplicates Z across N machines"). Not an aesthetic preference.

## Output

Findings as JSON per review.msg/v1 with `claim_type: RECOMMENDATION`, plus `score`
0–100 and a one-line rationale.

Write tersely: one sentence per `claim`, no hedging, no restating the diff. The
`caveman-review` skill is the format; the full contract is in the review prompt.
