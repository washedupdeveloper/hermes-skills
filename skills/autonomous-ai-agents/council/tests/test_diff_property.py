"""Property test for the diff parser: generated diffs in, exact line sets out.

The plan asks for this because the parser has already shipped a bug no test caught — a per-hunk
flag kept only the last hunk's answer, so every genuine change above it was refuted. Example tests
could not see it; a model can.

Deterministic by construction: a fixed seed and a fixed number of cases. No `hypothesis` dependency,
because the toolchain is pinned and a test that needs an unpinned package is a test that fails on a
machine that never runs it.

Run standalone: python tests/test_diff_property.py
"""
from __future__ import annotations

import importlib.util
import random
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))
_spec = importlib.util.spec_from_file_location("proofs", REPO / "scripts" / "proofs.py")
proofs = importlib.util.module_from_spec(_spec)
sys.modules["proofs"] = proofs
_spec.loader.exec_module(proofs)

# The oracle lives in one place, so v1's parser and reviewc's are measured against the same model
# rather than against two copies that could drift apart.
from diff_model import CASES, SEED, build_diff  # noqa: E402


def test_generated_diffs_agree_with_the_model():
    rng = random.Random(SEED)
    for case in range(CASES):
        text, added, removed = build_diff(rng)
        got_added, got_removed = proofs.parse_diff(text)
        assert got_added == added, f"case {case}: added {sorted(got_added)} != {sorted(added)}\n{text}"
        assert got_removed == removed, \
            f"case {case}: removed {sorted(got_removed)} != {sorted(removed)}\n{text}"


def test_file_headers_are_not_content():
    text = ("--- a/f.py\n+++ b/f.py\n@@ -1,0 +1,1 @@\n+first\n")
    added, removed = proofs.parse_diff(text)
    assert added == {1} and removed == set(), (added, removed)


def test_context_lines_advance_both_sides():
    text = "@@ -10,3 +10,3 @@\n keep\n-old\n+new\n"
    added, removed = proofs.parse_diff(text)
    assert added == {11} and removed == {11}, (added, removed)


def test_a_malformed_header_does_not_reset_the_cursor_silently():
    """An unparseable `@@` line is skipped, and the diff keeps counting from where it was."""
    text = "@@ nonsense @@\n+x\n"
    added, _ = proofs.parse_diff(text)
    assert added == {0}, added


def test_two_hunks_both_count():
    """The exact bug the plan records: the first hunk's answer must survive the second header."""
    text = ("@@ -1,0 +1,1 @@\n+one\n@@ -20,0 +21,1 @@\n+twenty-one\n")
    added, _ = proofs.parse_diff(text)
    assert added == {1, 21}, added


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
