#!/usr/bin/env python3
"""Contract tests for the skills this repo ships.

Standalone — no pytest required:

    python3 tests/unit/test_repo_skills.py

Every check here was a hand-run command before it was a test. The properties are
the ones that have actually broken in this repo: a reference file that was
promised and never written, a skill that shadows the repo from the live library.

WHAT MOVED TO NIX. Four tests that used to live here are now eval-tier
assertions in `nix/tests.nix`, because they are pure functions of the tree and
Nix names the skill, the field and both values when they fail:

    test_frontmatter_is_complete            -> test_every_skill_declares_the_required_fields
    test_description_fits_the_index_window  -> test_every_description_fits_the_index_window
    test_name_matches_directory             -> test_the_name_matches_its_directory
    test_no_crlf                            -> test_no_text_file_carries_crlf

They were removed rather than duplicated: one property, one owner. What stays is
what needs a real regex engine or a subprocess — the pointer heuristic below and
the prose claims in `test_docs.py`. Run `nix flake check` for the whole gate.
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
SKILLS = REPO / "skills"
SUPPORT = ("references", "templates", "assets", "scripts")


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


def test_no_dead_references():
    """A promised reference file that does not exist is a broken pointer.

    Only POINTERS are checked — a path the reader is meant to follow. A path in
    a prescriptive sentence ("Write the installer (`scripts/x.sh`)") names a file
    to CREATE, not one that exists, so flagging it would be wrong. Same for a
    placeholder (`references/<topic>.md`).

    A pointer that climbs OUT of the skill directory is broken too, even when the
    target exists in the repo: Hermes resolves a skill's paths relative to the
    skill's own directory, so `../../scripts/x.py` works from a checkout and
    dangles from anywhere the skill is read on its own.
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
            for m in re.finditer(r"`(\.\./[^`\s]+)`", line):
                if write_verbs.search(line):
                    continue
                bad.append(f"{p.parent.name} -> {m.group(1)} (escapes the skill dir)")
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


def test_no_dead_paths_in_fenced_commands():
    """A fenced command that runs a script this skill ships must find it.

    `test_no_dead_references` reads inline spans only, and that is not where the
    bug lived: a retired `scripts/install-bots.sh` sat in a fenced block and
    survived three audits of this file. Only paths into a directory the skill
    itself ships are checked — a `scripts/x.py` in a skill with no `scripts/`
    belongs to some other repository, and cannot be verified from here.
    """
    write_verbs = re.compile(r"\b(write|create|add|author|generate|scaffold|produce)\b", re.I)
    local = re.compile(r"\b((?:scripts|references|templates|assets)/[\w./-]+\.\w+)")
    fence = re.compile(r"```[a-zA-Z]*\n(.*?)```", re.S)
    bad = []
    for p in sorted(SKILLS.rglob("*.md")):
        if "__pycache__" in p.parts:
            continue
        d = p.parent if p.name == "SKILL.md" else next(
            (a for a in p.parents if (a / "SKILL.md").is_file()), p.parent)
        for block in fence.findall(p.read_text(encoding="utf-8", errors="replace")):
            for raw in block.splitlines():
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if any(c in line for c in "<>$") or write_verbs.search(line):
                    continue
                for ref in local.findall(line):
                    if not (d / ref.split("/", 1)[0]).is_dir():
                        continue
                    if not (d / ref).exists():
                        bad.append(f"{p.relative_to(SKILLS)} -> {ref}")
    assert not bad, f"dead paths in fenced commands: {bad}"


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
