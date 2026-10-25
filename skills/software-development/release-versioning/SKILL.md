---
name: release-versioning
description: "Use when cutting a release. Semver policy and gates."
version: 1.1.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
category: software-development
metadata:
  hermes:
    tags: [semver, release, changelog, versioning, tagging, packaging]
    related_skills: [github, verify-and-stop, deterministic-quality-gates, nix-declarative-config]
---

# Versioning and releasing

This user wants Semantic Versioning followed **properly, in every project, for all future
work** — not interpreted case by case. So the policy is written down in the repository
(`docs/VERSIONING.md`), the definitions are concrete enough to apply without judgement,
and a gate enforces them. A version policy that lives only in a chat is a policy that
will be re-litigated next release.

## The deciding question

**Does an existing user have to change something to keep the same meaning?**

| answer | bump |
|---|---|
| yes | **major** |
| no, and there is something new | **minor** |
| nothing observable changed | **patch** |

Every rule below is that question applied to a specific surface. When a case is
ambiguous, ask this, not what feels bigger.

## Step 1 — enumerate the public surface before deciding anything

Write the list down in the repo. A surface you did not name is a surface you will break
in a patch. For a CLI-shaped product the list is: subcommands and their flags, the
declarative outputs (flake outputs, module options), the artifacts written to disk and
their fields, exit codes other programs branch on, the container entry point, the
install path of anything shipped, and **any computed number users tune a threshold
against**.

Enumerate it **from the tool, never from memory**: an output's name is not derivable from
its purpose. `packages.default` is whatever the author aliased it to — in one flake the
*toolchain*, not the product — and the CLI's name need not match the package's
(`apps.council` beside `packages.review-council`). Query the surface (`nix flake show
--json` for a flake, `--help` for a CLI) and write down what comes back. A name you
assumed is a name you will document wrong, and the wrong name costs every consumer a
failed build.

Then write the explicit **not public** list, because it is what keeps patches honest:
maintainer-only commands, internal modules no entry point reaches, fixtures, dev-only
tooling, and the wording of any message no program parses.

**The shipped tree is the public surface.** If the project builds a reduced tree for
users (runtime modules only) and a fuller one for maintainers, a module's audience in the
command table decides which list it is in — and the build must enforce that split, not a
comment.

## Step 2 — the definitions

**Major** — renaming or removing a subcommand, flag, option or output; removing or
retyping a field in a written artifact; changing what an exit code means; dropping a
platform; raising the interpreter floor.

**Minor** — a new subcommand, flag, option, output or artifact field with a default; a
new analyzer/probe/rule **together with** recalibrated constants and a note on which way
scores moved; a new platform.

**Patch** — a bug fix that restores documented behaviour; docs, comments, tests; an
internal refactor whose outputs are byte-identical; a dependency bump that changes no
output.

### A computed score is a surface that cannot be stable by construction

When the product emits a number a user calibrates a threshold against, a change in the
inputs moves it. The rule that resolves this without making every release major:

- scores are comparable **within a major version**, never across one;
- a release that moves them records the movement **and the fixture it was measured on**;
- and it must show the shipped threshold still yields the same verdicts on the pinned
  fixtures. If it does not, it either ships recalibrated constants or is **major** —
  because the user must recalibrate their own threshold, which is the deciding question
  answering "yes".

Do not decide this by feel. Measure the fixture before and after, and say which way it
moved and why. A tool added to a coverage denominator can move the score *down* while the
product got better — coverage falls where a newly expected tool cannot run.

## Step 3 — one place the version lives, and one check that it agrees with itself

Two numbers that can disagree is the classic release bug. Keep the version in the build
metadata (`pyproject.toml` `[project] version`) and the newest `## [X.Y.Z] — YYYY-MM-DD`
heading in `CHANGELOG.md`, then **assert they match**.

The check is a subcommand of the project's own CLI (so it is one command and it ships
with the tooling), and it fails on:

| condition | why |
|---|---|
| version is not `X.Y.Z` | one format, one parser |
| newest CHANGELOG release ≠ build metadata | two numbers, one truth |
| released versions are not strictly descending | the file is read top-down |
| a version appears twice | a bump that was re-run |
| a released heading has no valid date | when, for every release |
| `## [Unreleased]` is not the first section | where the next entry goes |
| a document claims a release other than the build metadata | the prose is a third copy, and the only one nothing was checking |

Add `--tag vX.Y.Z` for the same check against a pushed tag. Never resolve the version
from git inside the check — pass the tag in, so the same code works in a sandbox with no
git and in CI with the tag.

