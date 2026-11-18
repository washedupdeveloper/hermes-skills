"""The diff model, shared by both parsers.

One generator, two implementations: v1's `parse_diff` and reviewc's `_line_in_diff` are measured
against the same oracle, so a disagreement is a disagreement about the code and not about the fixture.

The model is built *while* the text is emitted, independently of either parser: for every content line
we record what it means, and the parsers have to agree with the record.

Deterministic by construction — a fixed seed and a fixed number of cases. No `hypothesis` dependency:
the toolchain is pinned, and a test that needs an unpinned package is a test that fails on a machine
that never runs it.
"""
from __future__ import annotations

import random
from typing import Set, Tuple

CASES = 400
SEED = 20261106


def build_diff(rng: random.Random) -> Tuple[str, Set[int], Set[int]]:
    """A synthetic `git diff` and the line sets it must produce."""
    lines = ["diff --git a/f.py b/f.py", "--- a/f.py", "+++ b/f.py"]
    added, removed = set(), set()
    old_cursor = rng.randint(1, 5)
    new_cursor = old_cursor
    for _ in range(rng.randint(0, 5)):
        old_start, new_start = old_cursor, new_cursor
        body = []
        for _ in range(rng.randint(1, 6)):
            kind = rng.choice(["context", "add", "remove"])
            if kind == "context":
                # A context line occupies a line on BOTH sides. Getting this wrong in the model
                # is the mirror of getting it wrong in the parser, so it is stated explicitly.
                body.append((kind, " line"))
                old_cursor += 1
                new_cursor += 1
            elif kind == "add":
                added.add(new_cursor)
                body.append((kind, "+new"))
                new_cursor += 1
            else:
                removed.add(old_cursor)
                body.append((kind, "-old"))
                old_cursor += 1
        old_count = sum(1 for kind, _ in body if kind != "add")
        new_count = sum(1 for kind, _ in body if kind != "remove")
        # unified=0 with a zero-length side elides the count; emit both shapes on purpose.
        old_part = f"-{old_start},{old_count}" if old_count else f"-{old_start},0"
        new_part = f"+{new_start},{new_count}" if new_count else f"+{new_start},0"
        lines.append(f"@@ {old_part} {new_part} @@")
        lines.extend(text for _, text in body)
        old_cursor, new_cursor = old_cursor + 1, new_cursor + 1
    return "\n".join(lines) + "\n", added, removed
