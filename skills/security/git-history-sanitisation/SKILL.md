---
name: git-history-sanitisation
description: "Use when publishing a branch, or sanitising history."
version: 1.2.4
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
category: security
metadata:
  hermes:
    tags: [git, secrets, history-rewrite, publishing, audit]
    related_skills: [oss-forensics, github, web-app-security]
---

# Sanitising a git history before publishing

Two jobs share one question -- what is about to become public? The first is
**publishing a branch at all**: scope the commit, scan the range, verify it landed.
The second is **sanitising a history** that already carries what must not ship.

A secret committed and later deleted is still in the history and still readable. Audit
every blob reachable from any ref, not the working tree, and rewrite before the
repository is flipped to public.

Back up first — `git bundle create <file>.bundle --all` — and tell the user that bundle
is the only remaining copy of the sensitive data and must be deleted once they are
satisfied. Put it somewhere **durable**: a scratch or cache directory that prunes
itself will silently take the only rollback with it while the user believes they have
one. Prove it is a backup before relying on it — `git ls-remote <bundle>` lists the refs
it actually carries, and a bundle whose HEAD is a revision the rewrite already replaced
protects nothing.

Then do the whole rewrite on a **clone** before touching the real repo: the dry run is
what catches a malformed replacements file, and it costs one command.

## Procedure

1. **Map the history.** `git rev-list --all --count`, `git branch -a`, `git tag -l`,
   `git log --all --format='%an <%ae>' | sort -u`, `git remote -v`. A second remote (a
   bundle, a handoff path) is easy to forget and can carry refs the primary does not —
   but check what those refs *point at* before calling it a backup; a bundle cut before
   the rewrite holds pre-rewrite SHAs. Remove a stale remote and its refs together:
   `git remote remove <name>` leaves `refs/remotes/<name>/*` behind, so follow with
   `git update-ref -d` or delete `.git/refs/remotes/<name>` outright. A remote URL in
   `.git/config` is not committed history, but it can still carry a machine path and a
   username worth clearing. Then list the **remote's** full ref set —
   `git ls-remote origin` — because a stale *tag* keeps the old history reachable after
   the branch is force-pushed, and the tag is the ref that gets forgotten: the branch is
   the one in mind. Delete it explicitly (`git push origin :refs/tags/<name>`) rather
   than assuming the force-push covered it.
2. **Establish whether it is already public** before promising anything:
   `curl -s -o /dev/null -w '%{http_code}' https://api.github.com/repos/<owner>/<repo>`
   — 404 unauthenticated means private or absent. A rewrite is fully effective only
   while it is private; commits that have already been public are NOT recalled by a
   force-push.

   **An empty remote is the cheapest moment there will ever be — sanitise before the
   first push.** If the repository exists but advertises no refs (`git ls-remote origin`
   exits 0 with empty output) and the local tree has no upstream, then nothing has been
   published, so a rewrite costs a force-push of nothing, needs no recreate, and leaves
   no objects for the host to purge. Audit and rewrite *first*, then push once. The
   order is what makes it free: push, notice, rewrite, and you are in the private→public
   recovery path below — object purge, repository recreate, `-old` deletion — for a
   problem that one pre-push rewrite would have avoided entirely. Establish which
   situation you are in before the first push, not after the user says "it's live".

   **`filter-repo` needs `--force` in exactly this state**, because it expects a clone:
   with no upstream it refuses with `(refs/heads/main exists, but refs/remotes/origin/main
   not found) … use --force`. That is the one flag here that is safe to reach for, and
   note what it also enables: step 8's `reset --hard` will discard uncommitted changes to
   tracked files, so commit or bundle first. Take the backup before this step regardless —
   `--force` plus a prune is not reversible.
