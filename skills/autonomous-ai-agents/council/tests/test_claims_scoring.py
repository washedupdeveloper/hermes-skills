"""M-E: the score comes from the claims that were proven, and its scale says so.

Run standalone (no pytest needed):
    python tests/test_claims_scoring.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS))

_spec = importlib.util.spec_from_file_location("score_reviews", SCRIPTS / "score_reviews.py")
score = importlib.util.module_from_spec(_spec)
sys.modules["score_reviews"] = score
_spec.loader.exec_module(score)

DIMS = ("security", "correctness", "readability", "architecture", "performance")


def make(tmp: Path, *, reviewer_score=95, records=None, proofs=True, meta_proof=True) -> Path:
    repo = tmp / "repo"
    (repo / "src").mkdir(parents=True, exist_ok=True)
    (repo / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")
    round_dir = tmp / "round-1"
    round_dir.mkdir()
    meta = {"repo": str(repo), "stacks": ["generic"], "target_sha": "a" * 40}
    if meta_proof:
        meta["require_proof"] = True
    (round_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    for dim in DIMS:
        # The adjudication records must mirror findings the reviewers actually reported — a
        # record with no finding behind it is a fixture that tests nothing.
        findings = [{"id": r["id"], "dimension": dim, "severity": r["severity"],
                     "status": "open", "location": r["location"], "claim": "fixture"}
                    for r in (records or []) if r["dimension"] == dim]
        (round_dir / f"{dim}.json").write_text(json.dumps(
            {"dimension": dim, "score": reviewer_score, "findings": findings}), encoding="utf-8")
    if proofs:
        (round_dir / "proofs.json").write_text(json.dumps({
            "schema_version": 1, "findings": records or []}), encoding="utf-8")
    return round_dir


def record(ident="SEC-1", dimension="security", severity="critical", state="confirmed") -> dict:
    return {"id": ident, "dimension": dimension, "severity": severity, "state": state,
            "status": "open", "location": {"path": "src/app.py", "line_range": "1"},
            "blocks_certification": state != "refuted"}


class calibrated:
    """Pretend a claims-scale threshold exists, for the tests that are not about calibration."""

    def __enter__(self):
        self._original = score.load_calibration
        score.load_calibration = lambda path=None: {"scale": "claims", "threshold": 80.0}
        return self

    def __exit__(self, *exc):
        score.load_calibration = self._original


# --- the number itself -------------------------------------------------------------


def test_nothing_proven_scores_a_hundred():
    with tempfile.TemporaryDirectory() as tmp:
        result = score.evaluate(make(Path(tmp)), 80.0)
    security = next(d for d in result["per_dimension"] if d["dimension"] == "security")
    assert security["llm"] == 100.0, security
    assert security["source"] == "claims"


def test_a_confirmed_critical_lowers_the_dimension():
    with tempfile.TemporaryDirectory() as tmp:
        result = score.evaluate(make(Path(tmp), records=[record()]), 80.0)
    security = next(d for d in result["per_dimension"] if d["dimension"] == "security")
    assert security["llm"] < 50.0, security
    assert security["source"] == "claims"


def test_unsettled_claims_do_not_lower_the_score():
    """An unsettled claim is not a known defect; it blocks certification by its own route."""
    with tempfile.TemporaryDirectory() as tmp:
        result = score.evaluate(make(Path(tmp), records=[record(state="unsettled")]), 80.0)
    security = next(d for d in result["per_dimension"] if d["dimension"] == "security")
    assert security["llm"] == 100.0, security


def test_refuted_claims_do_not_lower_the_score():
    with tempfile.TemporaryDirectory() as tmp:
        result = score.evaluate(make(Path(tmp), records=[record(state="refuted")]), 80.0)
    security = next(d for d in result["per_dimension"] if d["dimension"] == "security")
    assert security["llm"] == 100.0


def test_the_reviewer_number_is_ignored_when_claims_drive_the_score():
    """Same claims, wildly different self-assessment, same result — that is the point."""
    with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2:
        high = score.evaluate(make(Path(tmp1), reviewer_score=99, records=[record()]), 80.0)
        low = score.evaluate(make(Path(tmp2), reviewer_score=10, records=[record()]), 80.0)
    assert high["aggregate"] == low["aggregate"], (high["aggregate"], low["aggregate"])


# --- the scale -----------------------------------------------------------------------


def test_a_claims_verdict_does_not_need_a_threshold():
    """A clean claims-scored run certifies with no claims threshold, because the verdict is what
    the run PROVED, not where its aggregate fell.

    Measured: six passes over one identical tree scored 52.49–68.08 and three passes over a clean
    tree 78.37–88.81. A cutoff inside a 10-point spread decides by luck; the blocking set decided
    every one of twelve runs the same way. `uncalibrated` now belongs only to the deterministic
    scale, where the number IS the verdict.
    """
    with tempfile.TemporaryDirectory() as tmp:
        # Point at a path that cannot exist: this asserts the NO-calibration case, and
        # reading the repo's own `scripts/calibration.claims.json` made the test change
        # meaning the moment a corpus-derived file was committed.
        original = score.calibration_path
        score.calibration_path = lambda scale: Path(tmp) / "calibration.claims.json"
        try:
            result = score.evaluate(make(Path(tmp)), 80.0)
        finally:
            score.calibration_path = original
    assert result["score_source"] == "claims"
    assert result["calibration_scale"] == "missing", result["calibration_scale"]
    assert result["calibrated_for_scale"] is False
    assert result["certification_basis"] == "claims"
    assert result["certification"] == "certified", result["reason"]
    assert result["status"] == "satisfied"


def test_a_claims_verdict_ignores_the_threshold_entirely():
    """Point 2, made permanent: no claims threshold decides a verdict, whatever its value.

    A medium confirmed claim caps the aggregate below 100 and nothing blocks, so a threshold of
    100 must not change the answer. If this ever fails, a magic number has crept back in.
    """
    with tempfile.TemporaryDirectory() as tmp:
        result = score.evaluate(make(Path(tmp), records=[record(severity="medium")]), 100.0)
    assert result["certification_basis"] == "claims"
    assert result["aggregate"] < 100.0, "the fixture must sit under the threshold"
    assert result["certification"] == "certified", result["reason"]


def test_a_claims_scale_threshold_certifies():
    with calibrated(), tempfile.TemporaryDirectory() as tmp:
        result = score.evaluate(make(Path(tmp), records=[record(state="refuted")]), 80.0)
    assert result["calibrated_for_scale"] is True
    assert result["certification"] == "certified", result["reason"]


def test_a_confirmed_defect_still_fails_on_a_calibrated_claims_scale():
    with calibrated(), tempfile.TemporaryDirectory() as tmp:
        result = score.evaluate(make(Path(tmp), records=[record()]), 80.0)
    assert result["certification"] == "unsatisfied", result["reason"]


def test_without_proofs_the_reviewer_scale_is_used_and_is_calibrated():
    with tempfile.TemporaryDirectory() as tmp:
        result = score.evaluate(make(Path(tmp), proofs=False), 80.0)
    assert result["score_source"] == "reviewer"
    assert result["calibrated_for_scale"] is True
    assert result["certification"] == "certified"


def test_the_opt_out_also_restores_reviewer_scoring():
    """`--allow-unproven` reproduces an old score, which includes the old scale."""
    with tempfile.TemporaryDirectory() as tmp:
        result = score.evaluate(make(Path(tmp), records=[record()]), 80.0, require_proof=False)
    assert result["score_source"] == "reviewer"
    assert result["calibrated_for_scale"] is True


# --- precedence -----------------------------------------------------------------------


def test_a_confirmed_defect_outranks_the_calibration_state():
    with tempfile.TemporaryDirectory() as tmp:
        result = score.evaluate(make(Path(tmp), records=[record()]), 80.0)
    assert result["certification"] == "unsatisfied", "a real defect is the more useful answer"


def test_an_unsettled_claim_outranks_the_calibration_state():
    with tempfile.TemporaryDirectory() as tmp:
        result = score.evaluate(make(Path(tmp), records=[record(state="unsettled")]), 80.0)
    assert result["certification"] == "unprovable"


# --- the cap: a proven defect cannot be diluted by a quiet tool --------------------


def test_the_cap_follows_the_worst_confirmed_severity():
    rows = [record(severity="medium"), record(ident="SEC-2", severity="critical")]
    assert score.claim_cap(rows) == 30.0
    assert score.claim_cap([record(severity="high")]) == 60.0
    assert score.claim_cap([record(severity="medium")]) == 85.0


def test_unproven_claims_impose_no_cap():
    assert score.claim_cap([record(state="unsettled")]) is None
    assert score.claim_cap([record(state="refuted")]) is None
    assert score.claim_cap([record(state="unrunnable")]) is None
    assert score.claim_cap([]) is None


def test_a_confirmed_critical_caps_the_dimension_score():
    review = {"score": 99, "findings": []}
    row = score.score_dimension(review, "security", ["generic"], 0.0,
                                adjudication={"findings": [record()]})
    assert row["cap"] == 30.0, row
    assert row["score"] <= 30.0, row


def test_the_cap_survives_a_perfect_deterministic_score():
    """β = 1 is the case that hid the dead claims term: score = det, cap must still apply."""
    review = {"score": 0, "findings": [], "tools": {"bandit": {"ran": True, "parsed": True}}}
    row = score.score_dimension(review, "security", ["python"], 0.0,
                                adjudication={"findings": [record()]})
    if row["beta"] == 1.0:
        assert row["score"] <= 30.0, row


def test_the_aggregate_reflects_a_confirmed_critical():
    with calibrated(), tempfile.TemporaryDirectory() as tmp:
        result = score.evaluate(make(Path(tmp), records=[record()]), 80.0)
    security = next(d for d in result["per_dimension"] if d["dimension"] == "security")
    assert security["score"] <= 30.0, security
    assert result["aggregate"] < 80.0, result["aggregate"]


def test_a_tiny_tree_is_not_scored_as_if_every_line_were_defective():
    """One medium finding in a 56-line file must not outrank the same finding in a real repo.

    Without the floor the density term saturates and every rung of the first corpus scored 39–44,
    with the 16-defect rung outscoring the clean one.
    """
    rows = [record(severity="medium")]
    tiny = score.claims_score(rows, 0.056)
    floor = score.claims_score(rows, score.MIN_KLOC)
    real = score.claims_score(rows, 10.0)
    assert tiny == floor, (tiny, floor)
    assert real > tiny, f"a 10 KLOC repo ({real}) must score better than a 56-line one ({tiny})"


def test_det_does_not_reward_a_smaller_tree():
    """The density term must use the same floor as the claims term.

    Without it a 56-line tree is judged denser than a 16-defect tree for the same findings — the
    measured cause of the 16-defect rung outscoring the clean one.
    """
    review = {"findings": [{"severity": "medium", "status": "open"}] * 3}
    tiny = score.deterministic_score(review, "correctness", ["generic"], 0.056)[0]
    floor = score.deterministic_score(review, "correctness", ["generic"], score.MIN_KLOC)[0]
    real = score.deterministic_score(review, "correctness", ["generic"], 10.0)[0]
    assert tiny == floor, (tiny, floor)
    assert real >= tiny, f"10 KLOC ({real}) must not score worse than 56 lines ({tiny})"


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok   {name}")
            except AssertionError as exc:
                failures += 1
                print(f"FAIL {name}: {exc}")
    raise SystemExit(1 if failures else 0)
