---
name: hermes-project-handoff
description: "Move a Hermes project and profiles to another machine."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
category: autonomous-ai-agents
metadata:
  hermes:
    tags: [hermes-agent, handoff, export, bundle, profiles, portability, migration]
    related_skills: [hermes-bot-authoring, project-kickoff-planning]
---

# Hermes Project Handoff

Package a Hermes project so another machine can resume it — repo, bot profiles, session history —
plus a resume guide, then verify the package by **restoring from it**.

## When to Use

- "How do I continue this on another machine?" / "How do I export this work?"
- Moving bots/profiles between hosts, or archiving a project for later.

Not for authoring the bots themselves — that is `hermes-bot-authoring`.

## Procedure

1. **Repo → git bundle** (self-contained, full history):
   ```bash
   ( cd "$REPO" && git bundle create "$OUT/repo.bundle" --all )
   git bundle verify "$OUT/repo.bundle"
   ```
   Restore with `git clone repo.bundle <dir>`.

2. **Profiles → native export** (config + persona + skills; secrets excluded):
   ```bash
   hermes profile export <name> -o "<native-path>/<name>.tar.gz"
   ```
   `-o` needs a **native** path on Windows (`C:/...`), not `/c/...`.

3. **Conversation → sessions export** (optional; a record, not a resume):
   ```bash
   hermes sessions export --session-id <id> --format md "<native-path>/transcript.md"
   hermes sessions export --session-id <id> --format jsonl "<native-path>/transcript.jsonl"
   ```

4. **Manifest + tarball.** `sha256sum` every artifact into `MANIFEST.txt`, then `tar czf` the dir.

5. **Write `HANDOFF.md`**: prerequisites, restore commands, the credentials step, a verification
   checklist, and the next steps for the project.

6. **Verify by restoring**, not by listing — see below.

## Pitfalls

- **Check `.gitignore` before trusting the bundle.** An ignored directory silently excludes
  deliverables (curated run reports, generated docs) from the repo, and a directory listing will not
  reveal it. Diff `git status --ignored` against what you expect to ship. The only reliable check is
  cloning the bundle and listing its files.
- **Rebuild the bundle AFTER the last commit.** A bundle built earlier will not contain later
  commits; a stale artifact passes a directory listing and fails a clone.
- **`hermes profile export` excludes `.env` but INCLUDES `state.db`.** No credentials travel, but
  session history does — the archives carry conversations and are personal data. Confirm with a tar
  listing before shipping, and tell the user which it is.
- **`hermes sessions export`'s OUTPUT is positional, not `-o`.** With `--format md` it writes into a
  *directory* named after the target path; flatten it or the archive ships a nested dir.
- **An export is not a resume.** `hermes sessions import` only ingests *foreign* Claude/Codex
  sessions — a Hermes export cannot be re-imported. To continue a conversation on the new machine,
  copy the profile's `state.db` and run `hermes --resume <id>`. Say this plainly; do not imply the
  transcript is resumable.
- **`HERMES_HOME` persists across terminal calls in a session**, so a stale value silently redirects
  later `hermes` commands at the wrong home. Unset it after probing another profile.
- **Native tools need native paths.** Windows `git`/`tar` do not accept MSYS `/c/...`: `git -C /c/...`
  fails with "cannot change to", and `tar` treats `C:` as a remote host. `cd` first (a bash builtin)
  or pass `C:/...`; inspect archives with Python's `tarfile`.

## Verify the handoff

```bash
git clone repo.bundle <tmp>/repo
( cd <tmp>/repo && git rev-list --count HEAD && git ls-files | wc -l )
( cd "$OUT" && sha256sum -c MANIFEST.txt )      # expect every line OK
```

Then confirm in the clone that the key deliverables exist (framework/plan docs, the run reports, the
install script), and that each profile archive lists `SOUL.md`, `profile.yaml`, and its rubric.

## Restore on the new machine

```bash
git clone repo.bundle <dir> && cd <dir>
python3 scripts/council.py setup bots           # or: hermes profile import profiles/<name>.tar.gz
hermes profile list                             # expect the bots
hermes -p <bot> tools list                      # capability set intact
```

**Credentials do not travel.** Either `hermes -p <bot> setup`, or copy `.env` by hand; then point the
provider/model at something reachable from the new host. Prefer the repo-driven install
(`install_bots.py`) as the source of truth, with archive import for exact local settings.
