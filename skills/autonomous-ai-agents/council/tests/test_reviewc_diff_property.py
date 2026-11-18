"""The rewrite's diff parser, measured against the same model as v1's.

`tests/test_diff_property.py` proves v1's `parse_diff` against a generated oracle. This proves
`reviewc.proofs._line_in_diff` against the *same* oracle — one generator, two parsers — so the two can
be compared and neither can be excused by a fixture that suits it.

`_line_in_diff` answers one question ("was this line added/removed?") rather than returning sets, so the
equivalence is checked line by line over a range that covers the whole diff.

Run standalone: python tests/test_reviewc_diff_property.py
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))

from diff_model import CASES, SEED, build_diff  # noqa: E402

from reviewc import proofs  # noqa: E402


def verdict(text: str, line: int, mode: str) -> bool:
    return proofs._line_in_diff(text, line, mode)[0]


def test_generated_diffs_agree_with_the_model_line_by_line():
    rng = random.Random(SEED)
    for case in range(CASES):
        text, added, removed = build_diff(rng)
        highest = max(added | removed, default=0) + 2
        for line in range(0, highest + 1):
            got_added = verdict(text, line, "added")
            got_removed = verdict(text, line, "removed")
            assert got_added == (line in added), \
                f"case {case}, line {line}: added={got_added}, model says {line in added}\n{text}"
            assert got_removed == (line in removed), \
                f"case {case}, line {line}: removed={got_removed}, model says {line in removed}\n{text}"


def test_a_content_line_beginning_with_plus_is_not_a_file_header():
    """`++foo` in the new file appears as `+++foo` in the patch. Prefix-skipping loses it."""
    text = "@@ -0,0 +1,1 @@\n+++foo\n"
    assert verdict(text, 1, "added") is True
    assert proofs._line_in_diff(text, 1, "added")[1].startswith("line 1 is added")


def test_a_content_line_beginning_with_minus_is_not_a_file_header():
    text = "@@ -1,1 +0,0 @@\n---bar\n"
    assert verdict(text, 1, "removed") is True


def test_the_no_newline_marker_occupies_neither_side():
    text = "@@ -1,1 +1,1 @@\n keep\n-old\n\\ No newline at end of file\n+new\n"
    assert verdict(text, 2, "added") is True
    assert verdict(text, 3, "added") is False


def test_file_headers_are_not_content():
    text = "diff --git a/f.py b/f.py\n--- a/f.py\n+++ b/f.py\n@@ -1,0 +1,1 @@\n+first\n"
    assert verdict(text, 1, "added") is True
    assert verdict(text, 2, "added") is False


def test_two_hunks_both_count():
    text = "@@ -1,0 +1,1 @@\n+one\n@@ -20,0 +21,1 @@\n+twenty-one\n"
    assert verdict(text, 1, "added") is True
    assert verdict(text, 21, "added") is True


def test_content_outside_any_hunk_invents_no_line_number():
    """v1 answers `{0}` here. Line 0 is not a line, so the rewrite reports no change and says so.

    This is a deliberate divergence in the parser, recorded rather than copied: a claimed line 0 would
    make `diff` proofs about line 0 look supportable.
    """
    text = "@@ nonsense @@\n+x\n"
    assert verdict(text, 0, "added") is False


if __name__ == "__main__":
    failures = 0
    names = [n for n in sorted(globals()) if n.startswith("test_")]
    for name in names:
        try:
            globals()[name]()
            print(f"ok   {name}")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL {name}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"FAIL {name}: {type(exc).__name__}: {exc}")
    print(f"\n{len(names) - failures} passed, {failures} failed")
    raise SystemExit(1 if failures else 0)
