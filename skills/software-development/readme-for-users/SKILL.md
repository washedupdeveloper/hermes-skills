---
name: readme-for-users
description: "Use when rewriting a README for tool users."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
category: software-development
metadata:
  hermes:
    tags: [readme, documentation, cli, user-guide, onboarding]
    related_skills: [writing-for-agents, release-versioning, handoff]
writes: [none]
---

# readme-for-users

Write the documentation a new user needs to install, run, and interpret the
tool without reading the source or its internal design notes.

## When to Use

- A project README is missing, stale, too long, or written for maintainers
  rather than new users.
- The user asks for install/run/read-the-result instructions for someone else.
- A CLI grew flags or commands and the README needs to be reconciled with the
  actual parser and its documentation tests.

## Procedure

1. **Establish the real surface first.** Read the current README, `--help` for
   every command, the docs index, the packaging metadata, and the tests that
   assert README content. If the repository checks that every flag or command is
   documented, that complete surface must remain in the README even while you
   compress everything else.

2. **Separate installed use from development use.** A source checkout's
   `nix develop` or dev shell may expose test tools but not the shipped console
   script. Print the install/build path for the artifact a user receives, and
   label source-only commands as maintainer commands. Never present a command
   that only works after a step the README omitted.

3. **Write for a reader with no context.** Use this order unless the project has
   a stronger one:

   - one sentence: what it does, and what it is not;
   - intended use and non-goals, so the reader knows when to reach for it;
   - prerequisites and a setup/health check before the first real run;
   - install for the shipped artifact(s), with the source path separate;
   - first successful run, including a free plan/dry-run if one exists;
   - how to read the result: states, exit codes, output files, and what to do
     for each outcome;
   - common workflows (local, CI, pull request, scoped review, large changes,
     accepted-risk baselines) and configuration;
   - a complete flag reference when tests require it, kept compact;
   - troubleshooting as symptom → likely cause → fix;
   - safety/privacy and links to deeper docs.

4. **Remove or update stale operational claims.** Version strings, commit
   hashes, test/claim counts, old checkout paths, deleted modules, and
   “published” status when the remote is behind are all claims. Re-measure them,
   remove them, or label the document historical. Keep internal architecture,
   migration history, and maintainer flag rationale in linked reference docs,
   not in the user's first page.

5. **Stay concise.** For a complex CLI, roughly 300–400 lines is usually enough;
   a 500+ line internal design dump is not a user guide. Prefer one idea per
   section and copy-pasteable examples over exhaustive prose. Every sentence
   should help the reader decide, run, or interpret something.

6. **Verify the documentation by the repository's own gates.** Run the docs,
   docs-index, release and citation tests if present; check links and
   `git diff --check`; and re-read every command against the installation path.
   Report the checks you actually ran and the current commit, not just “README
   updated.”

7. **Protect a shared worktree.** If unrelated files are already staged, commit
   only the README with a path-scoped `git commit README.md -m ...`. Never run
   `git commit --amend` while another writer's staged files are present. After
   the commit, run `git show --stat --oneline HEAD` and confirm it contains only
   the intended path. If a broad index slipped into the commit, recover with
   `git reset --soft HEAD^`, then re-run the path-scoped commit; verify the
   target branch and remote afterward.

## Pitfalls

- **A docs test can pin the README's vocabulary.** Removing an exhaustive flag
  table to simplify the page fails a test that asserts every CLI option is
  documented. Read the tests before compressing; keep all option strings, even
  if they live in a compact table or code block.
- **A source checkout is not an installed tool.** `nix develop` may provide
  pytest and linters but no CLI binary. Show the wheel/image/build
  install path separately from maintainer commands.
- **Stale status docs are worse than no status docs.** A handoff claiming an old
  commit, count or checkout path teaches a false current state; re-measure it or
  remove it. If it must remain, label it historical.
- **A README is not an architecture document.** Module maps, refactor logs and
  implementation rationale belong in linked docs; the user needs what it does,
  how to run it, and how to read failure.
- **A generated README often lacks a final newline.** Repositories frequently
  enforce a trailing LF (`test_files.py` or an equivalent packaging test);
  append one before committing and run the file-convention test. This is a
  packaging rule, not cosmetic style.
- **A new documentation page needs an index entry.** If the repository checks
  that every Markdown file is linked from a docs index, add the page to the
  index and run the index test; an unindexed page fails the gate even when its
  links are correct.
- **Do not explain the product with adjectives.** “Powerful”, “seamless” and
  “robust” do not tell a user whether they can run it or what a FAIL means.
