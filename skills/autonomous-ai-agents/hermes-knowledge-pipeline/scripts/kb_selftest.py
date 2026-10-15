#!/usr/bin/env python3
"""kb_selftest.py - verify the pipeline against a fixture vault.

Builds a deliberately broken vault in a temp directory, runs the indexer as a
subprocess, and asserts every defect is DETECTED and that a healthy vault
produces NO output. Then checks the tolerant link forms and idempotency.

Why this exists: the first version of the indexer was verified with ad-hoc shell
one-liners, which is unrepeatable - the next agent to touch it cannot tell
whether a change broke detection. Run this after every edit:

    python scripts/kb_selftest.py

Exit 0 = all assertions passed. Non-zero = failures, each with detail.
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import kb_reindex  # noqa: E402

FAILURES: list[str] = []


class Skip(Exception):
    """Raised to stop the run when the entry script itself is missing."""


def check(cond: bool, label: str) -> None:
    if not cond:
        FAILURES.append(label)


SCHEMA = """# Wiki Schema

Prose rules here are for humans; the block below is what the indexer reads.

```yaml
# kb-schema
schema_version: 1
tags:
  alpha:
  beta:
```
"""


def write(root: Path, rel: str, body: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8", newline="\n")


def page(title: str, tags: str, body: str, extra: str = "", status: str = "approved",
         dtype: str = "concept") -> str:
    return ("---\n"
            f"title: {title}\n"
            "created: 2026-01-01\nupdated: 2026-01-01\n"
            f"type: {dtype}\n"
            f"tags: [{tags}]\n"
            "sources: [raw/articles/src.md]\n"
            f"status: {status}\n"
            f"{extra}"
            "---\n" + body)


def run(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(HERE / "kb_reindex.py"), str(root), *args],
                          capture_output=True, text=True)


def build_dirty(root: Path) -> None:
    write(root, "SCHEMA.md", SCHEMA)
    # Log the canonical pages so the ONLY findings are the seeded defects. Leaving them
    # unlogged would also trip canonical_page_never_logged, and a title from that finding
    # ("Page B") would then collide with the link-resolution assertion below - an
    # ambiguous test is worse than no test.
    write(root, "log.md",
          "# Wiki Log\n\n## [2026-01-01] create | seed\n- entities/page-a\n"
          "- concepts/page-b\n- concepts/bad-tag\n- concepts/mismatch\n")
    # page-b is referenced by TITLE and by ALIAS from page-a -> both must resolve
    write(root, "entities/page-a.md",
          page("Page A", "alpha",
               "Links to [[Page B]] and [[Bee]] and [[nope]] and [[retired-b]].\n",
               dtype="entity"))
    write(root, "concepts/page-b.md",
          page("Page B", "beta", "Target page.\n", extra="aliases: [Bee]\n"))
    write(root, "concepts/bad-tag.md", page("Bad Tag", "nonsense", "Out of taxonomy.\n"))
    write(root, "concepts/mismatch.md",
          page("Mismatch", "alpha", "Proposed but not in inbox.\n", status="proposed"))
    write(root, "inbox/pending.md", page("Pending", "alpha", "A legitimate proposal.\n",
                                          status="proposed"))

    # ---- work/ items: the supervisor board's fields ----
    # `status` on a work item is WORK state, not promotion state, and the board's fields
    # are required rather than optional - a board with blank columns is a board nobody
    # trusts. One of each defect, plus a valid item that must stay unreported.
    write(root, "work/ok-item.md",
          page("Good Work Item", "alpha", "Valid board entry.\n",
               extra="priority: P2\nowner: agent\ntopic: board\n",
               status="active", dtype="work"))
    write(root, "work/bad-status.md",
          page("Bad Work Status", "alpha", "Promotion status on a work item.\n",
               extra="priority: P1\nowner: agent\ntopic: board\n",
               status="approved", dtype="work"))
    write(root, "work/no-priority.md",
          page("No Priority", "alpha", "Missing a required board field.\n",
               extra="owner: agent\ntopic: board\n",
               status="active", dtype="work"))
    write(root, "work/blocked-unexplained.md",
          page("Blocked Unexplained", "alpha", "Blocked with nothing to point at.\n",
               extra="priority: P0\nowner: human\ntopic: board\n",
               status="blocked", dtype="work"))

    # ---- archive integrity: each of these is a distinct defect ----
    # 1. retired without naming what replaced it
    write(root, "_archive/entities/no-successor.md",
          page("No Successor", "alpha", "Archived, but names no replacement.\n",
               status="archived", dtype="entity"))
    # 2. names a successor that does not exist
    write(root, "_archive/entities/ghost-target.md",
          page("Ghost Target", "alpha", "Successor is a phantom.\n",
               extra="superseded_by: nowhere-at-all\n", status="archived", dtype="entity"))
    # 3. successor exists but does not acknowledge replacing it (non-reciprocal)
    write(root, "_archive/concepts/retired-b.md",
          page("Retired B", "beta", "Superseded by page-b, which never says so.\n",
               extra="superseded_by: page-b\n", status="archived"))

    # raw: one correct (CRLF body vs LF hash), one drifted, one unstamped
    body_lf = "CRLF body line one.\nline two.\n"
    write(root, "raw/articles/ok.md",
          "---\nsource_url: https://example.com/ok\ningested: 2026-01-01\nsha256: "
          + kb_reindex.body_hash(body_lf) + "\n---\n" + body_lf.replace("\n", "\r\n"))
    write(root, "raw/articles/src.md",
          "---\nsource_url: https://example.com/src\ningested: 2026-01-01\n"
          "sha256: deadbeefdeadbeef\n---\nbody\n")
    write(root, "raw/articles/unstamped.md", "---\n---\nno provenance\n")


def build_clean(root: Path) -> None:
    write(root, "SCHEMA.md", SCHEMA)
    write(root, "entities/page-a.md",
          page("Page A", "alpha", "Links to [[Page B]].\n", dtype="entity"))
    # A CLEAN archive: retired, names its successor, and the successor acknowledges
    # it. This must not be reported - the vault stays silent with archived iterations.
    write(root, "concepts/page-b.md",
          page("Page B", "beta", "Links to [[Page A]].\n", extra="supersedes: [retired-c]\n"))
    write(root, "_archive/entities/retired-c.md",
          page("Retired C", "alpha", "Superseded cleanly.\n",
               extra="superseded_by: page-b\narchived: 2026-01-01\n",
               status="archived", dtype="entity"))
    write(root, "inbox/pending.md",
          page("Pending", "alpha", "Proposal, logged.\n", status="proposed"))
    (root / "log.md").write_text(
        "# Wiki Log\n\n## [2026-01-01] create | seed\n- entities/page-a\n- concepts/page-b\n"
        "\n## [2026-01-01] propose | Pending\n", encoding="utf-8", newline="\n")
    body = "clean body\n"
    write(root, "raw/articles/ok.md",
          "---\nsource_url: https://example.com/ok\ningested: 2026-01-01\nsha256: "
          + kb_reindex.body_hash(body) + "\n---\n" + body)


def check_commit_retry(tmp: Path) -> None:
    """The push must be decided from the ahead-count, not from whether this run committed.

    A commit whose push failed must still be pushed by a later run that changes nothing -
    otherwise one transient network failure strands it forever, because there is no next
    commit to trigger the retry. And a run with nothing to do must stay silent.
    """
    import os
    bare = tmp / "origin.git"
    work = tmp / "vault"
    broken = tmp / "not-a-remote"
    subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(bare), "symbolic-ref", "HEAD", "refs/heads/main"],
                   check=True, capture_output=True)
    work.mkdir(parents=True)
    (work / "inbox").mkdir()
    (work / "inbox" / "a.md").write_text("hi\n", encoding="utf-8", newline="\n")

    def g(*args: str, cwd: Path = work) -> str:
        r = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
        return (r.stdout + r.stderr).strip()

    g("init", "-q", "-b", "main")
    g("config", "user.email", "selftest@example.com")
    g("config", "user.name", "selftest")
    g("remote", "add", "origin", str(bare))
    g("add", "-A")
    g("commit", "-q", "-m", "init")
    g("push", "-q", "-u", "origin", "main")

    env = dict(os.environ, KB_COMMIT_PUSH="1")

    def commit_job() -> str:
        r = subprocess.run([sys.executable, str(HERE / "kb_commit.py"), str(work)],
                           capture_output=True, text=True, env=env)
        return (r.stdout + r.stderr).strip()

    check(commit_job() == "", "commit: clean and in sync is silent")

    # strand a commit: the remote is unreachable when the change lands
    g("remote", "set-url", "origin", str(broken))
    (work / "inbox" / "b.md").write_text("more\n", encoding="utf-8", newline="\n")
    out = commit_job()
    check("KB COMMIT:" in out and "KB PUSH FAILED" in out,
          "commit: a failed push still commits locally")
    check(g("rev-list", "--count", "@{upstream}..HEAD") == "1",
          "commit: the commit is stranded, one ahead of upstream")

    # restore the remote and change NOTHING - the retry must still happen
    g("remote", "set-url", "origin", str(bare))
    out = commit_job()
    check("KB PUSH:" in out, "commit: a later run with no changes retries the stranded push")
    check(g("rev-list", "--count", "@{upstream}..HEAD") == "0",
          "commit: the branch is in sync after the retry")
    check(g("ls-tree", "-r", "--name-only", "main", cwd=bare).split()
          == ["inbox/a.md", "inbox/b.md"], "commit: the remote actually received both files")
    check(commit_job() == "", "commit: silent again once in sync")

    # push enabled, no upstream at all, nothing to commit -> silence, not a hourly complaint
    w2 = tmp / "noup"
    (w2 / "inbox").mkdir(parents=True)
    (w2 / "inbox" / "a.md").write_text("x\n", encoding="utf-8", newline="\n")

    def g2(*args: str) -> str:
        r = subprocess.run(["git", "-C", str(w2), *args], capture_output=True, text=True)
        return (r.stdout + r.stderr).strip()

    g2("init", "-q", "-b", "main")
    g2("config", "user.email", "selftest@example.com")
    g2("config", "user.name", "selftest")
    g2("add", "-A")
    g2("commit", "-q", "-m", "init")
    r = subprocess.run([sys.executable, str(HERE / "kb_commit.py"), str(w2)],
                       capture_output=True, text=True, env=env)
    check((r.stdout + r.stderr).strip() == "",
          "commit: push enabled with no upstream and nothing to do is silent")


def check_vanished_dir(tmp: Path) -> None:
    """A page directory deleted out-of-band must be reported, not silently empty.

    The vault is silent when healthy, so a directory disappearing is invisible unless
    something says so - and the visible symptom is a base or an index that is simply
    empty, which reads as "nothing to show" rather than "the data is gone". The
    previous index is the memory that makes it detectable.
    """
    root = tmp / "vanish"
    for d in ("concepts", "work", "_meta"):
        (root / d).mkdir(parents=True, exist_ok=True)
    write(root, "SCHEMA.md", SCHEMA)
    write(root, "log.md", "# Wiki Log\n\n## [2026-01-01] create | seed\n- work/thing\n")
    write(root, "concepts/keep.md",
          page("Keep", "alpha", "Links [[work/thing]].\n"))
    write(root, "work/thing.md",
          page("Thing", "alpha", "Body.\n",
               extra="priority: P1\nowner: agent\ntopic: t\n",
               status="active", dtype="work"))

    run(root)                                   # records work/ in the index
    check("page_directory_vanished" not in run(root).stdout,
          "vanish: a healthy vault reports no vanished directory")

    shutil.rmtree(root / "work")                # the out-of-band deletion
    out = run(root).stdout
    check("page_directory_vanished" in out and "work" in out,
          "vanish: a deleted page directory IS reported")
    check("restore with" in out, "vanish: the finding says how to restore it")

    write(root, "work/thing.md",
          page("Thing", "alpha", "Body.\n",
               extra="priority: P1\nowner: agent\ntopic: t\n",
               status="active", dtype="work"))
    check("page_directory_vanished" not in run(root).stdout,
          "vanish: quiet again once the directory is restored")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        dirty = Path(tmp) / "dirty"
        dirty.mkdir()
        build_dirty(dirty)
        proc = run(dirty)
        out = proc.stdout

        check(proc.returncode == 0, "dirty: exit code 0")
        check("nope" in out, "dirty: genuinely broken link is reported")
        check("Page B" not in out and "Bee" not in out,
              "dirty: title-form and alias-form links resolve (not reported broken)")
        check("nonsense" in out, "dirty: out-of-taxonomy tag is reported")
        check("status_contradicts_location" in out,
              "dirty: proposed page outside inbox/ is reported")
        check("raw_sha256_drift" in out and "src.md" in out, "dirty: sha256 drift is reported")
        check("raw_missing_provenance" in out and "unstamped" in out,
              "dirty: raw file with no sha256 is reported")
        check("proposals_missing_log_entry" in out, "dirty: unlogged proposal is reported")

        # ---- work/ board ----
        check("work_item_status_or_priority_invalid" in out and "bad-status" in out,
              "dirty: promotion status on a work item is reported")
        check("work_item_missing_board_field" in out and "no-priority" in out,
              "dirty: work item missing a required board field is reported")
        check("blocked_by" in out and "blocked-unexplained" in out,
              "dirty: blocked work item with no reason is reported")
        check("ok-item" not in out,
              "dirty: a valid work item is NOT reported (no false positives)")
        check("CRLF" not in out or "ok.md" not in out,
              "dirty: CRLF-vs-LF body is NOT reported as drift")

        # ---- archive lifecycle ----
        check("archived_without_successor" in out,
              "dirty: archived page with no successor is reported")
        check("supersession_target_missing" in out and "nowhere-at-all" in out,
              "dirty: superseded_by pointing at nothing is reported")
        check("supersedes_not_reciprocated" in out,
              "dirty: non-reciprocal supersession is reported")
        check("links_to_archived_page" in out and "retired-b" in out,
              "dirty: a live page linking to an archived page is reported")

        # state must not be reported as a finding
        check("proposed_pages" not in out, "dirty: pending proposals are state, not findings")
        check("archived_pages" not in out, "dirty: archived pages are state, not findings")

        # ---- kb_promote.py: promotion must leave a LINT-CLEAN vault ----
        promo = Path(tmp) / "promote"
        promo.mkdir()
        write(promo, "SCHEMA.md", SCHEMA)
        write(promo, "log.md",
              "# Wiki Log\n\n## [2026-01-01] create | seed\n- concepts/existing\n"
              "\n## [2026-01-01] propose | Isolated\n")
        write(promo, "concepts/existing.md",
              page("Existing", "alpha", "Links to [[promo]].\n"))
        write(promo, "inbox/promo.md",
              page("Promo", "beta", "Links to [[existing]].\n", status="proposed"))
        write(promo, "inbox/isolated.md",
              page("Isolated", "beta", "No links at all.\n", status="proposed"))

        pr = subprocess.run([sys.executable, str(HERE / "kb_promote.py"), "promo", str(promo)],
                            capture_output=True, text=True)
        check(pr.returncode == 0,
              f"promote: exits 0 (got {pr.returncode}: {pr.stderr.strip()[:200]})")
        check(not (promo / "inbox" / "promo.md").exists(), "promote: left the inbox")
        check((promo / "concepts" / "promo.md").is_file(),
              "promote: landed in its type directory")
        promoted = (promo / "concepts" / "promo.md").read_text(encoding="utf-8")
        check("status: approved" in promoted, "promote: sets status: approved")
        check("promote | Promo" in (promo / "log.md").read_text(encoding="utf-8"),
              "promote: appends a log entry")
        pr_idx = run(promo)
        check(pr_idx.stdout.strip() == "",
              f"promote: vault is still LINT-CLEAN (got: {pr_idx.stdout.strip()[:250]!r})")

        # guards
        again = subprocess.run(
            [sys.executable, str(HERE / "kb_promote.py"), "existing", str(promo)],
            capture_output=True, text=True)
        check(again.returncode == 1, "promote: refuses a page that is not in inbox/")
        orphan = subprocess.run(
            [sys.executable, str(HERE / "kb_promote.py"), "isolated", str(promo)],
            capture_output=True, text=True)
        check(orphan.returncode == 1,
              "promote: refuses a proposal that would land as an orphan")
        check((promo / "inbox" / "isolated.md").is_file(), "promote: refusal writes nothing")

        # ---- canonical_page_never_logged: an unlogged page is a finding ----
        unlogged_dir = Path(tmp) / "unlogged"
        unlogged_dir.mkdir()
        write(unlogged_dir, "SCHEMA.md", SCHEMA)
        write(unlogged_dir, "log.md", "# Wiki Log\n")
        write(unlogged_dir, "concepts/orphan-of-history.md",
              page("Orphan Of History", "alpha", "Links to [[nowhere]].\n"))
        ul = run(unlogged_dir)
        check("canonical_page_never_logged" in ul.stdout,
              "lint: a canonical page absent from log.md is reported")

        # generated outputs
        check((dirty / "index.md").is_file(), "dirty: index.md was generated")
        check((dirty / "_meta" / "orient.json").is_file(), "dirty: orient.json was generated")
        index = (dirty / "index.md").read_text(encoding="utf-8")
        check("do not edit" in index, "dirty: index.md carries the generated banner")
        check("[[entities/page-a]]" in index, "dirty: index lists canonical pages")
        check("[[inbox/pending]]" in index, "dirty: index lists pending proposals")
        check("## Archived iterations" in index, "dirty: index has an archive section")
        check("superseded by" in index, "dirty: archive entries name their successor")

        # idempotency: unchanged vault -> byte-identical index
        before = (dirty / "index.md").read_bytes()
        run(dirty)
        check(before == (dirty / "index.md").read_bytes(), "dirty: index.md is idempotent")

        # orient mode writes nothing and is readable
        orient_proc = run(dirty, "--orient")
        check("KB ORIENTATION" in orient_proc.stdout, "orient: prints an orientation")
        check("schema v1" in orient_proc.stdout, "orient: reads schema version from SCHEMA.md")

        # clean vault must be SILENT
        clean = Path(tmp) / "clean"
        clean.mkdir()
        build_clean(clean)
        clean_proc = run(clean)
        check(clean_proc.stdout.strip() == "",
              f"clean: vault is silent (got: {clean_proc.stdout.strip()[:200]!r})")
        clean_index = (clean / "index.md").read_text(encoding="utf-8")
        check("[[entities/page-a]]" in clean_index, "clean: index still generated")
        check("retired-c" in clean_index, "clean: archived iteration appears in the index")
        check("## Archived iterations" in clean_index, "clean: archive section present")

        # ---- kb_archive.py: the mechanical archive must leave a LINT-CLEAN vault ----
        arc = Path(tmp) / "archive"
        arc.mkdir()
        write(arc, "SCHEMA.md", SCHEMA)
        write(arc, "log.md",
              "# Wiki Log\n\n## [2026-01-01] create | seed\n- concepts/current\n- concepts/other\n")
        write(arc, "concepts/legacy.md",
              page("Legacy", "alpha", "The old approach.\n"))
        write(arc, "concepts/current.md",
              page("Current", "beta", "Links to [[other]].\n"))
        write(arc, "concepts/other.md",
              page("Other", "beta", "Links to [[legacy]].\n"))

        arc_proc = subprocess.run(
            [sys.executable, str(HERE / "kb_archive.py"), "legacy",
             "--superseded-by", "current", "--reason", "replaced by the new approach",
             str(arc)], capture_output=True, text=True)
        check(arc_proc.returncode == 0,
              f"archive: exits 0 (got {arc_proc.returncode}: {arc_proc.stderr.strip()[:200]})")
        check(not (arc / "concepts" / "legacy.md").exists(),
              "archive: the retired page left its canonical directory")
        check((arc / "_archive" / "concepts" / "legacy.md").is_file(),
              "archive: the retired page is in _archive/")

        moved = (arc / "_archive" / "concepts" / "legacy.md").read_text(encoding="utf-8")
        check("status: archived" in moved, "archive: sets status: archived")
        check("superseded_by: concepts/current" in moved, "archive: records its successor")
        check("archived: " in moved, "archive: records the archive date")

        succ = (arc / "concepts" / "current.md").read_text(encoding="utf-8")
        check("supersedes: [legacy]" in succ, "archive: successor acknowledges what it replaced")

        other = (arc / "concepts" / "other.md").read_text(encoding="utf-8")
        # Repointed to the full successor slug - unambiguous, and what the index uses.
        check("[[concepts/current]]" in other and "[[legacy]]" not in other,
              f"archive: inbound links are repointed at the successor (got: {other.splitlines()[-1]!r})")
        check("archive | Legacy" in (arc / "log.md").read_text(encoding="utf-8"),
              "archive: appends a log entry")

        arc_reindex = run(arc)
        check(arc_reindex.stdout.strip() == "",
              f"archive: vault is still LINT-CLEAN (got: {arc_reindex.stdout.strip()[:250]!r})")

        # refusing to archive a pending proposal is the guard rail
        write(arc, "inbox/draft.md",
              page("Draft", "alpha", "A proposal.\n", status="proposed"))
        refuse = subprocess.run(
            [sys.executable, str(HERE / "kb_archive.py"), "draft",
             "--superseded-by", "current", str(arc)], capture_output=True, text=True)
        check(refuse.returncode == 1, "archive: refuses to archive a pending proposal")
        check((arc / "inbox" / "draft.md").is_file(),
              "archive: refusal writes nothing")

        # ---- commit job: the push must be decided from the ahead-count ----
        check_commit_retry(Path(tmp) / "committest")

        # ---- a page directory vanishing must be loud, not silently empty ----
        check_vanished_dir(Path(tmp) / "vanishtest")

    if FAILURES:
        print(f"kb_selftest: {len(FAILURES)} FAILURE(S)")
        for f in FAILURES:
            print(f"  FAIL  {f}")
        return 1
    print("kb_selftest: OK (detection, silence, link forms, generation, idempotency, "
          "commit retry, vanished dir)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
