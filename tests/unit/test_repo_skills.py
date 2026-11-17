#!/usr/bin/env python3
"""One check that needs the shipped curation script, not the gate.

The tree rules — dead references, fenced commands, `related_skills` — moved to
`scripts/validate.py`, which owns them for every host. A second implementation here
was a second answer to one question.

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


def test_the_routing_bench_scores_only_what_the_prompt_shows():
    """Hermes lists a skill to the model as `name: description`.

    The bench once scored `metadata.hermes.tags` too — a field the loader reads
    nowhere — and reported twice the effect size: held-out 0.57 -> 0.63 became
    0.43 -> 0.47 once the tags were removed.
    """
    src = (SKILLS / "software-development/skill-library-curation/scripts/skill-bench.py").read_text(
        encoding="utf-8")
    assert "tags.group" not in src, "the bench is scoring metadata the loader never reads"
    assert "fm.get('description', '')" in src, "the description must be in the scored blob"


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
