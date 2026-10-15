#!/usr/bin/env python3
"""kb_promote.py - promote an inbox proposal to canonical knowledge, in one verified step.

Promotion is three coordinated edits (move the file to its type directory, set
`status: approved`, append a log entry). Done by hand, the log entry is the one that gets
skipped - and unlike the archive ritual, a missing *promote* line is invisible: the
`proposals_missing_log_entry` check only looks at pages still in `inbox/`, so a promoted
page with no log entry leaves no trace anywhere. The log is the human's audit trail, so
this is not a cosmetic gap.

    kb_promote.py <proposal> [--to entities|concepts|comparisons|queries]
                             [--dry-run] [root]

<proposal> accepts a slug (`inbox/foo`), a basename (`foo`) or a title (`Foo Bar`).

Refuses, writing nothing, when: the page cannot be resolved, it is not in `inbox/`, its
`status` is not `proposed`, a page of the same name already exists in the target directory,
or promotion would immediately leave the page an orphan (no inbound and no outbound links).
That last guard matters: promoting is what makes a page subject to canonical rules, so a
proposal that would land dirty is better fixed in `inbox/` first.
"""
from __future__ import annotations

import argparse
import datetime
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import kb_reindex as kb  # noqa: E402


# `type` -> canonical directory. The inverse of kb_reindex.DIR_TYPE, derived rather
# than restated so the two cannot disagree.
TYPE_DIR = {v: k for k, v in kb.DIR_TYPE.items()}


def resolve(spec: str, pages: dict, archived: dict) -> str | None:
    if spec in pages or spec in archived:
        return spec
    return kb.build_link_map(pages, archived).get(kb.norm_key(spec))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("proposal", help="the inbox page to promote (slug, basename or title)")
    ap.add_argument("--to", choices=sorted(kb.DIR_TYPE),
                    help="target directory; defaults to the page's `type`")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("root", nargs="?")
    a = ap.parse_args()

    root = Path(a.root).expanduser() if a.root else kb.resolve_root()
    if not root.is_dir():
        print(f"kb_promote: root not found: {root}", file=sys.stderr)
        return 1

    pages, archived = kb.build(root)
    slug = resolve(a.proposal, pages, archived)

    problems: list[str] = []
    meta = None
    if slug is None:
        problems.append(f"cannot resolve proposal {a.proposal!r}")
    elif slug in archived:
        problems.append(f"{slug} is archived - unarchive it instead")
    else:
        meta = pages[slug]
        if meta["dir"] != "inbox":
            problems.append(f"{slug} is not in inbox/ (it is in {meta['dir']}/) - "
                            "only proposals are promoted")
        if meta["status"] != "proposed":
            problems.append(f"{slug} has status {meta['status']!r}, not 'proposed'")

    target = a.to
    if target is None and meta is not None:
        target = TYPE_DIR.get(meta["type"]) or "concepts"
    if target is not None and target not in kb.DIR_TYPE:
        problems.append(f"unknown target directory {target!r}")

    if meta is not None and target:
        # meta["path"] carries the .md extension; the slug does not. Deriving the
        # name from the slug drops it and writes an extensionless file.
        dest = root / target / Path(meta["path"]).name
        if dest.exists():
            problems.append(f"{dest.relative_to(root).as_posix()} already exists")
        # Would the promoted page be an orphan? outbound links are in the page;
        # inbound links are whatever currently points at this slug.
        if not meta["outbound"] and not meta["inbound"]:
            problems.append(
                "promotion would leave the page an orphan (no inbound or outbound links) - "
                "add at least one [[wikilink]] to another page first")

    if problems:
        print("kb_promote: refused, nothing written", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1

    today = datetime.date.today().isoformat()
    src = root / meta["path"]
    dest = root / target / Path(meta["path"]).name

    text = src.read_text(encoding="utf-8", errors="replace")
    fm, body = kb.parse_frontmatter(text)
    fm["status"] = "approved"
    fm["updated"] = today
    new_text = kb.render_frontmatter(fm) + body

    entry = (f"\n## [{today}] promote | {fm.get('title', slug)}\n"
             f"- {slug} -> {dest.relative_to(root).as_posix()}\n")

    if a.dry_run:
        print(f"kb_promote DRY RUN: {slug} -> {dest.relative_to(root).as_posix()}")
        print(f"  status    proposed -> approved")
        print(f"  links     outbound {len(meta['outbound'])}, inbound {len(meta['inbound'])}")
        print(f"  log       {entry.strip().splitlines()[0]}")
        return 0

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(new_text, encoding="utf-8", newline="\n")
    src.unlink()
    with (root / "log.md").open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(entry)

    print(f"kb_promote: {slug} -> {dest.relative_to(root).as_posix()}")
    print(f"  status: approved | logged | {len(meta['outbound'])} outbound link(s)")
    print("  run kb_reindex.py to confirm the vault is still clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
