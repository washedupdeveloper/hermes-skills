---
name: pr-description
description: "Use when writing a pull request body as evidence."
version: 1.0.0
author: "Dex Horthy (humanlayer, show-me), via mattpocock/skills, adapted for Hermes"
license: MIT
platforms: [linux, macos, windows]
category: software-development
metadata:
  hermes:
    tags: [pull-request, review, evidence, blast-radius, communication]
    source: mattpocock/skills@5863806dd4e15c63174bee4e7515a4256792ecfa (engineering/pr, crediting humanlayer/show-me)
    related_skills: [github, two-axis-review, verify-and-stop, release-versioning]
---

# Pull request description

The body is the reviewer's only evidence before they read the diff, and often the only thing
a future reader has after the branch is deleted. It earns three sections and no preamble.

The bundled `github` skill owns the mechanics (`gh pr create`, `gh pr edit`, reviews,
checks). This skill owns what the body says.

## When to Use

- Opening a PR, or updating one after review or a scope change.
- A PR body is a changelog, a wall of prose, or empty.
- A change is risky enough that the reviewer must know how it fails before reading it.
- Don't use for: a release note (`release-versioning`), or a commit message.

## The template

```markdown
## Summary

<the smallest view that makes the point clear>

## Evidence

- **Before:** <failing test run, output, screenshot, measurement>
  **After:** <the same, passing>

## Merge danger

**Door:** <one-way or two-way>

**Blast radius:** <one word>

<optional: what breaks, and for whom>
```

Canonical heading casing varies by repository; match the project's existing PRs. The three
sections are the requirement, not the exact words.

## Summary: pick a view, not a sentence

Choose the **smallest representation** that makes the key point clear. Prose is the last
resort, because a reviewer reading a diff can verify a picture and cannot verify a claim.

| The point is | Show |
|---|---|
| logic or an algorithm | pseudocode |
| runtime control flow | a call tree |
| UI structure | a component tree, with the state and module boundaries that matter |
| file responsibility, or a broad refactor | a shallow file tree |
| interaction between components over time | a `mermaid` sequence diagram |
| what changes inside a shape that already exists | a diff of that shape |

```text
submitForm
  createSession
    persistPrompt
    launchAgent
  navigateToSession
```

```diff
 <SessionPage>
   useSessionEvents()
   <SessionToolbar>
+    <RunSkillButton />
   <SessionTimeline>
+    <SkillResultCard />
```

Guidance: put each view next to the short text it supports, keep only the calls, files,
props, states and boundaries needed for the reviewer's current question, and use as few of
these as the change needs. Using all of them is a sign none of them was chosen.

## Evidence: before and after

Concrete proof the change works, in the reviewer's own vocabulary — the command and its
result, not a summary of it.

- **Execution evidence is the baseline**: the test that failed, the same test passing, with
  the exact invocation. `verify-and-stop` owns what counts as proof; this section reports
  what it produced.
- **A screenshot or recording is the strongest evidence** for a visual change, when the
  environment can produce one.
- **A pending check is reported as pending.** "CI will pass" is not evidence, and a claim
  made before the run is a prediction.
- **Skip the section only by saying so.** A change with no observable before/after ("typo")
  says that in one line; a silently empty Evidence section reads as unverified.

## Merge danger

Two facts a reviewer needs and rarely gets:

- **The door.** A **two-way** door can be walked back by reverting the commit: a refactor, a
  flag, a new endpoint nobody calls yet. A **one-way** door cannot: a destructive migration,
  a published API shape, a deleted table, a name other repositories now depend on, anything
  that leaves the repository and comes back.
- **The blast radius**, in one word — `none`, `local`, `package`, `service`, `everyone` —
  followed by the ramifications in a sentence or two. What breaks, for whom, and what the
  first symptom looks like.

If the door is one-way, say what the rollback would actually be, or that there is none. That
sentence is the reason the section exists.

## Rules

- **No preamble.** No "This PR…", no greeting, no restating the title.
- **Use the project's words.** The glossary's term, the domain name, the existing symbol. A
  body that invents vocabulary for the thing being changed is a second spec.
- **Keep it readable in a terminal.** PR bodies get read in `gh pr view`, in a diff viewer
  and on a phone; long unbroken paragraphs fail in all three.
- **Update it after a review round.** A body that describes the pre-review shape is worse
  than stale — the reviewer assumes it is current.

## Pitfalls

1. **A Summary that is a changelog.** File-by-file is what the diff already does.
2. **Evidence as an adjective.** "Thoroughly tested" is not a result.
3. **Every PR declared a two-way door.** The classification is only useful when it can come
   out one-way.
4. **Blast radius missing the actual sufferer.** "service" without saying which consumers
   care is a word, not a fact.
5. **A diagram that shows the architecture rather than the change.**
6. **A body written once.** It is a document with the diff's lifetime, not a one-time form.

## Verification

- [ ] Three sections present, or a section's absence is stated with its reason
- [ ] The Summary uses a view appropriate to the change, not prose-by-default
- [ ] Evidence names the exact command or artifact, before and after
- [ ] The door is classified, and a one-way door states its rollback (or that there is none)
- [ ] Blast radius is one word plus a sentence naming who suffers
- [ ] No sentence in the body is contradicted by the diff