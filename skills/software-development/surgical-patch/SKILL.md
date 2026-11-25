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
writes: [none]
side_effects: [none]
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

## Instrumentation you add is part of the patch

- **Tag every temporary log with one unique prefix** (`[DEBUG-a4f2]`), so cleanup is one
  search. Untagged logs survive the patch; tagged ones die with it.
- **Remove the instrumentation before declaring done**, and say what you searched for.
- **A missing seam is itself a finding.** The regression test belongs at a seam that exercises
  the real bug pattern at its call site. When the only available seam is too shallow — a
  single-caller test for a bug that needs several, a unit that cannot reproduce the chain
  that triggered it — a test there is false confidence. Record that the architecture stopped
  the bug being locked down, and report it instead of writing the shallow test.

## When a fix fails twice

- **Two fixes that share a premise have failed the same gate.** Write the premise down, the
  assumption both fixes made, and test it directly before writing a third fix that assumes it.
- The third attempt is then a hypothesis about the premise, not another patch at the same layer.

## When the findings cluster, delete the state instead of patching it

A reviewer loop that keeps returning findings in one subsystem is not returning new bugs; it
is returning the same defect wearing different masks. The signal is the count holding steady —
seven findings, fix them, six findings in the same three functions — and the tell is that each
fix is *invalidating something*: a cache entry, a memo, a derived index, a copy of state that
already exists elsewhere.

When you see that pattern, stop patching and ask what state has to be kept in sync. If the
answer is "a cache I maintain by hand", delete the cache and recompute from the source of truth
on every read. One instance fixed is a finding closed; the class removed is the loop ended. A
handler that must invalidate itself in six places is the bug, not any one of the six.

This is the one exception to "the narrowest layer": the narrowest *correct* layer can be the
one that removes state rather than the one that adds a guard to it. Record why in the commit, so
the deletion does not read as scope drift.

## A guard you add must be proven against the legitimate case

Every fix that refuses something needs two tests: the input it must reject, and the ordinary
input it must still accept. A traversal guard written against a hand-built fixture passed while
rejecting `tar -cf x.tar .`, because the legitimate archive carries a `.` directory header that
no hand-built fixture contains. Read the format's own specification for what real producers emit
before writing the rejection, and generate the accept-case with the real tool rather than by hand.

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