3. **Audit every blob.** Materialise each unique blob once and grep that, rather than
   running the pattern per commit:
   ```bash
   git rev-list --all --objects | awk 'NF==2{print $1}' | sort -u > objs
   git cat-file --batch-check < objs | awk '$2=="blob"{print $1}' | sort -u > blobs
   mkdir -p b && while read -r x; do git cat-file blob "$x" > "b/$x"; done < blobs
   grep -rlaE '<pattern>' b/          # blob id -> look up its path separately
   ```
   Scan the shapes that leak: home directories (both `/home/<name>` and
   `C:\Users\<name>`, in every separator and case variant), the machine hostname, a
   private hostname or endpoint, provider names, pinned model names, private repo or
   directory names, key-shaped strings, and any second account name. Scan **commit
   messages** too — a path in a message is as public as one in a file. A secret scanner
   over full history (`gitleaks detect`) is a good second opinion, never the only one:
   it matches generic patterns, not your identifiers.

   **Password hashes are their own scan class, and no secret scanner flags them.** A
   crypt(3) digest — `$6$…` (sha512-crypt), `$5$…`, `$2b$…` / `$2y$…` (bcrypt, which is
   what `htpasswd -B` writes), `$y$…` (yescrypt), `$apr1$…` (htpasswd MD5), `$argon2…` —
   is not credential-shaped, so gitleaks reports `no leaks found` over a history that
   carries one. It is still a publishing blocker: the hash is crackable offline,
   permanently, and a weak or reused password makes that minutes of work. Scan the
   **blobs materialised in step 3**, not `git log -p` output, and print **paths only**:

   ```bash
   # -l prints the blob id, never the digest: the match IS the secret.
   grep -rlaE '\$[0-9a-z]{1,10}\$[A-Za-z0-9./]|hashedPassword|initialHashedPassword' b/
   git grep -lE '\$[0-9a-z]{1,10}\$[A-Za-z0-9./]' -- .   # the current tree
   ```

   `$[0-9a-z]{1,10}\$` is the general crypt-format shape. Measured against every form
   that matters — `$1$`, `$2b$`, `$2y$`, `$5$`, `$6$`, `$y$`, `$apr1$`, `$argon2id$` — it
   matches all eight. A hand-written `[56y]` character class silently misses `$2b$`
   (bcrypt, `htpasswd -B`) and `$argon2id$`, which are the two a modern password store is
   most likely to hold. **Treat a hit as a candidate, not a finding:** the pattern also
   matches variable-adjacent text such as `echo $a$b` or `awk '{print $1$2}'`, so triage
   each blob before rewriting history over it. Two reasons the blob scan is the only one
   that counts here:

   - **`git log -p` cannot see a binary blob.** For any file git treats as binary or
     `-diff` — an `htpasswd` file with a NUL byte, a `.db` — `-p` prints `Binary files
     differ` instead of content, so the grep exits 1 and a clean result means "not
     scanned", not "clean".
   - **`grep -n` prints the whole line.** A matched `hashedPassword = "$6$…$<full hash>"`
     lands in the transcript, and step 4 of this same procedure forbids exactly that.
     Count or list; never echo.

   A literal hash that is gone from the tree but present in history is exactly the
   shape that survives a "the working tree is clean" check, so scan history even when
   `grep` over the checkout finds nothing.
4. **Verify a suspected credential by hash and length, never by printing it.** Identify
   the candidate and the live value the same way — length, sha256 prefix, first few
   characters only:
   ```bash
   printf %s "$VALUE" | sha256sum | cut -c1-12
   ```
   A report that quotes the secret is itself a leak. A test fixture that mimics the real
   provider's format (same length and prefix, different hash) is **not** a credential
   leak: say so with that evidence rather than leaving the scanner's finding
   unexplained. It is still a **publishing blocker**, and the two claims are different.
   Host push protection matches the shape, not the value -- measured, gitleaks flags any
   `sk_live_`-shaped string including an obviously fake one, while a provider's own
   documented example key is not flagged. So rewrite the fixture to build its value at
   runtime (`"sk_" + "live_" + ...`) and keep the shape the probe must match: the
   literal disappears from history while the test still proves what it claims. Rewrite
   it in the commit that introduced it, before the push -- a fixture that forces an
   exemption in the push path teaches everyone to ignore that path.
