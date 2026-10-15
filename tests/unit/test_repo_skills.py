#!/usr/bin/env python3
"""Contract tests for the skills this repo ships.

Standalone — no pytest required:

    python3 tests/unit/test_repo_skills.py

Every check here was a hand-run command before it was a test. The properties are
the ones that have actually broken in this repo: a description past the index
window, a reference file that was promised and never written, a skill that
shadows the repo from the live library.
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
SKILLS = REPO / "skills"
SUPPORT = ("references", "templates", "assets", "scripts")

# The index truncates at 57 chars + "...", so the trigger must be self-contained
# there. Past that, the only part loaded before a skill opens is cut mid-word.
DESC_MAX = 57

REQUIRED = ("name", "description", "version", "author", "license", "platforms")


def skill_files() -> list[pathlib.Path]:
    return sorted(SKILLS.rglob("SKILL.md"))


def catalog_files() -> list[pathlib.Path]:
    """Skills that ARE catalog entries — not support files under a skill."""
    return [p for p in skill_files()
            if not any(f"/{s}/" in p.as_posix() for s in SUPPORT)]


def parse(p: pathlib.Path) -> tuple[dict, str]:
    text = p.read_text(encoding="utf-8")
    assert text.startswith("---"), f"{p} must start with --- at byte 0"
    m = re.search(r"\n---\s*\n", text[3:])
    assert m, f"{p} has no closing ---"
    fm: dict = {}
    for line in text[3:m.start() + 3].splitlines():
        mm = re.match(r"^([a-z_]+):\s*(.*)$", line)
        if mm:
            fm[mm.group(1)] = mm.group(2).strip().strip('"')
    return fm, text[m.end() + 3:]


def test_frontmatter_is_complete():
    missing = []
    for p in skill_files():
        fm, _ = parse(p)
        for field in REQUIRED:
            if field not in fm:
                missing.append(f"{p.parent.name}:{field}")
    assert not missing, f"missing frontmatter: {missing}"


def test_description_fits_the_index_window():
    """The description is the ONLY part in the index — every session pays it."""
    bad = []
    for p in catalog_files():
        fm, _ = parse(p)
        d = fm.get("description", "")
        if len(d) > DESC_MAX:
            bad.append(f"{p.parent.name}: {len(d)} chars (max {DESC_MAX})")
    assert not bad, f"description past the index window: {bad}"


def test_name_matches_directory():
    """The skill registers as /<name>; the installer copies by directory name."""
    bad = []
    for p in skill_files():
        fm, _ = parse(p)
        if fm.get("name") != p.parent.name:
            bad.append(f"{p.parent.name} != {fm.get('name')}")
    assert not bad, f"name/directory mismatch: {bad}"


def test_no_dead_references():
    """A promised reference file that does not exist is a broken pointer.

    Only POINTERS are checked — a path the reader is meant to follow. A path in
    a prescriptive sentence ("Write the installer (`scripts/x.sh`)") names a file
    to CREATE, not one that exists, so flagging it would be wrong. Same for a
    placeholder (`references/<topic>.md`).
    """
    write_verbs = re.compile(
        r"\b(write|create|add|author|generate|scaffold|produce)\b", re.I)
    bad = []
    for p in catalog_files():
        _, body = parse(p)
        for line in body.splitlines():
            for m in re.finditer(
                    r"`((?:references|templates|assets|scripts)/[^`\s]+)`", line):
                rel = m.group(1).rstrip(".")
                if "<" in rel or ">" in rel:
                    continue  # a placeholder, not a path
                if write_verbs.search(line):
                    continue  # prescriptive: the file does not exist yet
                if not (p.parent / rel).exists():
                    bad.append(f"{p.parent.name} -> {rel}")
    assert not bad, f"dead references: {bad}"


def test_related_skills_resolve_in_repo():
    names = {p.parent.name for p in catalog_files()}
    bad = []
    for p in catalog_files():
        _, body = parse(p)
        m = re.search(r"related_skills:\s*\[([^\]]*)\]", body)
        if not m:
            continue
        for ref in (x.strip() for x in m.group(1).split(",")):
            if ref and ref in names:
                continue
            # Bundled Hermes skills live outside this repo; only flag a name
            # that looks like one of ours and is absent.
            if ref.startswith(("reviewer-", "review-council")):
                bad.append(f"{p.parent.name} -> {ref}")
    assert not bad, f"unresolved in-repo related_skills: {bad}"


def test_related_skills_frontmatter_resolves():
    """`metadata.hermes.related_skills` must name skills that exist somewhere."""
    names = {p.parent.name for p in catalog_files()}
    bad = []
    for p in catalog_files():
        fm, _ = parse(p)
        raw = fm.get("related_skills", "")
        for ref in (x.strip() for x in raw.strip("[]").split(",") if x.strip()):
            if ref not in names and not ref.startswith(
                    ("hermes-", "council", "nixos", "test-", "systematic",
                     "requesting", "simplify", "spike", "deterministic",
                     "grounded", "wait", "claude", "codex", "opencode")):
                bad.append(f"{p.parent.name} -> {ref}")
    assert not bad, f"related_skills names nothing known: {bad}"


def test_no_crlf():
    """A CRLF shebang fails on Linux; a CRLF/LF pair makes sync report drift."""
    bad = [str(p.relative_to(REPO)) for p in REPO.rglob("*")
           if p.is_file() and p.suffix in (".md", ".sh", ".py", ".yaml", ".yml", ".json")
           and b"\r\n" in p.read_bytes()]
    assert not bad, f"CRLF found: {bad}"


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
