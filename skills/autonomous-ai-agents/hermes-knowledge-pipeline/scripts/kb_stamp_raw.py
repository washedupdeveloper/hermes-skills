#!/usr/bin/env python3
"""kb_stamp_raw.py - stamp a raw/ source file with correct provenance frontmatter.

`raw/` is immutable and every file in it carries `source_url`, `ingested` and a
`sha256` over the body below the frontmatter. Computing that hash by hand is
error-prone in exactly the way that matters: a wrong hash makes the hourly
reindex cry drift forever, and a *right* hash computed over CRLF bytes makes it
cry drift the first time the same file is touched on another OS.

This script owns both problems. It normalises line endings to LF, recomputes the
hash over the LF-normalised body (the same definition kb_reindex.py checks
against), merges the supplied metadata into the existing frontmatter, and writes
the file back with LF endings.

Usage:
    kb_stamp_raw.py <file.md> [--source-url URL] [--title T] [--author A]
                    [--published D] [--fetched-via V] [--dry-run]

Idempotent: re-running on an already-stamped file rewrites the same bytes.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import re
import sys
from pathlib import Path

FM_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)
ORDER = ["source_url", "title", "author", "published", "ingested", "fetched_via", "sha256"]


def body_hash(body: str) -> str:
    normalised = body.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


def split_frontmatter(text: str) -> tuple[dict, str]:
    m = FM_RE.match(text)
    if not m:
        return {}, text
    fm: dict = {}
    for line in m.group(1).splitlines():
        if ":" in line and not line.lstrip().startswith("#"):
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip()
    return fm, text[m.end():]


def render(fm: dict) -> str:
    keys = [k for k in ORDER if k in fm] + sorted(k for k in fm if k not in ORDER)
    return "---\n" + "".join(f"{k}: {fm[k]}\n" for k in keys) + "---\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--source-url")
    ap.add_argument("--title")
    ap.add_argument("--author")
    ap.add_argument("--published")
    ap.add_argument("--fetched-via")
    ap.add_argument("--ingested", default=datetime.date.today().isoformat())
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    p = Path(a.file)
    if not p.is_file():
        print(f"kb_stamp_raw: not a file: {p}", file=sys.stderr)
        return 1

    raw = p.read_text(encoding="utf-8", errors="replace")
    fm, body = split_frontmatter(raw)
    body = body.replace("\r\n", "\n").replace("\r", "\n")

    for key, val in (("source_url", a.source_url), ("title", a.title),
                     ("author", a.author), ("published", a.published),
                     ("fetched_via", a.fetched_via), ("ingested", a.ingested)):
        if val is not None:
            fm[key] = val
    fm["sha256"] = body_hash(body)

    out = render(fm) + body
    if a.dry_run:
        print(render(fm), end="")
        return 0

    if p.read_text(encoding="utf-8", errors="replace") != out:
        p.write_text(out, encoding="utf-8", newline="\n")
        print(f"stamped {p.name}: sha256={fm['sha256'][:12]}")
    else:
        print(f"unchanged {p.name}: sha256={fm['sha256'][:12]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