5. **Dry-run on a clone.** `git clone <repo> /tmp/dry`, run the full rewrite there, and
   check the *result* before trusting the input files: comments intact, no unexpected
   replacement token anywhere in the tree, commit count unchanged, identities collapsed
   to one.
6. **Rewrite the real repo**, then re-add the remote — filter-repo drops the
   remote-tracking refs and the `origin` tracking branch.
7. **Re-audit the rewritten history** with the same blob scan. Every pattern must be
   zero, and every residual the scanner still reports must be explainable.
8. **Fix what the rewrite breaks**, then run the project's own gates. Be exact about
   what filter-repo actually does, because the wrong mechanism sends you hunting a
   deletion that never happened:

   - **It does not touch ignored or untracked files.** Its `cleanup()` runs only
     `git reset --hard`, `git reflog expire --expire=now --all` and
     `git gc --prune=now` — there is no `git clean` in it. With untracked changes
     present it refuses to start (`you have untracked changes`) unless you pass
     `--force`; it never deletes them.
   - **What does disappear is a *tracked* file the path filter excluded** — plus, under
     `--force`, uncommitted changes to tracked files, which `reset --hard` discards.
     That is the loss to check for, and `git status --ignored` cannot see it: the file
     is not ignored, it is gone from the commit.
   - **The irreversible step is the prune.** `reflog expire --expire=now` plus
     `gc --prune=now` drop the reflog and every object nothing references any more, so
     `git fsck --lost-found` will not recover them. Two corrections to the usual telling:
     a **stash** is not collateral damage — filter-repo refuses to start when one exists
     (`has stashed changes`) and, if one appears mid-run, rewrites it to the new commits
     (`_write_stash`, which prints `Rewrote the stash`) before the `gc`. What the prune
     really costs you is the reflog and any commit only the reflog still pointed at, so
     take a `git bundle create ../pre-rewrite.bundle --all` or a full clone **before** the
     rewrite; that backup is the only undo.

   The common failure is a push that dies on a hook rather than on git, because a
   tracked config the hook reads was excluded by the path filter:

   ```text
   No .pre-commit-config.yaml file was found
   error: failed to push some refs to '…'
   ```

   Confirm the mechanism **against the pre-rewrite backup**, not against the rewritten repo:
   after a path filter drops a file, `git log --oneline -- <path>` and
   `git log --oneline --all -- <path>` are both empty in the new history — identical to a
   file that was never tracked, so that pair cannot tell the two apart (measured). Ask the
   backup instead, where the answer is still there:

   ```bash
   git clone -q ../pre-rewrite.bundle /tmp/pre && \
     git -C /tmp/pre log --oneline --all -- .pre-commit-config.yaml
   ```

   If the backup has commits for that path and the rewritten repo has none, the filter
   dropped it: restore it (`--path .pre-commit-config.yaml` or a fresh commit) and push
   again, so the gate actually runs. **Do not reach for the bypass**
   (`PRE_COMMIT_ALLOW_NO_CONFIG=1`, `--no-verify`, deleting the hook) to get past it: a
   rewrite is exactly when the gate is most worth having.
9. **Tag** the release, and state in the tag message that the history was sanitised.
   Check the tree first: a rewrite does not stop other writers, and a background curator
   can patch a skill or create one *after* you finish — landing in the profile-local
   skills dir when `create_dir` is unset, which leaves the repo dirty and the new skill
   unpromoted. `git status` must be clean, with every author-created skill in the repo,
   before tagging. Keep the tag message in a file until the tag exists: deleting a tag
   and recreating it is destructive-then-creative, so a missing message file leaves you
   with **no** tag. Confirm with `git describe --tags --exact-match` rather than assuming
   the command worked.

## `--replace-text` syntax and its three traps

- **A line containing only `#` is not a comment.** filter-repo parses it as a rule that
  replaces the literal `#` with `***REMOVED***`, corrupting every comment in every file
  in history. Never leave a lone `#` as a separator — including inside a comment you
  wrote to warn about this.
