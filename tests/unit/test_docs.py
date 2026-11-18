#!/usr/bin/env python3
"""The documentation pointers: an ADR in the table, a spec path, a doc path.

The counts, the layout tree and the upstream ledger moved to `scripts/validate.py`
when the gate became portable — one implementation, one owner. What stays here needs a
regex engine over the docs themselves.

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
SPECS = REPO / "openspec" / "specs"
SPEC_PATH = re.compile(r"`((?:skills|docs|tests|scripts)/[A-Za-z0-9_./-]+)`")
LAYOUT_ROW = re.compile(r"[\u251c\u2514]\u2500\u2500 ([a-z0-9-]+)/")
SUPPORT = ("references", "templates", "assets", "scripts")
DOCS = [REPO / n for n in ("README.md", "AGENTS.md", "docs/upstream.md")]
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


def _declared_categories():
    text = (REPO / "README.md").read_text(encoding="utf-8")
    block = re.search(r"^```\nskills/\n(.*?)^```", text, re.S | re.M)
    assert block, "README has no `skills/` layout block"
    return set(LAYOUT_ROW.findall(block.group(1)))


def test_every_repo_path_named_in_a_spec_exists():
    """A spec is a promise about this tree, so a path it names has to be there.

    `openspec validate --strict` checks shape, not truth — which is how a scenario
    naming a script that never existed survived every gate. `openspec/changes/` is
    excluded on purpose: a delta names the files it is about to create.
    """
    specs = sorted(SPECS.rglob("*.md")) if SPECS.is_dir() else []
    # A vacuous pass is not a pass: an emptied or renamed specs/ would otherwise
    # iterate nothing and report success.
    assert specs, f"no specs found under {SPECS.relative_to(REPO)}"
    bad = []
    for spec in specs:
        for m in SPEC_PATH.finditer(spec.read_text(encoding="utf-8")):
            rel = m.group(1).rstrip(".")
            if not (REPO / rel).exists():
                bad.append(f"{spec.relative_to(REPO)}: {rel}")
    assert not bad, bad


# ── the ADR ledger ───────────────────────────────────────────────────────────
ADR_ROW = re.compile(r"^\|\s*\[(\d{4})\]\(docs/adr/([^)]+)\.md\)\s*\|", re.M)


def test_every_adr_in_the_directory_is_in_the_readme_table():
    """`docs/adr/` records hard-to-reverse choices, and README's table is its index.

    A decision filed but not listed is one a reader will not find; a row pointing at
    nothing is a dead link. Both fail here, and the empty-parse guard keeps a
    reformatted table from passing as complete.
    """
    adr_dir = REPO / "docs" / "adr"
    rows = ADR_ROW.findall((REPO / "README.md").read_text(encoding="utf-8"))
    assert rows, "no ADR rows parsed out of the README table"
    # The row's link carries the whole stem (0009-generic-project),
    # so prefixing the number again builds a name that matches no file.
    listed = {slug for _num, slug in rows}
    filed = {p.stem for p in adr_dir.glob("*.md")}
    assert listed == filed, (
        f"filed but not listed: {sorted(filed - listed)}; "
        f"listed but absent: {sorted(listed - filed)}")


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
