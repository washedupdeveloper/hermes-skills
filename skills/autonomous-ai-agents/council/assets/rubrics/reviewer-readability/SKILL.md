---
name: reviewer-readability
description: "Review a Nix diff for format, structure, and dead code."
version: 1.1.0
author: user, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
category: review-council
metadata:
  hermes:
    tags: [review, rubric, readability, formatting, dead-code, nix]
    related_skills: [review-council-orchestrator]
---

# Readability & Maintainability Review Rubric (Nix / NixOS / Clan)

Review **only the diff** at the pinned SHA. Judge the readability of the *change*,
not of the whole repo.

## Scoring anchors (0–100)

| Score | Meaning |
|---|---|
| 95–100 | Formatter-clean, clear structure, no dead code, documented where it matters. |
| 80–94 | Minor nits only; a reader is not slowed down. |
| 60–79 | Some structure/naming friction; still understandable. |
| 30–59 | Materially hard to read; a newcomer would struggle. |
| 1–29 | Structurally confusing, or dead code that misleads. |
| 0 | Unformatted and incoherent, or the diff is unreviewable. |

## Checklist

**Formatting**
- [ ] Not formatter-clean under the repo's formatter (respect the repo's choice —
      do not impose a different one).
- [ ] Inconsistent indentation or alignment introduced.

**Structure**
- [ ] A module now does more than one thing; the concern should be split.
- [ ] Deeply nested attrsets where a `let` binding or helper would flatten it.
- [ ] Long option paths repeated verbatim instead of bound once.
- [ ] New logic placed in a file that contradicts the repo's layout convention.

**Naming**
- [ ] Names that do not say what the thing is; inconsistent prefixes.
- [ ] Option names inconsistent with siblings.

**Dead & unused code**
- [ ] `deadnix` findings: unused args, unused `let` bindings.
- [ ] Commented-out blocks left behind.
- [ ] `lib.mkIf` branches that can never fire.

**Idiom**
- [ ] `with pkgs;` overuse (statix flags it).
- [ ] Reinventing a helper that already exists in the repo's `lib/`.
- [ ] Manual `inherit` where `lib.attrsets` reads better.

**Documentation**
- [ ] Non-obvious module with no comment explaining *why*.
- [ ] Machine or module added without any README entry.
- [ ] Stale comment contradicting the code.

## Severity discipline

Distinguish **nitpick** / **refactor suggestion** / **maintainability risk**. Do
not inflate nitpicks — volume lowers your score via the aggregate's
signal-to-noise term.

## Commands (ground truth — run these first)

```bash
nixfmt --check <files>          # the repo's formatter — respect its choice, do not impose another
statix check . -o json          # JSON (requires a --all-features build)
deadnix --output-format json --fail .
tokei -t Nix --output json | jq .Nix.code    # devshell: read a density by hand
```

> **The KLOC denominator comes from the framework, not `tokei`/`cloc`** — both are
> devshell-only conveniences for reading a report by hand; the ratio a finding is
> normalised against is the framework's own source-suffix count.

A finding that names a `statix`/`deadnix` rule id is worth more than an opinion.
Formatting is a **separate binary gate**, not folded into density.

**Gate (multiplicative):** `nixfmt --check` fails → **readability category × 0.5**.

**Deadnix FP note:** fires on intentionally-unused lambda pattern names —
`--no-lambda-pattern-names` suppresses the `callPackage` case. **Do not adopt
`nix-linter`** (abandoned; statix is its successor).

## Evidence

`file`, `line_range`, the rule id or the concrete reader harm, and a **concrete
idiomatic fix** (show the idiom, do not lecture).

## Output

Findings as JSON per review.msg/v1, plus `score` 0–100 and a one-line rationale.

Write tersely: one sentence per `claim`, no hedging, no restating the diff. The
`caveman-review` skill is the format; the full contract is in the review prompt.