- **`glob:` prefixes the TEXT expression, not a path.** There is no path-scoped
  replacement: `glob:<dir>/**:literal:x==>y` matches nothing and silently leaves the
  value in place. A rule that looks scoped and does nothing is the worst failure mode
  here, because the re-audit is the only thing that catches it.
- **Order matters; the first match wins.** Put specific forms before general ones — the
  full path before the bare name, the full provider host before the provider word.
- `literal:` for exact strings, `regex:` for word boundaries. Use a word-boundary regex
  for a bare name, and check the replacement against same-named public projects before
  choosing it: a generic word collides with ordinary English and with unrelated
  directories.
- `--replace-message <file>` takes the same syntax but **no glob lines** (a message has
  no path).
- `--mailmap <file>` rewrites author, committer and tagger. An **email-only** entry
  (`New Name <new@x> <old@y>`) rewrites both name and address for every commit carrying
  that address, which collapses several name spellings in one rule.

## When the history is not wanted at all: publish one commit

Sanitising preserves the shape of the history, which means it preserves every awkward
consequence of it: a pinned hash that no longer matches in older commits, a commit
message naming a path that no longer exists, an author identity from a machine that is
gone. If the user says they do not need the history — only a short, surface-level
record — the simpler and strictly safer answer is **one commit containing the current
tree**:

```bash
git checkout --orphan __release
git add -A
git commit -F release-notes.txt      # the changelog-esque summary
git branch -D <old-branch> && git branch -m <old-branch>
git tag -a v1.0.0 -F tag-notes.txt
git update-ref -d refs/remotes/origin/<branch>   # see below -- this one is easy to miss
git reflog expire --expire=now --all && git gc --prune=now
```

**`git commit --amend` does not fold a later commit into the release — it amends the
tip.** Once a second commit exists, `git add -A && git commit --amend` rewrites *that*
commit and leaves the release as its parent, so the file count and the tree are right
while the history is not: the count stays at 2 and `git log --oneline` shows the
release message twice over. The orphan checkout above is the only shape that yields
exactly one commit, so re-run it after every later edit rather than trying to amend
your way to one. Confirm with `git rev-list --all --count` — and remember it counts
commits across *all* refs, so a tag left pointing at the old history keeps the old
total standing.

Three things that keep the prune from actually pruning:

- **The tag.** Retagging must happen *before* the gc, and deleting the old tag first:
  while a tag points at the old history, every old object is still reachable and
  `git rev-list --all --count` keeps reporting the old total.
- **`refs/remotes/origin/<branch>`.** A remote-tracking ref still pointing at the
  pre-squash commit keeps that commit alive, and it survives `git gc`. Delete the ref,
  not just the local branch. This is the one that looks finished while it is not.
- **The reflog.** `git reflog expire --expire=now --all` before the gc, or the previous
  HEAD keeps everything.

Check the result rather than assuming: `git rev-list --all --count` must be 1, and
`git cat-file -e <old-HEAD>` must fail. Then verify the tree is untouched — file count
and the project's own tests — because the squash rewrites history, not content.

The payoff beyond the smaller history: this eliminates the pinned-hash problem above
entirely, since there is no older commit left to hold a stale pin.

**It does not remove what the host already has.** The squash changes what the *refs*
point at; it does not touch objects the host already stored from a previous push. Run
the fetch-by-SHA probe again afterwards — measured, the old commits stayed fetchable
after both a force-push and a squash, which is why recreating the repository remains
the only step that makes a private→public flip safe.

## What a rewrite cannot fix

A hash pinned in one file to **another file's content** (a fixture manifest, a lock, a
pinned expectation) cannot be regenerated inside the rewrite — a text substitution
cannot compute another file's hash. Two consequences, both of which must be stated
rather than left to be discovered:

- Sanitising a file whose hash is pinned breaks the pin. Regenerate it afterwards with
  the project's own tool, and show that only hashes moved, not scores.
- Commits older than the re-pin keep the now-wrong pin, so a check run on a *historical*
  checkout reports a mismatch. The tip is consistent; that is what ships.

