"""Tests for metrics.py — the interactive metrics, and the promise not to invent them.

Run standalone (no pytest needed):
    python tests/test_metrics.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
_spec = importlib.util.spec_from_file_location("metrics", REPO / "scripts" / "metrics.py")
metrics = importlib.util.module_from_spec(_spec)
sys.modules["metrics"] = metrics
_spec.loader.exec_module(metrics)

DIMS = metrics.dimensions()


def _run(root: Path, *, statuses, iterations=None, dim="security"):
    """One run directory: a dimension file with findings, and optionally outcome.json."""
    run = root / "run-1"
    run.mkdir(parents=True, exist_ok=True)
    findings = [
        {"id": f"SEC-{i:04d}", "dimension": dim, "severity": "high", "status": status,
         "location": {"path": "a.nix", "line_range": str(i)},
         "claim": f"claim {i}", "falsifiable_check": "check"}
        for i, status in enumerate(statuses, start=1)
    ]
    (run / f"{dim}.json").write_text(
        json.dumps({"dimension": dim, "findings": findings, "score": 50.0}), encoding="utf-8")
    if iterations is not None:
        (run / "outcome.json").write_text(
            json.dumps({"outcome": "satisfied", "scores": [50.0] * iterations}),
            encoding="utf-8")
    return run


# --- the promise: no data is not a zero --------------------------------------

def test_with_no_judged_findings_the_rates_are_null_not_zero():
    """`null` and `0.0` read identically in a table, and mean opposite things.

    This is the whole reason the module exists: the milestone refuses an invented
    number, so an unjudged run must report `no data`.
    """
    with tempfile.TemporaryDirectory() as td:
        run = _run(Path(td), statuses=["open", "open"])
        result = metrics.summarise([run], DIMS)

        assert result["acceptance_rate"] is None, result["acceptance_rate"]
        assert result["addressed_rate"] is None, result["addressed_rate"]
        assert result["judged"] == 0
        assert result["findings"] == 2
        assert result["missing"], "an unjudged run must say what is missing"


def test_the_missing_note_names_the_field_and_the_values():
    """A reader who does not know the schema must be told what to write."""
    with tempfile.TemporaryDirectory() as td:
        run = _run(Path(td), statuses=["open"])
        note = " ".join(metrics.summarise([run], DIMS)["missing"])
        for expected in ("status", "accepted", "fixed", "wontfix", "rejected"):
            assert expected in note, f"{expected!r} not named in: {note}"


def test_an_empty_run_reports_no_rate_rather_than_divide_by_zero():
    with tempfile.TemporaryDirectory() as td:
        run = Path(td) / "empty"
        run.mkdir()
        result = metrics.summarise([run], DIMS)
        assert result["acceptance_rate"] is None
        assert result["coverage"] is None, "no findings means no coverage to state"


# --- the mapping -------------------------------------------------------------

def test_the_four_judgements_map_to_accepted_and_addressed():
    """accepted / fixed / wontfix are all `real`; only `fixed` moved code."""
    with tempfile.TemporaryDirectory() as td:
        run = _run(Path(td), statuses=["accepted", "fixed", "wontfix", "rejected"])
        r = metrics.summarise([run], DIMS)

        assert r["judged"] == 4
        assert r["accepted"] == 3, "accepted, fixed and wontfix are all judged real"
        assert r["addressed"] == 1, "only `fixed` means the code changed"
        assert r["rejected"] == 1
        assert r["acceptance_rate"] == 0.75
        assert r["addressed_rate"] == 0.25


def test_pending_findings_do_not_drag_the_rate_down():
    """An unjudged finding is not a rejection, so it must not enter the denominator."""
    with tempfile.TemporaryDirectory() as td:
        run = _run(Path(td), statuses=["fixed", "open", "open"])
        r = metrics.summarise([run], DIMS)

        assert r["judged"] == 1
        assert r["acceptance_rate"] == 1.0, "one judged, one accepted"
        assert r["coverage"] == 1 / 3


def test_status_is_case_and_space_insensitive():
    with tempfile.TemporaryDirectory() as td:
        run = _run(Path(td), statuses=[" Fixed ", "ACCEPTED"])
        r = metrics.summarise([run], DIMS)
        assert r["accepted"] == 2, r
        assert r["addressed"] == 1, r


def test_an_unknown_status_is_reported_and_never_counted_as_a_rejection():
    """A typo must not silently become a false positive against the reviewer."""
    with tempfile.TemporaryDirectory() as td:
        run = _run(Path(td), statuses=["fixed", "resolved"])
        r = metrics.summarise([run], DIMS)

        assert r["rejected"] == 0, "`resolved` is not a rejection, it is a typo"
        assert r["unknown_statuses"] == {"resolved": 1}, r.get("unknown_statuses")
        assert any("resolved" in p for p in r["problems"]), r.get("problems")


def test_an_empty_status_counts_as_pending_not_unknown():
    with tempfile.TemporaryDirectory() as td:
        run = _run(Path(td), statuses=[""])
        r = metrics.summarise([run], DIMS)
        assert r["pending"] == 1
        assert "unknown_statuses" in r, "an absent status is still worth naming"


# --- iterations need no operator ---------------------------------------------

def test_iterations_come_from_the_outcome_file_the_loop_already_writes():
    """M8 assumed all three metrics needed an operator. This one never did."""
    with tempfile.TemporaryDirectory() as td:
        run = _run(Path(td), statuses=["open"], iterations=3)
        r = metrics.summarise([run], DIMS)
        assert r["iterations"]["per_run"] == [3]
        assert r["iterations"]["mean"] == 3.0
        assert not any("iteration" in m for m in r["missing"]), r["missing"]


def test_iterations_mean_across_runs():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        a = _run(root, statuses=["open"], iterations=2)
        b = root / "run-2"
        b.mkdir()
        (b / "security.json").write_text(json.dumps({"findings": []}), encoding="utf-8")
        (b / "outcome.json").write_text(json.dumps({"scores": [1.0] * 4}), encoding="utf-8")
        r = metrics.summarise([a, b], DIMS)
        assert r["iterations"]["per_run"] == [2, 4]
        assert r["iterations"]["mean"] == 3.0


def test_a_run_without_an_outcome_file_contributes_no_iteration():
    """None, not 0: a run that never terminated has no iteration count."""
    with tempfile.TemporaryDirectory() as td:
        run = _run(Path(td), statuses=["open"])
        r = metrics.summarise([run], DIMS)
        assert r["iterations"]["per_run"] == []
        assert r["iterations"]["mean"] is None
        assert any("iteration" in m for m in r["missing"]), r["missing"]


# --- reading a real run directory --------------------------------------------

def test_a_missing_dimension_file_is_not_an_error():
    """A partial run is legitimate; only an unreadable file is a problem."""
    with tempfile.TemporaryDirectory() as td:
        run = _run(Path(td), statuses=["fixed"], dim="security")
        r = metrics.summarise([run], DIMS)
        assert r["findings"] == 1
        assert not r.get("problems"), r.get("problems")


def test_a_corrupt_dimension_file_is_reported_not_skipped_silently():
    with tempfile.TemporaryDirectory() as td:
        run = _run(Path(td), statuses=["fixed"])
        (run / "correctness.json").write_text("{not json", encoding="utf-8")
        r = metrics.summarise([run], DIMS)
        assert any("correctness.json" in p for p in r["problems"]), r.get("problems")
        assert r["findings"] == 1, "the readable file still counts"


def test_rendering_says_no_data_rather_than_a_dash():
    with tempfile.TemporaryDirectory() as td:
        run = _run(Path(td), statuses=["open"])
        text = "\n".join(metrics.render(metrics.summarise([run], DIMS)))
        assert "no data" in text, text
        assert "acceptance rate no data" in text, text


# --- the exit code -----------------------------------------------------------

def test_unknown_status_exits_nonzero_but_no_data_exits_zero():
    """`no data` is an answer; a malformed record is a mistake."""
    with tempfile.TemporaryDirectory() as td:
        clean = _run(Path(td), statuses=["open"], iterations=1)
        assert metrics.main([str(clean), "--json"]) == 0

        root = Path(td) / "typo"
        root.mkdir()
        bad = _run(root, statuses=["resolved"], iterations=1)
        assert metrics.main([str(bad), "--json"]) == 1


def main() -> int:
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    passed = failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS {name}")
            passed += 1
        except AssertionError as exc:
            print(f"  FAIL {name} -> {exc}")
            failed += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  ERROR {name} -> {type(exc).__name__}: {exc}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
