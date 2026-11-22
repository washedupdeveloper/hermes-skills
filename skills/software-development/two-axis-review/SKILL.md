---
name: two-axis-review
description: "Review a branch on two axes: standards and spec."
version: 1.0.0
author: "Matt Pocock (mattpocock/skills, code-review), adapted for Hermes"
license: MIT
platforms: [linux, macos, windows]
category: software-development
metadata:
  hermes:
    tags: [review, standards, spec, code-smells, delegation]
    source: mattpocock/skills@5863806dd4e15c63174bee4e7515a4256792ecfa (engineering/code-review)
    related_skills: [requesting-code-review, to-spec, verify-and-stop]
writes: [none]
---

# Two-axis review

A change can follow every convention and still build the wrong thing, or do exactly what
the ticket asked while breaking the repository's rules. One review cannot answer both
questions without one answer burying the other, so run them as **two axes, side by side,
never merged**:

- **Standards** — does the change follow what this repository documents about how code is
  written?
- **Spec** — does the change do what the originating issue, spec or ticket asked?

`requesting-code-review` owns the mechanical pre-commit pass (security scan, gates,
auto-fix). This skill owns the two judgement questions above, over a diff against a fixed
point.

## When to Use

- "Review this branch", "review since `main`", "review the changes on this PR".
- A reviewer needs to know whether the work matches its spec, not only whether it compiles.
- A change is about to merge and nobody has checked scope creep.
- Don't use for: a mechanical lint or typecheck run; a review with no fixed point; a review
  of code you just wrote without saying so (the bias is worth naming).

## 1. Pin the fixed point

The fixed point is whatever the user named: a SHA, a branch, a tag, `HEAD~5`. If they named
none, ask — do not guess `main`.

```sh
git rev-parse <fixed-point>            # it must resolve
git diff --stat <fixed-point>...HEAD   # three dots: against the merge base
git log <fixed-point>..HEAD --oneline
```

An unresolvable ref or an empty diff fails **here**, in the caller's context, where the
error is one line. It must not fail inside two delegated children.

## 2. Find the spec

Search in this order, and stop at the first hit:

1. Issue references in the commit messages (`#123`, `Closes #45`) — fetch them with `gh`.
2. A path the user passed.
3. A spec or ticket file under `docs/`, `openspec/`, `specs/` or `docs/tickets/` matching
   the branch name or the feature.
4. Ask. If there is no spec, say so: the Spec axis is **skipped**, not passed.

## 3. Find the standards sources

Grep the repository for the files that state how code is written: `CONTRIBUTING.md`,
`AGENTS.md`, `CODING_STANDARDS.md`, `docs/adr/*`, a style guide, a lint config with
comments. Read them; do not infer a standard from the surrounding code.

Where a repository documents nothing, the smell baseline below still applies — as
judgement, never as a violation.

## The smell baseline

Twelve Fowler smells (*Refactoring*, ch. 3). Each is **what it is → how to fix it**. Two
rules bind the table:

- **The repository overrides.** A documented local standard always wins; where it endorses
  something the baseline flags, suppress the smell.
- **Always a judgement call.** "Possible Feature Envy", never "violation". Skip anything
  tooling already enforces.

| Smell | What it is | Fix |
|---|---|---|
| Mysterious Name | A name that does not reveal what a function, variable or type does or holds. | Rename it; if no honest name comes, the design is murky. |
| Duplicated Code | The same shape appears in more than one hunk or file. | Extract the shape, call it from both. |
| Feature Envy | A method reaching into another object's data more than its own. | Move the method onto the data it envies. |
| Data Clumps | The same few fields or parameters keep travelling together. | Bundle them into one type. |
| Primitive Obsession | A primitive or string standing in for a domain concept. | Give the concept its own small type. |
| Repeated Switches | The same `switch` or `if`-cascade on the same type recurs. | Polymorphism, or one map both sites share. |
| Shotgun Surgery | One logical change forces scattered edits across many files. | Gather what changes together into one module. |
| Divergent Change | One module is edited for several unrelated reasons. | Split so each module changes for one reason. |
| Speculative Generality | Abstraction, parameters or hooks for needs the spec does not have. | Delete it; inline back until a real need shows. |
| Message Chains | Long `a.b().c().d()` navigation the caller should not depend on. | Hide the walk behind one method on the first object. |
| Middle Man | A class or function that mostly delegates onward. | Cut it; call the real target. |
| Refused Bequest | A subclass that ignores or overrides most of what it inherits. | Drop the inheritance, use composition. |

## 4. Dispatch both axes in parallel

One `delegate_task` call, two tasks, so neither axis pollutes the other's context — and so
the diff is read once per question rather than once per file.

Each child gets the **commands**, not a pasted patch: it can run `git diff` and `git log`
itself, and a patch pasted into a goal is stale the moment the tree moves. Each child also
gets its sources, because it cannot see this skill.

**Standards child** — the diff command, the commit list, the standards-source paths, and
the smell table **copied in full**. Brief:

> Report, per file or hunk where relevant: (a) every place the diff breaks a documented
> standard, citing the file and the rule; (b) any baseline smell, named, quoting the hunk.
> A documented standard is a hard finding; a smell is always a judgement call, and a
> documented standard overrides the baseline. Skip what tooling enforces. Under 400 words.

**Spec child** — the diff command, the commit list, and the spec's path or fetched text.
Brief:

> Report: (a) requirements the spec asked for that are missing or partial; (b) behaviour
> in the diff nobody asked for (scope creep); (c) requirements that look implemented but
> whose implementation looks wrong. Quote the spec line for each finding. Under 400 words.

## 5. Aggregate without merging

Present the two reports under `## Standards` and `## Spec`, lightly cleaned, findings
intact. Close with one line per axis: the finding count, and the worst issue **within**
that axis.

Do not rerank across axes and do not pick a single winner. That separation is the whole
method: a change that passes Standards and fails Spec is a different problem from the
reverse, and it has a different fix — rewrite the code, or renegotiate the spec.

## Pitfalls

1. **One combined review.** The axis that reports second gets read as the answer.
2. **Letting a child re-derive the fixed point.** Give the literal ref; two children with
   two bases report two different diffs.
3. **Upgrading a smell to a violation.** Then the report reads as twelve blockers and the
   two real hard findings disappear.
4. **Spec absent, Spec axis "passed".** A missing spec is `skipped` and named — silence
   reads as approval.
5. **Skipping the standards sources.** Without them the baseline becomes the standard,
   which is exactly what the override rule forbids.
6. **Pasting the diff into the child's goal.** It goes stale, and a large goal costs more
   than the read it saves.

## Verification

- [ ] The fixed point resolved, and the three-dot diff was non-empty before dispatch
- [ ] The spec source is named in the report, or the axis is reported as skipped
- [ ] Every standards source found in step 3 is listed in the report
- [ ] Two reports under two headings, with no merged finding list and no cross-axis winner
- [ ] Every smell finding is labelled a judgement call; every hard finding cites a file and
      a rule