## After the rewrite

- Run the project's full gates, not just the scanner. Expect a guard test to fail
  because the rewrite changed its needle list or a fixture: fix the guard so it asserts
  a **shape** (a path prefix, a key prefix, a provider name) rather than anyone's
  username — a username needle is obsolete after sanitising and far too generic to
  assert on, since it matches ordinary prose.
- Re-prove a guard you weakened: break it deliberately, watch it report, restore it.
- **The sanitisation inputs are themselves sensitive.** The replacements file lists every
  identifier being removed, and an audit report quotes the paths it found. Disposing of
  them is part of the job: left in a scratch or cache directory they re-introduce exactly
  what the rewrite removed, in a place nobody thinks to scan.
- `git status` must be clean with no untracked files before tagging.
- A file that names a path inside the repository is *content*, so the rewrite edits it.
  Afterwards, check that no doc or skill now names a path that does not exist — a
  sanitised placeholder that was never real is worse than a generic description.

## Before a normal push: scope, scan the range, verify it landed

Publishing a branch that has never been pushed needs its own preflight. Do it per
repository -- "the repos" is not one unit, and one of them may have no remote at all.

1. **Map each repo before touching any of them.** Branch, remote, upstream, and the
   unpushed range:
   ```bash
   git rev-parse --abbrev-ref HEAD
   git remote -v                                   # may be EMPTY
   git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null || echo NONE
   git log --oneline '@{u}..HEAD'                  # what would actually leave
   ```
   A repo with no remote cannot be pushed, and "push the changes" then means asking
   rather than inventing a destination. Confirm the push is a fast-forward before it
   happens: `git merge-base --is-ancestor origin/<branch> HEAD`.
2. **Scan the COMMIT RANGE, not the working tree.** `gitleaks --no-git --pipe` and
   `gitleaks dir .` scan the checkout, so they report untracked caches, editor state
   and a reviewer's run artifacts that will never be pushed -- a wall of findings
   about files git does not track. Use history mode over the exact range:
   ```bash
   gitleaks git --log-opts="origin/<branch>..HEAD" --redact -v
   ```
   Before believing any finding, ask whether the file is tracked
   (`git ls-files | grep <path>`) and which commit introduced it
   (`git log --oneline -- <path>`). Untracked means it is not in the push; a commit
   older than the branch point is somebody else's history, already published or
   deliberately parked.
3. **Never push a possible credential to find out whether it is real.** Report the
   path, the rule, the commit and the shape (length, prefix, hash prefix) -- never
   the value. Then ask. An agent that resolves the ambiguity by pushing has made the
   leak irreversible on someone else's behalf.
4. **Scope every commit to your own paths.** In a repo where the user has staged work
   that is not yours -- the normal case when they have been reviewing alongside you --
   `git commit --amend` and `git reset --soft` both carry the WHOLE index into the
   commit, so your one-file change silently publishes their twenty-seven. Both are
   safe to use only with an explicit path list:
   ```bash
   git commit --amend --no-edit --only -- path/to/my-file
   git commit -F msg.txt --only -- path/to/my-file
   ```
   `reset --soft` has no path argument at all: after it, re-stage only your own paths
   (`git add <yours>`) and leave the rest in the working tree, or use `reset --mixed`
   and rebuild the index deliberately. Verify before pushing --
   `git show --name-only --format='' HEAD` must list exactly the files you intended,
   and `git diff --cached --name-only | wc -l` must still equal what the user had
   staged.
