#!/usr/bin/env python3
"""Report each SKILL.md's word share per H2 section.

Step 5 says to move bulk detail into references/ and leave a pointer. This names the
bulk instead of guessing: the largest section is the tiering candidate, and its share
is what that skill's load cost falls by.

    python3 section-share.py <skills-root> [--min-share 0.25] [--top 3]

Output is the skill's H2 sections only; the intro before the first H2 is excluded,
because it cannot be tiered. A share is not a verdict — read the section before
proposing it move, since a pitfalls or rules block is usually the reason the skill
exists. Words, not tokens: the comparison is between sections of one file.
"""
from __future__ import annotations

import pathlib
import re
import sys


def sections(text: str):
    body = text
    m = re.search(r"\n---\s*\n", text[3:])
    if m:
        body = text[m.end() + 3:]
    for seg in re.split(r"^## ", body, flags=re.M)[1:]:
        yield seg.split("\n", 1)[0].strip(), len(seg.split())


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    root = pathlib.Path(argv[1])
    min_share, top = 0.25, 3
    for i, a in enumerate(argv[2:]):
        if a == "--min-share":
            min_share = float(argv[2:][i + 1])
        elif a == "--top":
            top = int(argv[2:][i + 1])

    rows = []
    for p in sorted(root.rglob("SKILL.md")):
        secs = sorted(sections(p.read_text(encoding="utf-8")), key=lambda t: -t[1])
        total = sum(w for _, w in secs)
        if total and secs[0][1] / total >= min_share:
            rows.append((secs[0][1] / total, p.parent.relative_to(root).as_posix(), total, secs[:top]))

    for share, name, total, secs in sorted(rows, reverse=True):
        print(f"{name}  ({total:,} words in H2 sections)")
        for title, w in secs:
            print(f"  {w / total * 100:5.0f}%  {w:>5}w  {title[:64]}")
        print()
    print(f"{len(rows)} skill(s) with a section at or above {min_share:.0%} of the body.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
