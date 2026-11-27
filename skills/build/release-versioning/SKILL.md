---
name: release-versioning
description: "Use when cutting a release. Semver policy and gates."
version: 1.2.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
category: software-development
metadata:
  hermes:
    tags: [semver, release, changelog, versioning, tagging, packaging]
    related_skills: [github, verify-and-stop, deterministic-quality-gates, nix-declarative-config]
writes: [none]
side_effects: [none]
scope_answers: ["what version a release should carry"]
scope_triggers: [cut a release, semver decision]
scope_out: [the changelog's claims (pr-description), the gate before it (two-axis-review)]
---

# Versioning and releasing

**Runtime.** Podman; `docker` is the accepted substitute — the policy and the differences that bite are in `docs/runtime.md`.

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
(`apps.<tool>` beside `packages.<tool>`). Query the surface (`nix flake show
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
| two headings of one category (two `### Added`) under one release | section-keyed tooling merges or drops a list, and a scripted insert lands in the first |
| a released heading has no valid date | when, for every release |
| the Unreleased heading (`## Unreleased`, or bracketed only when a compare link exists) is not first | where the next entry goes |
| a document claims a release other than the build metadata | the prose is a third copy, and the only one nothing was checking |

**The zero-release state is legal and must pass.** Before the first release there is no
dated heading, so there is nothing to compare the build metadata against; the check must
still pass when `## [Unreleased]` is first and every prose claim equals the metadata, and
the bump cannot compute a version from nothing — require it explicitly (`--version
0.1.0`) and keep the same rewrite path, so the first release is not the one release that
skips the gate.

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

**A shipped artifact's file name is a version copy as well.** `tool-1.2.3-py3-none-any.whl`
in an install line, an image tag in a `podman run`, a download URL — each is the version
written into prose, and a bump that renames the artifact but not the line ships a command
that 404s. Add every artifact-name shape the docs quote to the same extractor and the same
rewrite path; the `Current release` regex alone will not see them.

**A build file is a version copy too, and no prose check reads it.** A `flake.nix` that
hardcodes `version = "1.2.3"`, an image `tag`, and a check asserting `__version__ ==
"1.2.3"` is three more copies of the number. Derive them from the one source — in Nix,
`version = (builtins.fromTOML (builtins.readFile ./pyproject.toml)).project.version;` — and
feed the package, the image tag and the check's expected value from that binding. Have
`__version__` read the installed metadata (`importlib.metadata.version("pkg")`) with a
source-checkout fallback, so the wheel cannot disagree with the tree that built it. A
hardcoded image tag is the silent one: the package is 2.0.0 and the image still says 0.1.0,
and every check still passes because each copy is internally consistent.

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
   - **replace only the captured version group, never the rest of the match.** A pattern
     that matches a wheel filename (`tool-1.2.3-py3-none-any.whl`) and a replacement built
     as `match.group(0)[:match.start(1)] + version` drops `-py3-none-any.whl`, and the
     README then advertises a file that does not exist. Splice `match.span(1)` and keep the
     prefix and suffix; pin it with a bump test asserting the suffix survives and the
     result passes the check.
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
  asset, unpack it, and check what `podman load` checks first — one `manifest.json` entry,
  its `RepoTags` naming the image the docs tell people to run, the `Config` file present,
  and every path in `Layers` existing. Read the config for the entrypoint, `Cmd`, `User`
  and `WorkingDir` the docs claim. That is structure, not execution: say which of the two
  you did, and never present a structural pass as "the image works".

The concrete commands for each artifact — wheel, image, tag and CI entry — are in
`references/release-artifact-verification.md`. Label every check `executed` or
`structural` in the release note: a structural check inspects bytes, and only an executed
one runs the artifact.

**The failure this catches: a release that predates the work.** A repo can be fully green,
fully tagged, with CI passing — and the only downloadable artifact built from a commit
dozens of changes old, carrying bugs the source no longer has. When a milestone's
acceptance is "a fresh machine installs this", check the artifact's provenance, not the
tree's.

## When the ask is a backlog, not a version

"Release everything on the main branch" usually means *land the uncommitted work*, not *cut a
number*. Settle which before touching a version: a repository with no changelog, no build
metadata and no version check has no release surface, and building one is a second project. Say
which reading you took. The deliverable is commits on the branch; the push is the one step still
worth a question, because it publishes and the remote belongs to its owner. Ask once, and treat a
yes as scoped to that push rather than as a new standing policy.

- **Split by intent, not by file count.** `git reset` first — it unstages everything and leaves the
  working tree byte-identical — then stage one intent at a time, naming the paths. A document and
  the reference file it cites ship in the same commit: a commit that cites a file it does not
  contain fails the gate's own dead-reference rule, so **every intermediate commit must be
  self-consistent, not only the head**.
- **Prove every commit, not just the head.** For each new commit, `git worktree add --detach
  /tmp/v-<sha> <sha>`, run the repository's cheapest gate inside it, `git worktree remove --force`.
  A series whose head is green can still carry a commit that never built, and a bisect will blame
  the wrong one. A stdlib validator or a two-second suite makes this a per-commit habit rather
  than a special occasion.
- **Reconcile the count before pushing.** `git status --porcelain` empty, and
  `git diff --shortstat <base>..HEAD` equal to the change you started from. A file left unstaged
  and a file staged twice both read as success from the log alone.
- **Read the run you caused, not the latest one.** `gh run list --branch <b> --limit 1 --json
  databaseId,status,conclusion,headSha` and assert `headSha` is the commit you pushed before
  reading `conclusion`; a run listed seconds after a push can still be the previous one.

## Pitfalls

- **The branch is yours; the main branch and the remote are not.** Work on a branch per session
  or per feature and commit there. Never commit to the main branch and never push: a push
  publishes, exactly as a tag does, and publishing belongs to whoever owns the remote. An
  instruction to land the work on the deployed branch is the exception, and it is still a question
  about the push: commit there, then ask once — *When the ask is a backlog, not a version* is the
  procedure. When the staging area or `HEAD` changes under you, check `git reflog` and for a
  scheduling daemon before concluding your work was lost or reverted — an orchestration job can
  commit and push on a timer while you edit, and its commit messages will not describe your
  changes.

- **`01.2.3` is not semver.** Leading zeros are forbidden; `^(0|[1-9]\d*)\.` per part, or
  a lenient `\d+` silently normalises a malformed version into a valid-looking one.
- **Do not tag before CI is green on every platform.** A tag pushed over a red matrix
  publishes an artifact that fails its own suite on two of three OSes. Wait for the run.
- **A tag nobody can see is not published; once it is, it does not move.** Before the
  remote has the tag and no release references it, a release commit that lands after
  tagging should carry the tag forward: delete and re-create it at the final commit, and
  say so. After publication, re-pointing it over product code is a silent change to a
  released version; a test-only fix is the one defensible case, and even then say which it
  was. Moving a local tag is not a rewrite of history — leaving it behind means the tag
  does not contain the release's own evidence.
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

- **A tag freezes every sentence about the released behaviour — grep them before tagging.**
  The version check compares version strings, so a doc stating the *old* behaviour passes it
  and ships inside the tag. Measured: a release closed a milestone's open parameter and the
  tag went on while `docs/FRAMEWORK.md` still said a claims-scored run "is reported
  `uncalibrated` rather than compared" — true before the release, false in it. Before the tag,
  grep the docs and README for the shapes a behaviour change invalidates (`does not exist`,
  `not supported`, `rather than`, `cannot`, `not yet`) and fix or delete every hit. If the tag
  is already pushed, land the correction as a follow-up commit and say the tag is one commit
  behind; do not force-move a published ref to spare the reader one `git log`.

## Writing it down

Put the policy in `docs/VERSIONING.md`, link it from the README's docs table, and name it
in the CHANGELOG entry that introduces it. The document carries the definitions and the
enforcement list; the CLI carries the mechanism; the gate carries the consequence.
