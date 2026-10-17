#!/usr/bin/env python3
"""Add a reviewer dimension to a writable framework tree, following the docs.

This is docs/EXTENDING.md "Add a reviewer (a dimension)" executed as code, so the
VM test can prove the acceptance claim rather than restate it: *a new reviewer can
be added following the docs alone*.

The five steps the doc names, in its order:

  1. the rubric       -> skills/reviewer-<dim>/SKILL.md
  2. the loop         -> council_loop.DIMENSION_SPEC and DEFAULT_GOALS
  3. the gate         -> score_reviews.STACK_TOOLS, GENERIC_TOOLS, WEIGHTS
  4. reinstall        -> `council setup bots`, done by the caller
  5. expect the weights to matter

Nothing here is special-cased for a dimension called "accessibility": it is the
dimension this test adds, and the anchors below are the LAST entry of each table,
which is where the doc tells a reader to add theirs.

Every anchor must be unique or the edit refuses to run. A silent no-op edit would
make the test pass while proving nothing, which is the failure mode this whole
exercise exists to avoid.
"""

from __future__ import annotations

import sys
from pathlib import Path

DIMENSION = "accessibility"
RUBRIC = "reviewer-accessibility"
PREFIX = "A11Y"


def insert_after(text: str, anchor: str, addition: str) -> str:
    """Insert `addition` after `anchor`, refusing anything ambiguous."""
    if text.count(anchor) != 1:
        raise SystemExit(
            f"anchor appears {text.count(anchor)} times, expected 1: {anchor!r}")
    return text.replace(anchor, anchor + addition)


def add_rubric(fw: Path) -> None:
    """Step 1: the rubric, modelled on the ones beside it."""
    path = fw / "skills" / RUBRIC / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        f"name: {RUBRIC}\n"
        "description: Score accessibility: keyboard reach, labels, contrast.\n"
        "---\n\n"
        f"# {DIMENSION.capitalize()} reviewer\n\n"
        "## What counts as a finding\n"
        "An interactive element a keyboard or screen-reader user cannot reach or\n"
        "identify: a control with no accessible name, a click target with no focus\n"
        "path, meaning carried by colour alone.\n\n"
        "## How to score it\n"
        "100 when every interactive element is reachable and labelled; each finding\n"
        "lowers it by severity, as every other dimension does.\n\n"
        "## Mandatory evidence\n"
        "The element, its file and line, and what the user cannot do. A claim about\n"
        "a screen reader must name the attribute that is missing.\n\n"
        "## What to refuse\n"
        "Stylistic preferences, and anything not visible in the reviewed diff.\n",
        encoding="utf-8",
    )


def register_in_loop(fw: Path) -> None:
    """Step 2: DIMENSION_SPEC and DEFAULT_GOALS. DIMENSIONS derives itself."""
    path = fw / "scripts" / "council_loop.py"
    text = path.read_text(encoding="utf-8")

    text = insert_after(
        text,
        '    "performance": {"rubric": "reviewer-performance", "prefix": "PERF"},\n',
        f'    "{DIMENSION}": {{"rubric": "{RUBRIC}", "prefix": "{PREFIX}"}},\n',
    )
    text = insert_after(
        text,
        '        "acceptance": "No open high/critical performance finding, and the timing probes "\n'
        '                      "show no regression.",\n'
        "    },\n",
        f'    "{DIMENSION}": {{\n'
        '        "objective": "No new barrier for a keyboard or screen-reader user.",\n'
        '        "acceptance": "Every interactive element is reachable and labelled, or the "\n'
        '                      "exception is recorded.",\n'
        "    },\n",
    )
    path.write_text(text, encoding="utf-8")


