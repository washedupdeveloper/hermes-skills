"""Tests for calibrate.py's pure logic and the calibrated density scorer (M8).

Run standalone (no pytest needed):
    python tests/test_calibration.py
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    assert spec is not None and spec.loader is not None, rel
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cal = _load("calibrate", "scripts/calibrate.py")
score = _load("score_reviews", "scripts/score_reviews.py")


# --- the Hill curve ---------------------------------------------------------

def test_hill_returns_100_at_or_below_zero():
    """No findings is a clean bill of health, not a division by zero."""
    assert cal.hill(0.0, 1.9) == 100.0
    assert cal.hill(-1.0, 1.9) == 100.0


def test_hill_scores_50_at_d_star():
    """§7 defines d* as the density at which the term scores 50 — by definition,
    so this is the property the whole calibration rests on."""
    assert abs(cal.hill(1.8921, 1.8921) - 50.0) < 0.01


def test_hill_is_monotone_decreasing():
    vals = [cal.hill(d, 1.8921) for d in (0.1, 0.5, 1.0, 2.0, 4.0, 8.0)]
    assert all(a > b for a, b in zip(vals, vals[1:])), vals


# --- d* derivation ----------------------------------------------------------

def test_d_star_is_the_known_good_density():
    d = cal.derive_d_star({"ruff": 2.0, "bandit": 0.5}, {"ruff": 8.0, "bandit": 4.0})
    assert d["ruff"]["d_star"] == 2.0
    assert d["bandit"]["d_star"] == 0.5


def test_d_star_is_floored_when_the_baseline_is_clean():
    """A tool that finds nothing on known-good code has d* = 0, which collapses
    the curve to a step at the origin. Floor it and SAY SO, so the manifest
    records that the value is a floor rather than a measurement."""
    d = cal.derive_d_star({"secret-grep": 0.0}, {"secret-grep": 3.0})
    assert d["secret-grep"]["d_star"] == cal.DENSITY_FLOOR
    assert d["secret-grep"]["floored"] is True


def test_tool_absent_from_the_good_baseline_is_skipped():
    """No known-good reading means no reference point — omit it rather than
    inventing one from the bad baseline."""
    d = cal.derive_d_star({"ruff": 1.0}, {"ruff": 5.0, "nosuch": 9.0})
    assert "nosuch" not in d


# --- density measurement ----------------------------------------------------

def test_probe_density_excludes_probes_that_did_not_run():
    """A tool that did not run must contribute NO key. Recording it as 0.0 would
    read as 'clean', which is exactly how a missing analyzer becomes a passing
    grade."""
    results = [
        {"tool": "ruff", "ran": True, "findings": [1, 2, 3, 4, 5]},
        {"tool": "bandit", "ran": False, "findings": []},
        {"tool": "gitleaks", "ran": True, "findings": []},
    ]
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "a.py").write_text("\n".join("x = 1" for _ in range(1000)) + "\n",
                                   encoding="utf-8")
        dens = cal.probe_density(results, root)
    assert "bandit" not in dens, "an unrun probe must not appear as 0 findings"
    assert dens["gitleaks"] == 0.0, "a probe that ran clean is a real zero"
    assert abs(dens["ruff"] - 5.0) < 0.01, dens["ruff"]   # 5 findings / 1 KLOC


def test_kloc_counts_source_not_binaries():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "a.py").write_text("x = 1\ny = 2\n", encoding="utf-8")
        (root / "blob.bin").write_bytes(b"\x00" * 5000)
        (root / ".git").mkdir()
        (root / ".git" / "c.py").write_text("z = 1\n" * 100, encoding="utf-8")
        assert abs(cal.kloc(root) - 0.002) < 1e-6, cal.kloc(root)


# --- the threshold sweep ----------------------------------------------------

def _pts():
    return [
        {"label": "good", "score": 94.0},
        {"label": "bad", "score": 80.0},
        {"label": "bad", "score": 60.0},
        {"label": "bad", "score": 25.0},
    ]


def test_sweep_treats_bad_as_the_positive_class():
    rows = {r["threshold"]: r for r in cal.sweep_threshold(_pts())}
    at_80 = rows[80.0]
    assert at_80["tp"] == 2, "the 60 and 25 points are below 80"
    assert at_80["fp"] == 0
    assert at_80["fn"] == 1
    assert at_80["tn"] == 1


def test_sweep_separates_perfectly_in_the_gap():
    rows = {r["threshold"]: r for r in cal.sweep_threshold(_pts())}
    perfect = rows[94.0]
    assert perfect["precision"] == 1.0
    assert perfect["recall"] == 1.0
    assert perfect["f1"] == 1.0
    assert perfect["youden_j"] == 1.0


def test_sweep_returns_nothing_without_both_classes():
    """You cannot measure separation with only one class present."""
    assert cal.sweep_threshold([{"label": "bad", "score": 10.0}]) == []
    assert cal.sweep_threshold([{"label": "good", "score": 90.0}]) == []


def test_threshold_comes_from_the_labels_not_the_sweep():
    """The separating interval is (best_bad, worst_good] computed from LABELS.

    The sweep cannot see its interior — it only evaluates thresholds AT observed
    scores — so reading the plateau off the sweep both misses the interior and
    collapses to a single point whenever no observed score lands in the gap.
    """
    rec = cal.choose_threshold(_pts())          # good 94; bad 80, 60, 25
    assert rec["separable"] is True
    assert rec["threshold"] == 87.0
    assert rec["plateau"] == [80.0, 94.0]
    assert rec["margin"] == 7.0
    assert rec["precision"] == 1.0 and rec["recall"] == 1.0


def test_choose_threshold_is_independent_of_candidate_rounding():
    """A near-boundary score must not decide the threshold through rounding.

    The score 79.8399 rounds to a candidate of 79.84, which then sits on the
    "bad" side of itself — an artifact of candidate generation, not evidence.
    Working from the labels makes the boundary exact."""
    pts = [{"label": "good", "score": 94.0},
           {"label": "bad", "score": 79.8399},
           {"label": "bad", "score": 25.0}]
    rec = cal.choose_threshold(pts)
    assert rec["threshold"] == round((79.8399 + 94.0) / 2.0, 4), rec


def test_choose_threshold_reports_overlap_honestly():
    """When no threshold separates the classes, say so rather than presenting a
    'separating' threshold that does not separate."""
    rec = cal.choose_threshold([{"label": "good", "score": 50.0},
                                {"label": "bad", "score": 95.0}])
    assert rec["separable"] is False
    assert "overlap" in rec["note"]
    assert rec["youden_j"] == 0.0


def test_choose_threshold_needs_both_classes():
    assert cal.choose_threshold([{"label": "good", "score": 90.0}]) is None
    assert cal.choose_threshold([]) is None


def test_sweep_finds_only_the_endpoint_of_the_gap():
    """Documents WHY choose_threshold exists, so nobody 'simplifies' it back."""
    rows = cal.sweep_threshold(_pts())
    optimal = [r for r in rows if r["youden_j"] == 1.0]
    assert len(optimal) == 1, "the sweep sees one endpoint, not the interval"
    assert optimal[0]["threshold"] == 94.0


def test_threshold_ignores_non_optimal_rows():
    pts = _pts() + [{"label": "bad", "score": 85.0}]
    rec = cal.choose_threshold(pts)
    assert rec["plateau"] == [85.0, 94.0]
    assert rec["threshold"] == 89.5


# --- the calibrated scorer --------------------------------------------------

def test_density_scorer_anchors_on_non_floored_tools():
    """Most tools find nothing on clean code, so their d* is the floor. Pooling
    ALL of them makes the median 0.05 and drags every dimension to ~6/100 — the
    aggregate curve must anchor on the tools with a real baseline reading."""
    manifest = {
        "halflife_k": 1.2,
        "d_star": {
            "secret-grep": {"d_star": 0.05, "floored": True},
            "py-compile": {"d_star": 0.05, "floored": True},
            "complexity": {"d_star": 2.0, "floored": False},
        },
    }
    assert abs(score.hill_density(2.0, calibration=manifest) - 50.0) < 0.5
    assert abs(score.hill_density(0.0, calibration=manifest) - 100.0) < 0.01


def test_density_scorer_falls_back_without_a_manifest():
    """An uncalibrated checkout must still run, on the documented default.

    An empty calibration dict means "no manifest" (as opposed to None, which
    means "use whatever is on disk").
    """
    got = score.hill_density(5.0, calibration={})
    assert got == score.hill_curve(5.0), "uncalibrated must match the legacy curve"


def test_kloc_of_an_unknown_repo_is_zero():
    assert score.kloc(None) == 0.0
    assert score.kloc(Path("does-not-exist-xyz")) == 0.0


def test_the_shipped_manifest_loads():
    cal_manifest = score.load_calibration()
    assert cal_manifest is not None, "scripts/calibration.json should ship with the repo"
    assert "d_star" in cal_manifest
    assert cal_manifest["threshold"]["recommended"] > 0


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
