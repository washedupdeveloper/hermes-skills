"""The proof engine: the contract, the three outcomes, and a self-test that can fail.

Run standalone: python tests/test_proofs_reviewc.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from reviewc import proofs  # noqa: E402


def tree(tmp: Path) -> Path:
    (tmp / "a.py").write_text("def helper():\n    return 1\n", encoding="utf-8")
    (tmp / "data.json").write_text('{"a": {"b": [1, 2]}}', encoding="utf-8")
    return tmp


# --- the contract -------------------------------------------------------------------

def test_the_vocabulary_is_read_from_the_protocol_file():
    declared = proofs.kinds()
    assert set(declared) == {"absent", "present", "command", "json", "diff", "dom", "http"}
    assert set(proofs.EXECUTORS) == set(declared), "an executor exists for a kind the spec lacks"


def test_an_unknown_kind_is_refused():
    try:
        proofs.check({"kind": "vibes", "params": {}})
    except proofs.ProofError as exc:
        assert "unknown proof kind" in str(exc)
    else:
        raise AssertionError("an undeclared kind was accepted")


def test_a_missing_required_param_is_refused():
    try:
        proofs.check({"kind": "present", "params": {"path": "a.py"}})
    except proofs.ProofError as exc:
        assert "missing required param" in str(exc)
    else:
        raise AssertionError("a proof without its required params was accepted")


def test_an_undeclared_param_is_refused():
    """A typo in a param name would otherwise be silently ignored and the proof would pass."""
    try:
        proofs.check({"kind": "present", "params": {"path": "a.py", "line": 1, "text": "x",
                                                    "txt": "y"}})
    except proofs.ProofError as exc:
        assert "unknown param" in str(exc)
    else:
        raise AssertionError("an undeclared param was accepted")


def test_a_path_that_escapes_the_tree_is_refused():
    with tempfile.TemporaryDirectory() as tmp:
        root = tree(Path(tmp))
        try:
            proofs.evaluate({"kind": "present", "params": {"path": "../../etc/passwd", "line": 1,
                                                           "text": "root"}}, proofs.Context(root))
        except proofs.ProofError as exc:
            assert "outside the tree" in str(exc)
        else:
            raise AssertionError("a proof read outside its tree")


# --- the three outcomes -------------------------------------------------------------

def test_not_exercised_is_not_the_same_as_not_observed():
    with tempfile.TemporaryDirectory() as tmp:
        root = tree(Path(tmp))
        missing = proofs.evaluate({"kind": "command",
                                   "params": {"argv": ["definitely-not-a-binary-xyz"],
                                              "expect": {"exit": "zero"}}}, proofs.Context(root))
        wrong = proofs.evaluate({"kind": "present", "params": {"path": "a.py", "line": 1,
                                                               "text": "nope"}},
                                proofs.Context(root))
    assert missing.ok is None and missing.word == "not exercised"
    assert wrong.ok is False and wrong.word == "not observed"


def test_a_missing_file_is_not_observed_not_unrunnable():
    with tempfile.TemporaryDirectory() as tmp:
        root = tree(Path(tmp))
        got = proofs.evaluate({"kind": "present", "params": {"path": "nope.py", "line": 1,
                                                             "text": "x"}}, proofs.Context(root))
    assert got.ok is False


def test_absent_reports_unrunnable_above_max_files():
    with tempfile.TemporaryDirectory() as tmp:
        root = tree(Path(tmp))
        got = proofs.evaluate({"kind": "absent", "params": {"pattern": "helper", "max_files": 1}},
                              proofs.Context(root))
    assert got.ok is None, got.detail
    assert "max_files" in got.detail


def test_diff_without_a_base_is_not_exercised():
    with tempfile.TemporaryDirectory() as tmp:
        root = tree(Path(tmp))
        got = proofs.evaluate({"kind": "diff", "params": {"path": "a.py", "line": 1}},
                              proofs.Context(root))
    assert got.ok is None
    assert "base revision" in got.detail


def test_http_refuses_a_non_loopback_host():
    with tempfile.TemporaryDirectory() as tmp:
        got = proofs.evaluate({"kind": "http", "params": {"url": "https://example.com/"}},
                              proofs.Context(tree(Path(tmp))))
    assert got.ok is None
    assert "loopback" in got.detail


def test_json_pointer_escapes_are_honoured():
    with tempfile.TemporaryDirectory() as tmp:
        root = tree(Path(tmp))
        (root / "esc.json").write_text('{"a/b": 1, "c~d": 2}', encoding="utf-8")
        slash = proofs.evaluate({"kind": "json", "params": {"path": "esc.json",
                                                            "pointer": "/a~1b", "equals": 1}},
                                proofs.Context(root))
        tilde = proofs.evaluate({"kind": "json", "params": {"path": "esc.json",
                                                            "pointer": "/c~0d", "equals": 2}},
                                proofs.Context(root))
    assert slash.ok is True and tilde.ok is True


def test_json_absent_is_the_inverse_of_present():
    with tempfile.TemporaryDirectory() as tmp:
        root = tree(Path(tmp))
        gone = proofs.evaluate({"kind": "json", "params": {"path": "data.json",
                                                           "pointer": "/a/missing", "absent": True}},
                               proofs.Context(root))
        there = proofs.evaluate({"kind": "json", "params": {"path": "data.json",
                                                            "pointer": "/a/b", "absent": True}},
                                proofs.Context(root))
    assert gone.ok is True and there.ok is False


# --- the self-test ------------------------------------------------------------------

def test_the_self_test_covers_every_kind_in_both_directions():
    cases, failures = proofs.self_test()
    assert not failures, [c["case"] for c in failures]
    covered = {}
    for case in cases:
        if isinstance(case["want"], bool):
            covered.setdefault(case["kind"], set()).add(case["want"])
    for kind in proofs.EXECUTORS:
        assert covered.get(kind) == {True, False}, f"{kind} is not exercised both ways: {covered.get(kind)}"


def test_the_self_test_exits_three_when_a_lane_cannot_run():
    """On a host with no browser the dom lane is not exercised, and that is not a pass."""
    cases, _ = proofs.self_test()
    skipped = [c for c in cases if c.get("skipped")]
    if proofs.browser_driver():
        assert not skipped, "a browser is present, so nothing should be skipped"
        assert proofs.self_test_exit(cases) == 0
    else:
        assert len(skipped) == 2, [c["case"] for c in skipped]
        assert proofs.self_test_exit(cases) == 3


def test_the_self_test_names_the_same_cases_as_v1():
    """The differential needs the same list, or the two runs are not comparable."""
    cases, _ = proofs.self_test()
    names = {c["case"] for c in cases}
    for expected in ("absent finds the symbol", "present refuses a wrong citation",
                     "command refutes a failure that did not happen", "json catches a wrong value",
                     "http sees a local server answer", "dom finds a rendered element",
                     "diff sees an addition in the FIRST hunk",
                     "diff refutes a removal that did not happen"):
        assert expected in names, expected


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
