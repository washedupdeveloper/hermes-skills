"""The gate with proofs: only `refuted` clears a blocking finding, and `unprovable` is its own state.

Run standalone (no pytest needed):
    python tests/test_gate_proofs.py
"""
from __future__ import annotations

import contextlib
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

DIMENSIONS = ("security", "correctness", "readability", "architecture", "performance")


def round_dir(tmp: Path, findings=None, score_value=100, proofs=None) -> Path:
    """A round the real gate can score: five dimension files, a repo, and optional adjudication."""
    root = tmp / "run"
    root.mkdir(parents=True, exist_ok=True)
    repo = tmp / "repo"
    repo.mkdir(exist_ok=True)
    (repo / "app.py").write_text("x = 1\n", encoding="utf-8")
    (root / "meta.json").write_text(json.dumps({"repo": str(repo), "stacks": ["python"]}),
                                    encoding="utf-8")
    for dimension in DIMENSIONS:
        owned = [f for f in (findings or []) if f.get("dimension") == dimension]
        (root / f"{dimension}.json").write_text(json.dumps(
            {"dimension": dimension, "score": score_value, "findings": owned}), encoding="utf-8")
    if proofs is not None:
        (root / "proofs.json").write_text(json.dumps(
            {"schema_version": 1, "findings": proofs}), encoding="utf-8")
    return root


def critical(dimension="security", ident="C-1", path="app.py", line="3") -> dict:
    return {"id": ident, "dimension": dimension, "severity": "critical", "status": "open",
            "location": {"path": path, "line_range": line}, "claim": "broken"}


def record(finding, state, ident=None) -> dict:
    return {"id": ident or finding["id"], "dimension": finding["dimension"], "state": state,
            "location": finding["location"], "blocks_certification": state != "refuted"}


# --- without enforcement nothing changes -------------------------------------------


def test_the_default_is_enforcement():
    """No flag, no proofs: the run is unprovable, not satisfied."""
    with tempfile.TemporaryDirectory() as tmp:
        result = score.evaluate(round_dir(Path(tmp), [critical()]), 80)
    assert result["enforced"] is True
    assert result["certification"] == "unprovable"


def test_allow_unproven_restores_the_pre_proof_rule():
    with tempfile.TemporaryDirectory() as tmp:
        result = score.evaluate(round_dir(Path(tmp), [critical()]), 80, require_proof=False)
    assert result["status"] == "not_satisfied"
    assert result["certification"] == "unsatisfied"
    assert result["enforced"] is False


def test_without_require_proof_a_proofs_file_is_ignored():
    """Opted out is opted out: a refuted finding does not open the gate on its own."""
    with tempfile.TemporaryDirectory() as tmp:
        finding = critical()
        result = score.evaluate(round_dir(Path(tmp), [finding],
                                          proofs=[record(finding, "refuted")]), 80,
                                require_proof=False)
    assert result["status"] == "not_satisfied"
    assert result["enforced"] is False


# --- with enforcement ---------------------------------------------------------------


@contextlib.contextmanager
def claims_scale():
    """These tests are about blocking, not about calibration.

    A claims-scored run is `uncalibrated` until a threshold exists for that scale (see
    test_claims_scoring.py). Pinning the scale here keeps this file's subject — which proof states
    clear a blocking finding — independent of that separate question.
    """
    original = score.load_calibration
    score.load_calibration = lambda path=None: {"scale": "claims", "threshold": 80.0}
    try:
        yield
    finally:
        score.load_calibration = original


def test_a_refuted_blocking_finding_no_longer_blocks():
    with claims_scale(), tempfile.TemporaryDirectory() as tmp:
        finding = critical()
        result = score.evaluate(round_dir(Path(tmp), [finding],
                                          proofs=[record(finding, "refuted")]), 80,
                                require_proof=True)
    assert result["certification"] == "certified", result["reason"]
    assert result["blocking"] == []


def test_an_unsettled_blocking_finding_makes_the_run_unprovable_not_failed():
    with tempfile.TemporaryDirectory() as tmp:
        finding = critical()
        result = score.evaluate(round_dir(Path(tmp), [finding],
                                          proofs=[record(finding, "unsettled")]), 80,
                                require_proof=True)
    assert result["certification"] == "unprovable"
    assert result["status"] == "not_satisfied"
    assert "could not be settled" in result["reason"]
    assert len(result["unresolved"]) == 1


def test_a_confirmed_blocking_finding_is_an_ordinary_failure():
    with tempfile.TemporaryDirectory() as tmp:
        finding = critical()
        result = score.evaluate(round_dir(Path(tmp), [finding],
                                          proofs=[record(finding, "confirmed")]), 80,
                                require_proof=True)
    assert result["certification"] == "unsatisfied"
    assert result["unresolved"] == [], "a confirmed defect is not an unresolved one"


def test_no_proofs_file_at_all_means_nothing_was_settled():
    """Enforcement must not pass because the adjudication is missing — that is a back door."""
    with tempfile.TemporaryDirectory() as tmp:
        result = score.evaluate(round_dir(Path(tmp), [critical()]), 80, require_proof=True)
    assert result["certification"] == "unprovable"
    assert result["unresolved"][0]["_adjudication"] == "missing"


def test_a_blocking_finding_the_report_never_saw_is_unresolved():
    with tempfile.TemporaryDirectory() as tmp:
        finding = critical()
        other = critical(ident="C-2", line="9")
        result = score.evaluate(round_dir(Path(tmp), [finding, other],
                                          proofs=[record(finding, "confirmed")]), 80,
                                require_proof=True)
    assert len(result["unresolved"]) == 1
    assert result["unresolved"][0]["id"] == "C-2"


def test_matching_works_by_location_when_the_id_differs():
    with claims_scale(), tempfile.TemporaryDirectory() as tmp:
        finding = critical()
        payload = [{"id": "something-else", "dimension": "security", "state": "refuted",
                    "location": {"path": "app.py", "line_range": "3"}}]
        result = score.evaluate(round_dir(Path(tmp), [finding], proofs=payload), 80,
                                require_proof=True)
    assert result["certification"] == "certified"


def test_a_low_severity_finding_is_unaffected_by_enforcement():
    with tempfile.TemporaryDirectory() as tmp:
        quiet = {"id": "L-1", "dimension": "readability", "severity": "low", "status": "open",
                 "location": {"path": "app.py", "line_range": "1"}, "claim": "style"}
        result = score.evaluate(round_dir(Path(tmp), [quiet]), 80, require_proof=True)
    assert result["certification"] == "certified"


def test_the_score_shortfall_is_still_a_failure_under_enforcement():
    with tempfile.TemporaryDirectory() as tmp:
        result = score.evaluate(round_dir(Path(tmp), [], score_value=40), 80, require_proof=True)
    assert result["certification"] == "unsatisfied"
    assert "aggregate" in result["reason"]


def test_the_mode_is_recorded_in_the_result():
    with tempfile.TemporaryDirectory() as tmp:
        root = round_dir(Path(tmp), [])
        enforced = score.evaluate(root, 80, require_proof=True)
        advisory = score.evaluate(root, 80, require_proof=False)
    assert enforced["enforced"] is True and advisory["enforced"] is False


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