**The prose is a copy of the version too, so check it.** `README.md` and `docs/**` restate
the version as a claim to a reader — "Current release **v1.5.0**" — and the numeric checks
above never look at them, so build metadata, CHANGELOG and tag can all agree while a
document advertises a superseded release for several versions running. Extract the claim
shape and assert every hit equals the build metadata:

```python
PROSE = re.compile(r"[Cc]urrent release\s+\*{0,2}v(\d+\.\d+\.\d+)")
```

Scope it deliberately: **exclude `CHANGELOG.md` and any `runs/`-style record**, because
those are supposed to name versions that are no longer current, and a check that cannot
tell history from a claim punishes documentation for doing its job. Pin all three
behaviours — a stale claim fails naming the file and the version it claims, agreeing prose
passes in both the bold and plain spellings, and a historical mention does not trip it —
because a prose check with no negative fixture is a regex you merely hope is right.

**The pattern belongs in the production module, not in the test.** A prose check written
inside the test suite reports the drift *after* the operation that causes it, and the
operation cannot consult a regex it does not own — so every release needs a manual prose
edit that the enforcing check could never have prevented. Put one function in the version
module that both callers use: the checker calls it to report, the bump calls it to
rewrite. Have the test import that function rather than restating the pattern, or the
library ends up with three definitions of the same regex and no way to tell which is
authoritative. Generalised: **when a gate and the operation that violates it are separate
code, the operation must own the definition** — otherwise the gate is a report, not a
gate.

## Step 4 — enforce it in three places, or it is a wish

1. **The repository's own gate.** Run the check as a check (`checks.<name>` in a nix
   flake, a CI step, a `make check` target) so a stale version fails every push. The gate
   is what makes the policy real.
2. **CI, before the expensive build.** Compare the pushed tag against the build metadata
   **as the first step** of the publish job. A mistyped tag then costs a minute instead of
   publishing a large artifact under the wrong version — and the release that would have
   been created never exists.
3. **A bump command.** Moving `## [Unreleased]` to a dated heading, updating the build
   metadata, **rewriting the prose claims**, and leaving an empty `## [Unreleased]` behind
   is mechanical and easy to do half-way, so do it in code:
   - refuse when `## [Unreleased]` has no entries (a heading is not a release);
   - refuse when build metadata and the newest release disagree (bumping would pick one
     of two numbers arbitrarily);
   - refuse a computed version that does not increase;
   - support `--dry-run`;
   - **update every prose claim in the same command, and print which files it changed.**
     A bump that writes two of the three copies leaves the third to be caught by the
     check on the next push — which means the release is already committed and the fix is
     a second commit. Prose that quotes the release is part of the release, so the one
     command that changes the version changes all of it.
   - **print the `git tag` command rather than running it** — tagging is publishing, and
     publishing is a decision.
   - **take the repository root as an argument (`--repo <path>`), not only from the CWD**,
     so the bump can be driven against a temporary tree, and assert in that test that the
     **result passes the check**. The bump is the only thing that writes both numbers, so
     it is the one place a half-finished edit can ship: a moved heading with an unchanged
     version, or a version with no release section.

Make the bump command maintainer-only if the project has an audience split: it edits the
repository, so it does not belong in the shipped tree.

## Step 5 — the entry is written in the same commit as the change

Every commit that touches a public surface adds its line under `## [Unreleased]` in the
matching Keep a Changelog category (`Added` / `Changed` / `Fixed` / `Removed`). A release
is then a bump, not an editing session. Reconstructing a release's changelog afterwards
produces a summary of what someone remembered, not of what shipped.

## Step 6 — shipping is not tagging

A tag is not a release until the published artifact is built **from that tag**. Verify the
chain and say which link you checked:

- the tag's own tree carries the version (`git show <tag>:pyproject.toml`);
- the publish job ran on that tag and succeeded;
- the release asset exists and its size is plausible against a local build;
- the documented download URL answers — anonymously, if the artifact is meant to be
  public;
- **a consumer can actually consume it.** Every test in the repository builds from a
  local path, so the published artifact is the one thing nothing exercises — and it is
  the only thing a stranger ever gets. Build from a throwaway project whose only input is
  the published URL (`github:owner/repo`, the release tarball, the registry entry), run
  the binary, and import the module if one ships. Recipe: the `nix-declarative-config`
  skill, `consumer-testing-a-flake.md`.
- **A container asset can be verified structurally with no daemon.** The gap that hides
  here is a test of the *derivation* standing in for a test of the *attached file*: a VM
  can load and exercise the image build while the asset a downloader receives is built
  from a different commit, or is missing a layer, and nothing looks. Download the real
  asset, unpack it, and check what `docker load` checks first — one `manifest.json` entry,
  its `RepoTags` naming the image the docs tell people to run, the `Config` file present,
  and every path in `Layers` existing. Read the config for the entrypoint, `Cmd`, `User`
  and `WorkingDir` the docs claim. That is structure, not execution: say which of the two
  you did, and never present a structural pass as "the image works".