5. **Verify the push landed, per repo.** A push that reported success is not a ref
   that matches:
   ```bash
   git fetch -q origin && git rev-list --left-right --count origin/<branch>...HEAD
   ```
   Both numbers must be `0`. Compare the SHAs too, and say in the report which
   repository received what -- a range like `c2bc808..758363e` is the receipt.

   **Then prove the published repository works by cloning it anonymously.** A ref that
   matches says the objects arrived; it says nothing about whether a stranger can build
   what they now have. Clone over **HTTPS with no credentials** into a fresh directory,
   confirm the file and commit counts match the local tree, re-run the sanitisation scan
   on that clone, and run the project's own gates there:

   ```bash
   set -euo pipefail
   D=$(mktemp -d)                      # a fresh path each run: a fixed one reuses a stale clone
   git clone -q https://github.com/<owner>/<repo>.git "$D/published"   # own line: a failed clone must abort
   cd "$D/published"
   git ls-files | wc -l; git rev-list --count HEAD      # must equal the local tree
   # <the project's gate command>, run here
   ```

   **Keep the clone on its own line.** Chained as `git clone … && cd … && <gate>`, a failed
   clone is the non-final operand of an `&&` list, so `set -e` does not abort — the shell
   falls through with the cwd still in the caller's tree, and the counts and the gate then
   describe the local checkout instead of the published one, which is the stale-proof
   failure this file warns about elsewhere.

   The clone is the only check that exercises what was actually published — an
   authenticated remote can serve from a different cache, and a working tree can differ
   from its own committed blobs. Report the clone's result, not the local gate's, when
   the question is whether the *published* thing is sound.

Report the commit range per repo, and what was deliberately left unpushed. A branch
kept local on purpose is a result, not an omission.

## Publishing: a force-push is not enough

Every commit SHA changes, so the push must be forced. But a force-push only makes the
old commits *unreachable* — it does not remove them. Hosts keep the objects and serve
them **by SHA**, so anyone holding an old SHA can still fetch the pre-rewrite history.

Do not assume this, and do not take it on faith from this page: test it. After pushing,
fetch an old commit from the remote and check the exit code **unpiped** — `$?` read
through a pipe reports the last stage's status, not git's, so a piped check reports
success for a fetch that failed:

```bash
cd "$(mktemp -d)" && git clone -q <remote> . && git fetch origin <FULL-40-CHAR-SHA>; echo $?
```

**Pass the full 40-character SHA.** An abbreviated SHA — the ten characters
`git log --oneline` prints, which is what you will have to hand — fails to fetch whether
or not the host still holds the object. A probe list built from abbreviated SHAs
therefore reports `gone` for *everything*, including objects the host is still serving,
and returns a false all-clear on the exact question the probe exists to answer. Resolve
each to its full ID first (from the pre-rewrite bundle, or `git rev-parse <abbrev>` in a
clone that still has it), and make the probe report one positive before trusting any
negative. `scripts/verify-recreate.sh` refuses an abbreviated SHA for this reason.

The same rule bites the push guard. `git push --force-with-lease=<branch>:<sha>` takes an
exact object, so an abbreviated `<sha>` fails with `cannot parse expected object name`
and the push does **not** happen — while a tag push in the same command still succeeds.
That is one mechanism behind the branch-and-tag divergence below: read the output of each
push rather than assuming a command that ran two of them succeeded at both. Get the SHA
for the lease from `git ls-remote origin refs/heads/<branch> | cut -f1`, which prints it
in full.

**"Could not check" is not "absent".** A probe that treats any non-zero exit as "the
object is gone" reports a false all-clear on an auth failure, a network error or a
missing repository exactly as readily as on a genuinely pruned object. An anonymous
HTTPS `ls-remote` against a **private** repository fails with `could not read
Username`, which is not "not found" — so test existence through the API
(`curl -s https://api.github.com/repos/<owner>/<name>`, where only
`"message": "Not Found"` means absent) or through an authenticated remote, and treat
every other outcome as unknown. An unknown is reported as unknown; never fold it into
the negative that makes the gate pass.

exit 0 means the host still serves it, and the fetched object can be inspected to
confirm it carries what the rewrite removed. Measured, not theoretical: on GitHub the
pre-rewrite commits stayed fetchable by SHA after the force-push, and their trees still
held every identifier the rewrite had removed.