def register_in_gate(fw: Path) -> None:
    """Step 3: one STACK_TOOLS entry per stack, a GENERIC_TOOLS entry, a weight."""
    path = fw / "scripts" / "score_reviews.py"
    text = path.read_text(encoding="utf-8")

    # One entry per stack, even empty: STACK_TOOLS[dim][stack] is beta's denominator,
    # and an absent key and an empty list both mean "no deterministic tool here".
    stacks = ("python", "nix", "javascript", "rust", "go", "shell")
    entries = "".join(f'        "{s}": [],\n' for s in stacks)
    text = insert_after(
        text,
        '        "shell": ["declared-rules"],\n    },\n',
        f'    "{DIMENSION}": {{\n{entries}    }},\n',
    )
    text = insert_after(
        text,
        '    "architecture": [],\n',
        f'    "{DIMENSION}": [],\n',
    )

    # WEIGHTS must sum to 1.0, so a new dimension REBALANCES the others rather than
    # being appended. These are the doc's step 3 numbers, scaled by 0.93 + 0.07.
    old = (
        "WEIGHTS: Dict[str, float] = {\n"
        '    "security": 0.30,\n'
        '    "correctness": 0.25,\n'
        '    "readability": 0.20,\n'
        '    "architecture": 0.15,\n'
        '    "performance": 0.10,\n'
        "}\n"
    )
    new = (
        "WEIGHTS: Dict[str, float] = {\n"
        '    "security": 0.28,\n'
        '    "correctness": 0.23,\n'
        '    "readability": 0.19,\n'
        '    "architecture": 0.14,\n'
        '    "performance": 0.09,\n'
        f'    "{DIMENSION}": 0.07,\n'
        "}\n"
    )
    if text.count(old) != 1:
        raise SystemExit("WEIGHTS block not found verbatim")
    text = text.replace(old, new)
    path.write_text(text, encoding="utf-8")


def register_as_core_skill(fw: Path) -> None:
    """Step 4: name the rubric in CORE_SKILLS, which is what the installer reads.

    Not a glob. `EXTENDING.md` claimed the installer globbed `reviewer-*/SKILL.md`
    and needed no edit; it does not, and a dimension registered everywhere else but
    missing here is installed WITHOUT its rubric -- the reviewer then answers with
    no criteria and reports nothing, which looks like a quiet review rather than a
    misconfiguration. This step is in the test precisely because it is the one that
    fails silently.
    """
    path = fw / "scripts" / "council_config.py"
    text = path.read_text(encoding="utf-8")
    text = insert_after(
        text,
        'CORE_SKILLS: Dict[str, tuple] = {\n    "reviewer": (\n',
        f'        "{RUBRIC}",\n',
    )
    path.write_text(text, encoding="utf-8")


def verify(fw: Path) -> None:
    """Step 5's precondition, measured: the tables agree and the weights sum."""
    sys.path.insert(0, str(fw / "scripts"))
    import council_config as cfg          # noqa: PLC0415 - the edited copy, on purpose
    import council_loop as loop          # noqa: PLC0415
    import score_reviews as score        # noqa: PLC0415

    problems = []
    if DIMENSION not in loop.DIMENSIONS:
        problems.append(f"{DIMENSION} did not reach DIMENSIONS")
    if DIMENSION not in loop.DEFAULT_GOALS:
        problems.append(f"{DIMENSION} did not reach DEFAULT_GOALS")
    if DIMENSION not in score.STACK_TOOLS:
        problems.append(f"{DIMENSION} did not reach STACK_TOOLS")
    if DIMENSION not in score.GENERIC_TOOLS:
        problems.append(f"{DIMENSION} did not reach GENERIC_TOOLS")
    if DIMENSION not in score.WEIGHTS:
        problems.append(f"{DIMENSION} did not reach WEIGHTS")
    total = sum(score.WEIGHTS.values())
    if abs(total - 1.0) > 1e-9:
        problems.append(f"WEIGHTS sum to {total}, not 1.0")

    if RUBRIC not in cfg.CORE_SKILLS["reviewer"]:
        problems.append(
            f"{RUBRIC} is not in CORE_SKILLS['reviewer'], so the installer would "
            "never put it in the profile and the reviewer would answer with no rubric")

    # A dimension in the round but not in WEIGHTS is a KeyError in doctor, so the
    # two tables have to agree exactly rather than merely both mention the new name.
    missing = sorted(set(loop.DIMENSIONS) - set(score.WEIGHTS))
    if missing:
        problems.append(f"in DIMENSIONS but not WEIGHTS: {missing}")

    if problems:
        raise SystemExit("; ".join(problems))

    print(f"{len(loop.DIMENSIONS)} dimensions, WEIGHTS sum {total:.2f}: "
          + ", ".join(loop.DIMENSIONS))


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        raise SystemExit(f"usage: {argv[0]} <framework-root>")
    fw = Path(argv[1])
    if not (fw / "scripts" / "council_loop.py").is_file():
        raise SystemExit(f"not a framework tree: {fw}")
    add_rubric(fw)
    register_in_loop(fw)
    register_in_gate(fw)
    register_as_core_skill(fw)
    verify(fw)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
