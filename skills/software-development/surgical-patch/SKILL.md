---
name: surgical-patch
description: Use when fixing a bug. Narrowest layer, regression proof.
version: 1.0.0
author: JuliusBrussee/caveman, adapted by user
license: MIT
platforms: [linux, macos, windows]
category: software-development
metadata:
  hermes:
    tags: [bugfix, scope, regression, verification]
    related_skills: [verify-and-stop, systematic-debugging, test-driven-development]
    source: https://github.com/JuliusBrussee/caveman @ d262ab3882952a59312ff3537cd86d894523c5ab
---

# surgical-patch

Reproduce the failure first when that is economical; otherwise capture the strongest
available evidence. Then patch, prove, stop.

## Rules

- Trace the symptom to the mechanism that owns it before editing.
- Change the **narrowest layer** that owns the incorrect behavior. Not the caller, not
  the wrapper, not the config that happens to be nearby.
- Preserve unrelated behavior, and preserve the user's uncommitted changes.
- **No cleanup, renaming, or abstraction outside the fix.** A drive-by tidy-up turns a
  one-line fix into an unreviewable diff and hides the real change.
- Add only the regression proof relevant to the task.

## Stop condition

Run the focused proof plus the nearest affected gate. Stop when the failure is fixed
and the regression proof passes.

## Failure modes this prevents

- **Symptom-patching** — guarding the call site when the function is wrong. The bug
  moves rather than closes.
- **Scope drift** — a fix that also reformats, renames, or refactors. The reviewer can
  no longer tell which line fixed the defect.
- **Unproven fix** — "it should work now". Without the regression proof there is no
  evidence the failure is gone, only that the code changed.
- **Test weakening** — editing the assertion instead of the behavior. Never do this to
  make a gate pass.

## Relationship to other skills

`systematic-debugging` owns finding the mechanism; this skill owns the *size* of the
change once you have it. `test-driven-development` owns writing the failing test first.
When a fix loop is driven by a gate, the gate's output is the evidence to repair
against — do not argue with it, and do not silence it.
