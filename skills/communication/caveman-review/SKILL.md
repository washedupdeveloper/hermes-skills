---
name: caveman-review
description: Use when reviewing a diff or PR. One line per finding.
version: 1.0.0
author: JuliusBrussee/caveman, adapted by user
license: MIT
platforms: [linux, macos, windows]
category: communication
metadata:
  hermes:
    tags: [code-review, brevity, tokens, findings, communication]
    related_skills: [caveman, council, requesting-code-review]
    source: https://github.com/JuliusBrussee/caveman @ d262ab3882952a59312ff3537cd86d894523c5ab
---

# caveman-review

Write review comments terse and actionable. One line per finding. Location, problem,
fix. No throat-clearing.

This is the output format for findings that another agent or the harness will read —
the council's reviewer-to-harness payload. Verbose prose in a findings file is paid
for on every read.

## Format

`L<line>: <problem>. <fix>.` — or `<file>:L<line>: ...` when reviewing multi-file
diffs.

**Severity prefix (optional, when mixed):**

- `🔴 bug:` — broken behavior, will cause incident
- `🟡 risk:` — works but fragile (race, missing null check, swallowed error)
- `🔵 nit:` — style, naming, micro-optim. Author can ignore
- `❓ q:` — genuine question, not a suggestion

## Drop

- "I noticed that...", "It seems like...", "You might want to consider..."
- "This is just a suggestion but..." — use `nit:` instead
- "Great work!", "Looks good overall but..." — say it once at the top, not per
  comment
- Restating what the line does — the reviewer can read the diff
- Hedging ("perhaps", "maybe", "I think") — if unsure use `q:`

## Keep

- Exact line numbers
- Exact symbol/function/variable names in backticks
- Concrete fix, not "consider refactoring this"
- The *why* if the fix is not obvious from the problem statement

## Examples

Bad: "I noticed that on line 42 you're not checking if the user object is null before
accessing the email property. This could potentially cause a crash if the user is not
found in the database. You might want to add a null check here."

Good: `L42: 🔴 bug: user can be null after .find(). Add guard before .email.`

Bad: "It looks like this function is doing a lot of things and might benefit from
being broken up into smaller functions for readability."

Good: `L88-140: 🔵 nit: 50-line fn does 4 things. Extract validate/normalize/persist.`

Bad: "Have you considered what happens if the API returns a 429? I think we should
probably handle that case."

Good: `L23: 🟡 risk: no retry on 429. Wrap in withBackoff(3).`

## Auto-clarity

Drop terse mode for: security findings (CVE-class bugs need full explanation plus a
reference), architectural disagreements (need rationale, not a one-liner), and
onboarding contexts where the author is new and needs the *why*. In those cases write
a normal paragraph, then resume terse for the rest.

## Boundaries

Reviews only — does not write the code fix, does not approve or request changes, does
not run linters. Output the comment(s) ready to paste into the PR. "stop
caveman-review" or "normal mode": revert to verbose review style.

A deterministic gate is a separate claim from a review: never report a finding as
verified because the terse format makes it look decisive. Cite the evidence.