That result gates the whole operation. **Do not flip a private repository to public
while the old objects are still served.** Unreachable-but-fetchable is tolerable while
only collaborators can reach the repo; it is a leak the moment the repo is public,
because the SHAs are not secret — they sit in reflogs, shell history, pasted output and
any pre-rewrite bundle. Remove them first: delete and recreate the repository with the
rewritten history, or have the host purge the unreachable objects (GitHub Support
will). Then re-run the probe and confirm it fails before changing visibility.

**The verdict is per repository, not global.** A recreate is legitimately half-done
while one repository has been rebuilt and another has not: the fresh repository serves
none of the old objects and can be published, while the untouched one still serves all
of them through its `-old` twin. Report the probe's result for each repository
separately — one combined "NOT SAFE" hides the repository that is finished and blocks a
release that is safe. What decides the exposure is where the objects live and who can
reach them: a `-old` repository still **private** keeps them reachable only by
collaborators, so publishing the fresh, clean repository exposes nothing, whereas
making the `-old` repository public does. Check visibility as well as existence, and
say which of the two you are reporting.

**Recreating means deleting the old repository, not renaming it aside.** The usual shape
is: rename `X` → `X-old`, create an empty `X`, push. That alone removes nothing —
`X-old` still serves every pre-rewrite object, and it is now the repository nobody
remembers to look at. So the recreate is three steps and only the last one is the fix:
rename aside, create and push fresh, **then delete the `-old` repository**. Until that
delete happens the probe must still report the objects as served, so a probe that comes
back clean before the delete is a probe that is not testing anything. Check for the
leftovers explicitly — any `<name>-old` or `<name>-backup` that still resolves is a leak
under a new name — and gate the visibility flip on both checks passing:
`scripts/verify-recreate.sh`.

**The old name keeps working, and that is the trap.** GitHub leaves a redirect from the
old name to the new one, so after `X` → `X-old` the plain name `X` still resolves — to
`X-old`. A `git push` to `X` therefore **succeeds**, landing the objects in `X-old`,
and every ref check then agrees, because it agrees with the wrong repository. Do not
push until the new `X` exists, and when you do, confirm which repository received it.
The tell is that both names advertise **identical refs**:

```bash
[ "$(git ls-remote <owner>/X.git | sort)" = "$(git ls-remote <owner>/X-old.git | sort)" ] \
  && echo 'X is still a redirect to X-old — a push to X went there'
```

A freshly created empty repository answers `ls-remote` with **exit 0 and no refs**, so
"no refs" is not "does not exist" — and it is also the one push that cannot
fast-forward, so it reports `[new branch]`, which is what you want to see. A push that
reports "Everything up-to-date" against a supposedly new repository is the redirect
signature.

The recreate needs repository create, rename and delete, which a push-only credential
cannot do — a successful `git push` over SSH says nothing about whether you can create a
repository. Establish which of those you actually have before promising to finish the
job; if you cannot, hand over the web-UI steps plus the push commands and state plainly
that the old objects are still served until the delete happens.

**Verify the push landed, and that the refs agree.** A force-push reports success per
ref, and the branch and the tag are separate pushes that can diverge — the tag is the
one that goes stale. Compare the local object against the remote one for both, and
dereference the tag: `refs/tags/<name>` on an annotated tag is the *tag object*, not
the commit.

```bash
l=$(git rev-parse HEAD); rh=$(git ls-remote origin refs/heads/<branch> | cut -f1)
lt=$(git rev-parse v1.0.0^{commit}); rt=$(git ls-remote origin 'refs/tags/v1.0.0^{}' | cut -f1)
[ "$l" = "$rh" ] && [ "$lt" = "$rt" ]    # both must hold
```

A bare `git ls-remote origin` then shows what the host actually advertises: one
branch, one tag, no leftover ref from an earlier push. Do this before telling the
user the release is up — a push that reported success is not a ref that matches.

Report the probe's result as the reason to wait. A user who asked for the repositories
to be made public is better served by "not yet, here is why, here is the command that
proves it" than by a visibility change that publishes what the rewrite removed.

Do not claim the repositories are published. Pushing, changing visibility, and deleting
a remote are the user's actions: hand over the exact commands and stop.
