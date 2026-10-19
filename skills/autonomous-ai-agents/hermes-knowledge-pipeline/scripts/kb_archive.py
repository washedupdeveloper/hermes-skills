#!/usr/bin/env python3
"""kb_archive.py - retire a superseded page in one verified step.

Archiving is five coordinated edits (move the file, stamp the archived page, stamp the
successor, repoint inbound links, log it). Done by hand, one of the five gets forgotten -
which is exactly why kb_reindex reports four different archive defects. This performs all
five atomically and refuses to proceed when a precondition is unmet.

    kb_archive.py <page> --superseded-by <new-page> [--reason "..."] [--dry-run] [root]

<page> and <new-page> accept a slug (`entities/foo`), a basename (`foo`), or a title
(`Foo Bar`) - the same tolerant resolution the indexer uses.

Refuses when: either page cannot be resolved, the target is not a live page, the page is
already archived, or it is the same page. Nothing is written unless every check passes.
"""
from __future__ import annotations

import argparse
import datetime
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import kb_reindex as kb  # noqa: E402

# The frontmatter writer lives in kb_reindex so every script shares one implementation.
render_frontmatter = kb.render_frontmatter


def resolve(spec: str, pages: dict, archived: dict) -> str | None:
    """Tolerant lookup: exact slug, basename, or title/alias."""
    if spec in pages or spec in archived:
        return spec
    link_map = kb.build_link_map(pages, archived)
    return link_map.get(kb.norm_key(spec))


def repoint(text: str, old_slug: str, new_slug: str) -> tuple[str, int]:
    """Rewrite wikilinks that resolve to old_slug so they point at new_slug."""
    old_keys = {kb.norm_key(old_slug), kb.norm_key(Path(old_slug).stem)}
    hits = 0

    def sub(m: re.Match) -> str:
        nonlocal hits
        target = m.group(1)
        if kb.norm_key(target) in old_keys:
            hits += 1
            rest = m.group(2) or ""
            return f"[[{new_slug}{rest}]]"
        return m.group(0)

    return re.sub(r"\[\[([^\]|#]+)((?:[#|][^\]]*)?)\]\]", sub, text), hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("page", help="the page to retire (slug, basename or title)")
    ap.add_argument("--superseded-by", required=True, help="the page that replaces it")
    ap.add_argument("--reason", default="", help="one line for the log entry")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("root", nargs="?")
    a = ap.parse_args()

    root = Path(a.root).expanduser() if a.root else kb.resolve_root()
    if not root.is_dir():
        print(f"kb_archive: root not found: {root}", file=sys.stderr)
        return 1

    pages, archived = kb.build(root)
    old_slug = resolve(a.page, pages, archived)
    new_slug = resolve(a.superseded_by, pages, archived)

    problems = []
    if old_slug is None:
        problems.append(f"cannot resolve page {a.page!r}")
    elif old_slug in archived:
        problems.append(f"{old_slug} is already archived")
    if new_slug is None:
        problems.append(f"cannot resolve successor {a.superseded_by!r}")
    elif new_slug in archived:
        problems.append(f"successor {new_slug} is itself archived - point at a live page")
    if old_slug and new_slug and old_slug == new_slug:
        problems.append("a page cannot supersede itself")
    if old_slug and old_slug in pages and pages[old_slug]["status"] == "proposed":
        problems.append(f"{old_slug} is a pending proposal - reject it instead of archiving")

    if problems:
        print("kb_archive: refused, nothing written", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1

    today = datetime.date.today().isoformat()
    old_meta = pages[old_slug]
    old_path = root / old_meta["path"]
    new_path = root / pages[new_slug]["path"]

    # ---- 1. the archived page: status/archived/superseded_by ----
    text = old_path.read_text(encoding="utf-8", errors="replace")
    fm, body = kb.parse_frontmatter(text)
    fm["status"] = "archived"
    fm["archived"] = today
    fm["superseded_by"] = new_slug
    fm["updated"] = today
    archived_text = render_frontmatter(fm) + body

    # ---- 2. the successor: acknowledge what it replaced ----
    ntext = new_path.read_text(encoding="utf-8", errors="replace")
    nfm, nbody = kb.parse_frontmatter(ntext)
    supersedes = kb.as_list(nfm.get("supersedes"))
    old_ref = Path(old_slug).stem
    if old_ref not in supersedes:
        supersedes.append(old_ref)
    nfm["supersedes"] = supersedes
    nfm["updated"] = today
    new_text = render_frontmatter(nfm) + nbody

    # ---- 3. repoint inbound links from live pages ----
    repointed: list[tuple[str, int]] = []
    edits: list[tuple[Path, str]] = []
    for slug, m in pages.items():
        if slug == old_slug:
            continue
        p = root / m["path"]
        src = p.read_text(encoding="utf-8", errors="replace")
        fixed, n = repoint(src, old_slug, new_slug)
        if n:
            repointed.append((slug, n))
            edits.append((p, fixed))

    dest = root / kb.ARCHIVE_DIR / old_meta["path"]
    log = root / "log.md"
    entry = (f"\n## [{today}] archive | {fm.get('title', old_slug)} "
             f"(superseded by {new_slug})\n"
             f"- {old_slug} -> {dest.relative_to(root).as_posix()}\n"
             + (f"- reason: {a.reason}\n" if a.reason else "")
             + ("- repointed links: " + ", ".join(f"{s} ({n})" for s, n in repointed) + "\n"
                if repointed else "- no inbound links to repoint\n"))

    if a.dry_run:
        print(f"kb_archive DRY RUN: {old_slug} -> _archive  (superseded by {new_slug})")
        print(f"  move      {old_meta['path']} -> {dest.relative_to(root).as_posix()}")
        print(f"  successor {new_slug} gains supersedes: {supersedes}")
        print(f"  repoint   {repointed or 'nothing'}")
        print(f"  log       {entry.strip().splitlines()[0]}")
        return 0

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(archived_text, encoding="utf-8", newline="\n")
    old_path.unlink()
    new_path.write_text(new_text, encoding="utf-8", newline="\n")
    for p, fixed in edits:
        p.write_text(fixed, encoding="utf-8", newline="\n")
    with log.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(entry)

    print(f"kb_archive: {old_slug} -> {dest.relative_to(root).as_posix()}")
    print(f"  superseded_by: {new_slug}  (which now declares supersedes: {supersedes})")
    print(f"  repointed {sum(n for _, n in repointed)} link(s) across {len(repointed)} page(s)")
    print("  run kb_reindex.py to confirm the vault is still clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