**The failure this catches: a release that predates the work.** A repo can be fully green,
fully tagged, with CI passing — and the only downloadable artifact built from a commit
dozens of changes old, carrying bugs the source no longer has. When a milestone's
acceptance is "a fresh machine installs this", check the artifact's provenance, not the
tree's.

## Pitfalls

- **`01.2.3` is not semver.** Leading zeros are forbidden; `^(0|[1-9]\d*)\.` per part, or
  a lenient `\d+` silently normalises a malformed version into a valid-looking one.
- **Do not tag before CI is green on every platform.** A tag pushed over a red matrix
  publishes an artifact that fails its own suite on two of three OSes. Wait for the run.
- **If you must move a tag, move it only when no shipped content changed.** Re-pointing a
  tag over a test-only fix is defensible and keeps one version; re-pointing it over
  product code is a silent change to a released version. Say which it was.
- **`git push` the branch before the tag.** A tag on an unpushed commit publishes from a
  ref nobody can see, and the release's "source" link 404s.
- **A tag-triggered publish job must be idempotent on the asset name.** A fixed asset
  filename keeps `releases/latest/download/<name>` stable across versions, and re-running
  the job has to clobber rather than duplicate.
- **The check's own path resolution is a bug waiting to happen.** If the check runs from
  an installed launcher, `__file__` is not the working tree — see
  `nix-declarative-config` for the store-copy trap and the CWD-then-upwards fix.
- **Comparing paths with `==` is a string comparison.** Any assertion that a resolved
  directory is "the same" must use `os.path.samefile`; macOS `/var` → `/private/var` and
  Windows 8.3 short paths make two names for one directory unequal. See
  `cross-platform-test-portability`.
- **A release with an empty `## [Unreleased]` is a re-tag, not a release.** If there is
  nothing to record, there is nothing to version.
- **`### <Category>` headings repeat once per released version, so a scripted changelog
  edit cannot address "the Unreleased one" by string.** A replace either refuses (the
  anchor occurs in every release) or lands in an already-shipped section and rewrites
  history nobody can review. Locate `## [Unreleased]` first, then the first
  `### Added|Changed|Fixed` after it, and insert by index. Same trap in reverse when
  reading: parse headings in file order and take the first, never the last.
- **When the bump command refuses, the release is over — do not commit and tag anyway.**
  A bump that exits non-zero because `## [Unreleased]` is empty is not an obstacle to
  route around; it is the one guard that knows the release has no content. Chaining
  `bump && commit && tag` in one shell line hides the refusal behind the later commands'
  success and ships a tag whose build metadata still carries the **old** version. The
  tag-vs-metadata check in CI then fails, which is the system working — but the failed
  publish run and the forced tag move are self-inflicted. Run the bump, read its exit
  status, and only then commit; if it refused, the missing entry is the work.
- **A consumer check run seconds after a push can be testing the previous commit.**
  `nix flake` caches the branch-to-commit resolution, so `github:owner/repo` may resolve
  to the rev that was current when the cache was written — and a new output or template
  then reads as "missing", which looks like a broken release rather than a stale ref.
  Pin the rev you mean (`github:owner/repo/<sha>`) for the verification run, or re-run
  after the ref cache turns over, and say which you did.
- **Never construct a release asset's URL from a guess — read the asset list.** Asset
  names are chosen by the publish workflow and are not derivable from the tag or the
  project name. A fabricated `<project>-image.tar.gz` 404s and reads as "the release is
  broken" when the asset is simply called something else. Ask for the names that exist
  (`curl -sL .../releases/tags/<tag> | jq -r '.assets[] | "\(.name) \(.size)"'`) and
  check the download with the name that came back.
- **A release that adds or removes a tool re-measures every figure derived from the
  toolchain, in the same commit.** Closure size, path count, substitutable fraction,
  image tarball size, layer content and every "N analyzers" string in prose are all
  functions of the same list, and each lives in a different document. Nothing warns you:
  the docs stay confidently wrong for several releases. Enumerate the derived figures
  before the change and re-measure each after it — the mechanics are in the
  `nix-declarative-config` skill, `flake-cost-and-structure.md`.

## Writing it down

Put the policy in `docs/VERSIONING.md`, link it from the README's docs table, and name it
in the CHANGELOG entry that introduces it. The document carries the definitions and the
enforcement list; the CLI carries the mechanism; the gate carries the consequence.
