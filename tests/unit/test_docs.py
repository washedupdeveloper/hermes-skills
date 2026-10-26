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


# ── the layout the README declares ───────────────────────────────────────────
# The `skill-library` spec's "known category" clause needs a referent, and the README
# layout tree is where a reader looks for it. Parsing that tree keeps one owner for the
# fact: a list written here would be a second copy of what the README already states,
# and this repo has already paid for that shape once.
# re.M is load-bearing: without it findall matches only at offset 0, so a
# seven-row tree parses as one and the comparison passes on a single category.
LAYOUT_ROW = re.compile(r"^[\u251c\u2514]\u2500\u2500 ([a-z0-9][a-z0-9-]*)/", re.M)


def _declared_categories():
    text = (REPO / "README.md").read_text(encoding="utf-8")
    block = re.search(r"^```\nskills/\n(.*?)^```", text, re.S | re.M)
    assert block, "README has no `skills/` layout block"
    return set(LAYOUT_ROW.findall(block.group(1)))


def test_the_declared_layout_matches_the_filesystem():
    """Undeclared on disk, or declared and absent, are both failures.

    The empty-parse guard is load-bearing: a reformatted tree must fail rather than
    pass by comparing an empty set with an empty set.
    """
    declared = _declared_categories()
    assert declared, "no category rows parsed out of the README layout tree"
    on_disk = {p.name for p in SKILLS.iterdir() if p.is_dir()}
    assert declared == on_disk, (
        f"undeclared on disk: {sorted(on_disk - declared)}; "
        f"declared but absent: {sorted(declared - on_disk)}")


# ── a spec names only paths that exist ───────────────────────────────────────
SPECS = REPO / "openspec" / "specs"
SPEC_PATH = re.compile(
    r"`((?:skills|soul|docs|tests|scripts|nix|openspec)/[A-Za-z0-9_./-]+)`")


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
    # The row's link carries the whole stem (0003-the-council-skill-is-a-generated-copy),
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
