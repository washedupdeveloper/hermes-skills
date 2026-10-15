#!/usr/bin/env python3
"""Every factual claim in the docs is checked against the repo, or it is a bug.

    python3 tests/unit/test_docs.py

The rule this enforces: a claim that can be measured MUST be measured. Prose
that says "40 SKILL.md across 34 skills" is a testable assertion, and the
README has already drifted from reality twice in this repo's history.
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
SKILLS = REPO / "skills"
SUPPORT = ("references", "templates", "assets", "scripts")
DOCS = [REPO / n for n in ("README.md", "AGENTS.md", "docs/upstream.md")]
DOCS += sorted((REPO / "soul").glob("*.md"))
DOCS = [d for d in DOCS if d.is_file()]

WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
         "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}


def _all():
    return sorted(SKILLS.rglob("SKILL.md"))


def _catalog():
    return [p for p in _all()
            if not any(f"/{s}/" in p.as_posix() for s in SUPPORT)]


def _windows():
    out = []
    for p in _catalog():
        fm = p.read_text(encoding="utf-8", errors="replace").split("---", 2)[1]
        m = re.search(r"^platforms:\s*(.+)$", fm, re.M)
        if m and "windows" not in m.group(1):
            continue
        out.append(p)
    return out


def test_the_headline_counts_are_true():
    """'N SKILL.md across M skills — K load on Windows' must equal reality."""
    pat = re.compile(
        r"(\d+)\s+`SKILL\.md`\s+across\s+(\d+)\s+skills\s*[—-]\s*(\d+)\s+load on Windows")
    want = (len(_all()), len(_catalog()), len(_windows()))
    bad = []
    for d in DOCS:
        for m in pat.finditer(d.read_text(encoding="utf-8")):
            got = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
            if got != want:
                bad.append(f"{d.name}: claims {got}, actual {want}")
    assert not bad, bad


def test_the_rubric_count_is_true():
    """'Six of the N are the council's reviewer rubrics'."""
    n = len(list(SKILLS.rglob("assets/rubrics/*/SKILL.md")))
    pat = re.compile(r"(\w+)\s+of the\s+(\d+)\s+are the council's reviewer rubrics")
    bad = []
    for d in DOCS:
        for m in pat.finditer(d.read_text(encoding="utf-8")):
            claimed, total = WORDS.get(m.group(1).lower()), int(m.group(2))
            if claimed != n or total != len(_all()):
                bad.append(f"{d.name}: claims {claimed}/{total}, "
                           f"actual {n}/{len(_all())}")
    assert not bad, bad


def test_every_repo_path_named_in_the_docs_exists():
    """A backticked repo path is a promise. UPSTREAM.md is exempt: its
    'Upstream path' column names paths in the UPSTREAM repo, not here."""
    pat = re.compile(r"`((?:skills|soul|docs|tests|scripts)/[A-Za-z0-9_./-]+)`")
    bad = []
    for d in DOCS:
        if d.name == "upstream.md":
            continue
        for m in pat.finditer(d.read_text(encoding="utf-8")):
            rel = m.group(1).rstrip(".")
            if not (REPO / rel).exists():
                bad.append(f"{d.name}: {rel}")
    assert not bad, bad


def test_upstream_ledger_matches_reality():
    """'Taken' skills must exist here; 'rejected' ones must not.

    Both are claims, and they are opposites — a rejected skill that later gets
    added would silently contradict the ledger that explains why it was not.
    """
    up = REPO / "docs" / "upstream.md"
    if not up.is_file():
        return
    names = {p.parent.name for p in _catalog()}
    taken = not_taken = False
    bad = []
    for line in up.read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            low = line.lower()
            if "not taken" in low:
                taken, not_taken = False, True
            elif line.startswith("## "):
                taken, not_taken = True, False
            continue
        if not line.startswith("|"):
            continue
        m = re.match(r"\|\s*`([a-z0-9-]+)`\s*\|", line)
        if not m:
            continue
        n = m.group(1)
        if not_taken and n in names:
            bad.append(f"rejected `{n}` is present in the repo")
        elif taken and not not_taken and n not in names:
            bad.append(f"taken `{n}` is missing")
    assert not bad, bad


def main() -> int:
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ok    {name}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL  {name}\n        {exc}")
    print(f"\n  {len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
