#!/usr/bin/env python3
"""kb_commit.py - commit vault changes on a schedule. Zero LLM calls.

Runs as a `--no-agent` cron job. Silent when there is nothing to commit, so a
quiet hour delivers nothing.

This is the pipeline's safety net, not its primary output. Two jobs:

1. `raw/` immutability is a *convention* that kb_reindex only *reports* on. Git is
   what actually makes it recoverable - a drifted or clobbered source file is one
   `git checkout` away.
2. Every ingest, proposal and promotion is dated and attributable after the fact.

**Pushing is opt-in.** A remote is a per-machine decision, so the default is
commit-only and nothing leaves the host. Set `KB_COMMIT_PUSH=1` in the profile
`.env` (via `hermes config set KB_COMMIT_PUSH 1`) to push to the configured
upstream. A failed push never fails the job: the commit is already local, and the
push is retried on the next run *because the push decision is made from the
branch's ahead-count, not from whether this run happened to commit something*.

That distinction is the whole point. Deciding to push only inside the "we just
committed" branch strands a commit forever after one transient failure - there is
no next commit coming, so there is no retry. Silent when there is nothing to commit
AND the branch is in sync; a push is reported, because it moved a ref.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def resolve_root() -> Path:
    for var in ("HERMES_KB_ROOT", "WIKI_PATH", "OBSIDIAN_VAULT_PATH"):
        val = os.environ.get(var)
        if val:
            return Path(os.path.expanduser(val))
    try:
        import kb_root
        resolved, _ = kb_root.resolve()
        if resolved:
            return Path(resolved)
    except Exception:
        pass
    return Path.cwd()


def git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True)


def counts(root: Path) -> tuple[int, int]:
    pages = proposals = 0
    idx = root / "_meta" / "kb-index.json"
    if idx.is_file():
        try:
            data = json.loads(idx.read_text(encoding="utf-8"))
            pages = data.get("page_count", 0)
            proposals = sum(1 for m in data.get("pages", {}).values()
                            if str(m.get("status")) == "proposed")
        except Exception:
            pass
    if not proposals:
        inbox = root / "inbox"
        proposals = sum(1 for _ in inbox.glob("*.md")) if inbox.is_dir() else 0
    return pages, proposals


def main() -> int:
    root = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else resolve_root()
    if not (root / ".git").exists():
        print(f"KB COMMIT: {root} is not a git repository - run `git init` there "
              f"to enable versioning.")
        return 0

    git(root, "add", "-A")
    staged = git(root, "diff", "--cached", "--quiet")
    committed = False
    if staged.returncode != 0:
        pages, proposals = counts(root)
        files = git(root, "diff", "--cached", "--name-only").stdout.split()
        msg = f"kb: {pages} pages, {proposals} proposals ({len(files)} file(s))"
        done = git(root, "commit", "-m", msg)
        if done.returncode != 0:
            print(f"KB COMMIT FAILED: {done.stderr.strip()[:400]}")
            return 0
        print(f"KB COMMIT: {msg}")
        committed = True

    # Opt-in push. Deliberately reached even when nothing was staged: a commit whose
    # push failed earlier must still be retried, and nothing else will retry it.
    if os.environ.get("KB_COMMIT_PUSH", "").strip().lower() not in ("1", "true", "yes", "on"):
        return 0

    upstream = git(root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
    if upstream.returncode != 0:
        # Only worth saying when this run stranded a commit. A vault with push enabled
        # but no upstream is a configuration choice, not a finding, and reporting it
        # every hour would make the job permanently noisy - the one thing this channel
        # must never be. Silence is the healthy signal.
        if committed:
            print("KB PUSH SKIPPED: no upstream configured for this branch "
                  "(`git push -u <remote> <branch>` once to set it)")
        return 0

    ahead = git(root, "rev-list", "--count", "@{upstream}..HEAD")
    if ahead.returncode == 0 and ahead.stdout.strip() in ("", "0"):
        return 0  # nothing to commit and already in sync -> silent

    pushed = git(root, "push")
    if pushed.returncode != 0:
        print(f"KB PUSH FAILED: {pushed.stderr.strip()[:400]}")
        print("  the commit is local; the next run will retry it")
    else:
        n = ahead.stdout.strip() or "?"
        print(f"KB PUSH: {upstream.stdout.strip()} ({n} commit(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
