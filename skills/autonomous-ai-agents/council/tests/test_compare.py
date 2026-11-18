"""Better/worse than before, decided by evidence — not by a score out of X.

Run standalone: python tests/test_compare.py
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
_spec = importlib.util.spec_from_file_location("compare", REPO / "scripts" / "compare.py")
compare_mod = importlib.util.module_from_spec(_spec)
sys.modules["compare"] = compare_mod
_spec.loader.exec_module(compare_mod)


def finding(key, severity="critical", state="confirmed", claim="a claim"):
    path, span, dimension = key.split(":", 2)
    return {"key": key, "path": path, "line_range": span, "dimension": dimension,
            "severity": severity, "state": state, "claim": claim}


def record(findings=(), probes=(("gitleaks", True, 0),)):
    return {"schema_version": 1,
            "findings": list(findings),
            "probes": [{"tool": t, "ran": r, "defects": d} for t, r, d in probes]}


def test_a_new_confirmed_critical_makes_it_worse():
    result = compare_mod.compare(
        record(),
        record([finding("a.py:4:security", claim="key committed")]))
    assert result["verdict"] == "worse", result
    assert result["regressions"][0]["key"] == "a.py:4:security"
    assert "key committed" in result["regressions"][0]["evidence"]


def test_a_resolved_finding_makes_it_better():
    result = compare_mod.compare(
        record([finding("a.py:4:security")]),
        record())
    assert result["verdict"] == "better", result
    assert result["resolutions"][0]["key"] == "a.py:4:security"


def test_nothing_changed_is_same():
    payload = record([finding("a.py:4:security")])
    assert compare_mod.compare(payload, payload)["verdict"] == "same"


def test_a_probe_that_starts_finding_defects_is_a_regression():
    result = compare_mod.compare(
        record(probes=(("bandit", True, 0),)),
        record(probes=(("bandit", True, 2),)))
    assert result["verdict"] == "worse", result
    assert result["regressions"][0]["kind"] == "probe"


def test_a_probe_that_stops_finding_defects_is_a_resolution():
    result = compare_mod.compare(
        record(probes=(("bandit", True, 2),)),
        record(probes=(("bandit", True, 0),)))
    assert result["verdict"] == "better", result


def test_an_analyzer_that_did_not_run_is_incomparable_not_an_improvement():
    """Measured class of error: a missing tool finds nothing, and 'nothing' reads as better."""
    result = compare_mod.compare(
        record([finding("a.py:4:security")], probes=(("gitleaks", True, 1), ("bandit", True, 1))),
        record([], probes=(("bandit", True, 0),)))
    assert result["verdict"] == "incomparable", result
    assert "gitleaks" in result["reasons"][0]


def test_a_medium_finding_alone_does_not_make_it_worse():
    """Only what would block decides 'worse'; a nit is not a regression."""
    result = compare_mod.compare(record(), record([finding("a.py:9:readability",
                                                           severity="low")]))
    assert result["verdict"] == "same", result


def test_there_is_no_threshold_and_no_score_in_the_verdict():
    payload = compare_mod.compare(record(), record([finding("a.py:4:security")]))
    assert "threshold" not in payload
    assert not any(isinstance(v, float) for v in payload.values()), payload
    source = (REPO / "scripts" / "compare.py").read_text(encoding="utf-8")
    # Prose may name the thing this module does not have; a constant or a comparison may not.
    assert "THRESHOLD" not in source, "a magic number constant crept into the comparison"
    assert "threshold=" not in source, "a threshold parameter crept into the comparison"
    assert "87.11" not in source, "the old magic number is back"


def test_a_different_record_version_is_incomparable():
    old = record()
    old["schema_version"] = 0
    assert compare_mod.compare(old, record())["verdict"] == "incomparable"


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
