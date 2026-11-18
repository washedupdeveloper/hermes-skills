"""A proof about one file cannot confirm a finding about another.

Measured on the nine-run corpus: a finding about a committed key in `src/svc/__init__.py:4` carried
a `present` proof over `src/svc/client.py:9`, and adjudication confirmed it — the check passed and
its control failed, so nothing noticed the two were about different files.

Run standalone: python tests/test_adjudicate_place.py
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
_spec = importlib.util.spec_from_file_location("adjudicate", REPO / "scripts" / "adjudicate.py")
adjudicate = importlib.util.module_from_spec(_spec)
sys.modules["adjudicate"] = adjudicate
_spec.loader.exec_module(adjudicate)


def test_a_proof_for_a_different_file_is_rejected():
    proof = {"kind": "present", "params": {"path": "src/svc/client.py", "line": 9, "text": "x"}}
    ok, why = adjudicate._proves_the_claimed_place(
        proof, {"path": "src/svc/__init__.py", "line_range": "4"})
    assert ok is False, "a proof about another file was accepted"
    assert "client.py" in why and "__init__.py" in why, why


def test_the_same_file_under_a_different_spelling_is_accepted():
    for spelling in ("a.py", "./a.py"):
        proof = {"kind": "present", "params": {"path": spelling, "line": 1, "text": "x"}}
        ok, why = adjudicate._proves_the_claimed_place(proof, {"path": "a.py"})
        assert ok is True, f"{spelling} was rejected: {why}"


def test_a_path_that_escapes_the_tree_is_not_normalised_into_a_match():
    """`lstrip('./')` would turn `../a.py` into `a.py` and accept a proof from outside the repo."""
    ok, _ = adjudicate._proves_the_claimed_place(
        {"kind": "present", "params": {"path": "../a.py"}}, {"path": "a.py"})
    assert ok is False


def test_an_absence_proof_that_excludes_the_claimed_file_proves_nothing_about_it():
    """Measured: three complexity claims were confirmed by `absent` proofs whose exclude named
    the very file claimed — evidence that cannot observe the thing it was said to establish."""
    proof = {"kind": "absent",
             "params": {"pattern": "classify_0", "include": ["**/*.py"],
                        "exclude": ["src/svc/report.py"]}}
    ok, why = adjudicate._proves_the_claimed_place(
        proof, {"path": "src/svc/report.py", "line_range": "8-33"})
    assert ok is False, "an excluding proof was accepted for the excluded file"
    assert "excludes" in why and "report.py" in why, why


def test_an_absence_proof_that_covers_the_claimed_file_is_accepted():
    proof = {"kind": "absent",
             "params": {"pattern": "classify_0", "include": ["**/*.py"],
                        "exclude": ["src/svc/other.py"]}}
    ok, why = adjudicate._proves_the_claimed_place(
        proof, {"path": "src/svc/report.py"})
    assert ok is True, why


def test_an_include_that_does_not_cover_the_claim_is_rejected():
    proof = {"kind": "absent", "params": {"pattern": "x", "include": ["tests/*.py"]}}
    ok, why = adjudicate._proves_the_claimed_place(proof, {"path": "src/app.py"})
    assert ok is False, why
    assert "include" in why, why


def test_a_proof_without_a_path_is_left_to_its_control():
    """`command` proofs run over the whole tree; the control is what catches a vacuous check."""
    ok, _ = adjudicate._proves_the_claimed_place(
        {"kind": "command", "params": {"argv": ["true"]}}, {"path": "a.py"})
    assert ok is True


def test_a_missing_repo_cannot_replace_a_good_adjudication():
    """Measured: a diagnostic `--repo` that did not exist wrote an all-unrunnable report over a
    round with four confirmed claims. The tree is a precondition, so nothing is written."""
    import json
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        round_dir = root / "run" / "round-1"
        round_dir.mkdir(parents=True)
        (round_dir / "meta.json").write_text(
            json.dumps({"repo": str(root / "tree"), "stacks": ["generic"]}), encoding="utf-8")
        (round_dir / "security.json").write_text(
            json.dumps({"findings": [{"id": "S-1", "dimension": "security", "severity": "high",
                                      "status": "open",
                                      "location": {"path": "a.py", "line_range": "1"}}]}),
            encoding="utf-8")
        before = json.dumps({"findings": [{"id": "S-1", "state": "confirmed"}]})
        (round_dir / "proofs.json").write_text(before, encoding="utf-8")
        try:
            adjudicate.adjudicate_round(round_dir, root / "does-not-exist")
        except FileNotFoundError as exc:
            assert "does not exist" in str(exc), exc
        else:
            raise AssertionError("a missing repository did not raise")
        after = (round_dir / "proofs.json").read_text(encoding="utf-8")
    assert after == before, "the existing adjudication was overwritten"


def test_a_finding_without_a_location_is_not_demoted():
    ok, _ = adjudicate._proves_the_claimed_place(
        {"kind": "present", "params": {"path": "a.py"}}, {})
    assert ok is True


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
