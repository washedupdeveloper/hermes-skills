"""The claim ladder: every rung, both directions, and the determinism it promises.

Run standalone (no pytest needed):
    python tests/test_claims.py

Two rules shape these tests:

* a claim is DERIVED — so every case writes the files that would justify a rung, asserts it opens,
  then removes or corrupts exactly that evidence and asserts it closes with a reason a reader needs;
* the ladder is DETERMINISTIC — the verdict is always recomputed here, and two builds of the same
  tree must be byte-identical, so one test asserts exactly that instead of trusting the docstring.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

_spec = importlib.util.spec_from_file_location("claims", REPO / "scripts" / "claims.py")
claims = importlib.util.module_from_spec(_spec)
sys.modules["claims"] = claims
_spec.loader.exec_module(claims)

_sspec = importlib.util.spec_from_file_location("score_reviews", REPO / "scripts" / "score_reviews.py")
score = importlib.util.module_from_spec(_sspec)
sys.modules["score_reviews"] = score
_sspec.loader.exec_module(score)

SHA = "a" * 40
OTHER = "b" * 40

CLEAN_BROWSER = {
    "tool": "browser", "ran": True, "parsed": True, "signal": 100.0, "findings": [],
    "note": "observed file:///x with chromium; dom=/tmp/d/dom.html screenshot=/tmp/d/page.png; 0 critical",
}


def all_expected(stacks) -> list:
    out = []
    for dimension in score.STACK_TOOLS.values():
        for stack in stacks:
            for tool in dimension.get(stack, []):
                if tool not in out:
                    out.append(tool)
    return out


def probes_for(stacks, *, browser=None):
    """A passing row for every expected tool; the browser lane is explicit, never implied."""
    rows = [{"tool": t, "ran": True, "parsed": True, "signal": 100.0, "findings": [], "note": ""}
            for t in all_expected(stacks) if t != "browser"]
    if "browser" in all_expected(stacks):
        rows.append(dict(browser or CLEAN_BROWSER))
    return rows


def fixture(tmp: Path, *, stacks=("nix",), sha=SHA, meta=True, probes="ok", browser=None,
            scores=100, findings=None, rounds=("round-1",), round_metas=None) -> Path:
    """A run directory the REAL gate scores. No synthetic verdict is passed anywhere."""
    root = tmp / "run-1"
    root.mkdir()
    if meta:
        (root / "meta.json").write_text(json.dumps(
            {"target_sha": sha, "stacks": list(stacks), "repo": str(tmp),
             "mode": "whole-repo", "round": 1}), encoding="utf-8")
    if probes == "ok":
        (root / "probes.json").write_text(json.dumps(probes_for(stacks, browser=browser)),
                                          encoding="utf-8")
    elif probes == "empty":
        (root / "probes.json").write_text("[]", encoding="utf-8")
    for name in rounds:
        round_dir = root / name
        round_dir.mkdir()
        for dim in claims.DIMENSIONS:
            (round_dir / f"{dim}.json").write_text(json.dumps(
                {"dimension": dim, "score": scores, "findings": list(findings or [])}), encoding="utf-8")
    for name, meta_payload in (round_metas or {}).items():
        (root / name / "meta.json").write_text(json.dumps(meta_payload), encoding="utf-8")
    return root


def build(root: Path, **kw):
    return claims.build(root, **kw)


# --- the shape ------------------------------------------------------------------


def test_the_ladder_is_ordered_and_labelled():
    assert claims.LADDER[0] == "run_recorded" and claims.LADDER[-1] == "published"
    for rung in claims.LADDER:
        assert rung in claims.LABELS and rung in claims.BLOCK_REASONS, rung


def test_a_complete_run_reaches_the_last_supported_rung():
    with tempfile.TemporaryDirectory() as tmp:
        payload = build(fixture(Path(tmp)))
    assert payload["allowed_claims"] == ["run_recorded", "probes_observed", "council_complete",
                                         "gate_recomputed", "verdict_calibrated"]
    assert payload["blocked_claims"][0]["claim"] == "ci_observed"
    assert payload["claim_state"] == "verdict_calibrated"
    assert "CI" in payload["blocked_claims"][0]["reason"]


# --- determinism ----------------------------------------------------------------


def test_two_builds_of_one_tree_are_byte_identical():
    """No clock, no set iteration, no caller-supplied verdict: the same files, the same bytes."""
    with tempfile.TemporaryDirectory() as tmp:
        root = fixture(Path(tmp))
        first = json.dumps(build(root), indent=2, sort_keys=True)
        second = json.dumps(build(root), indent=2, sort_keys=True)
    assert first == second


def test_the_newest_round_is_chosen_numerically_not_alphabetically():
    """`round-10` sorts before `round-2` as a string; scoring round 9 would be a silent wrong answer."""
    with tempfile.TemporaryDirectory() as tmp:
        root = fixture(Path(tmp), rounds=("round-2", "round-9", "round-10"), scores=0,
                       findings=[{"severity": "critical", "status": "open", "claim": "x",
                                  "location": {"path": "a", "line_range": "1"}}])
        # round-10 is the only clean one: if it is not chosen, the verdict is not satisfied.
        for dim in claims.DIMENSIONS:
            (root / "round-10" / f"{dim}.json").write_text(json.dumps(
                {"dimension": dim, "score": 100, "findings": []}), encoding="utf-8")
        payload = build(root)
    assert payload["verdict"]["status"] == "satisfied", payload["verdict"]
    assert payload["verdict"]["aggregate"] == 100.0


def test_a_caller_supplied_verdict_cannot_open_the_ladder():
    """The gate is recomputed; a disagreeing dict is reported, not honoured."""
    with tempfile.TemporaryDirectory() as tmp:
        root = fixture(Path(tmp))
        payload = build(root, result={"status": "satisfied", "aggregate": 12.5, "threshold": 80.0})
    blocked = payload["blocked_claims"][0]
    assert blocked["claim"] == "gate_recomputed"
    assert "12.5" in blocked["reason"] and "recomputes" in blocked["reason"]


# --- each rung closes when its evidence is gone ---------------------------------


def test_no_meta_json_blocks_at_the_first_rung():
    with tempfile.TemporaryDirectory() as tmp:
        payload = build(fixture(Path(tmp), meta=False))
    assert payload["allowed_claims"] == []
    assert payload["claim_state"] == "nothing_observed"
    assert "nothing to attach" in payload["blocked_claims"][0]["reason"]


def test_two_meta_json_that_disagree_are_a_conflict_not_a_choice():
    with tempfile.TemporaryDirectory() as tmp:
        root = fixture(Path(tmp), round_metas={"round-1": {"target_sha": OTHER}})
        payload = build(root)
    blocked = payload["blocked_claims"][0]
    assert blocked["claim"] == "run_recorded"
    assert SHA[:12] in blocked["reason"] and OTHER[:12] in blocked["reason"]


def test_a_missing_probe_blocks_and_names_the_tool():
    with tempfile.TemporaryDirectory() as tmp:
        root = fixture(Path(tmp))
        rows = [p for p in probes_for(["nix"]) if p["tool"] != "flake-check"]
        (root / "probes.json").write_text(json.dumps(rows), encoding="utf-8")
        payload = build(root)
    assert payload["allowed_claims"] == ["run_recorded"]
    assert "flake-check" in payload["blocked_claims"][0]["reason"]


def test_an_absent_probe_file_says_never_recorded():
    with tempfile.TemporaryDirectory() as tmp:
        payload = build(fixture(Path(tmp), probes="absent"))
    assert "never recorded" in payload["blocked_claims"][0]["reason"]


def test_an_empty_probe_file_is_not_a_clean_one():
    """An empty array means the runner produced nothing — a different fact from "no file"."""
    with tempfile.TemporaryDirectory() as tmp:
        payload = build(fixture(Path(tmp), probes="empty"))
    assert payload["blocked_claims"][0]["claim"] == "probes_observed"
    assert "empty" in payload["blocked_claims"][0]["reason"]


def test_a_run_with_no_stacks_cannot_pass_the_probe_rung_vacuously():
    with tempfile.TemporaryDirectory() as tmp:
        root = fixture(Path(tmp), stacks=())
        (root / "probes.json").write_text(json.dumps([]), encoding="utf-8")
        payload = build(root)
    assert payload["allowed_claims"] == ["run_recorded"]
    assert payload["blocked_claims"][0]["claim"] == "probes_observed"


def test_an_incomplete_council_cannot_certify():
    with tempfile.TemporaryDirectory() as tmp:
        root = fixture(Path(tmp))
        (root / "round-1" / "correctness.json").unlink()
        payload = build(root)
    blocked = payload["blocked_claims"][0]
    assert blocked["claim"] == "council_complete"
    assert "correctness" in blocked["reason"]


def test_an_uncalibrated_threshold_blocks_the_calibration_rung():
    """The rung's contract is one field of the gate's result, asserted directly."""
    ok, _, _ = claims._rung_verdict_calibrated({"calibrated": True, "threshold": 80}, {})
    not_ok, reason, _ = claims._rung_verdict_calibrated({"calibrated": False, "threshold": 80}, {})
    assert ok and not not_ok and "override" in reason


# --- the runtime rung is conditional and evidence-bearing -----------------------


def test_runtime_is_not_applicable_without_a_page():
    with tempfile.TemporaryDirectory() as tmp:
        payload = build(fixture(Path(tmp), stacks=["nix"]))
    assert "runtime_observed" in payload["not_applicable"]
    assert all(item["claim"] != "runtime_observed" for item in payload["blocked_claims"])


def test_a_web_run_whose_browser_probe_did_not_run_blocks_the_beta_rung():
    with tempfile.TemporaryDirectory() as tmp:
        browser = {"tool": "browser", "ran": False, "parsed": False, "signal": None,
                   "findings": [], "note": "no headless browser — runtime behaviour not observed"}
        payload = build(fixture(Path(tmp), stacks=["web"], browser=browser))
    assert payload["allowed_claims"] == ["run_recorded"]
    assert payload["blocked_claims"][0]["claim"] == "probes_observed"
    assert "browser" in payload["blocked_claims"][0]["reason"]


def test_a_loaded_page_opens_the_runtime_rung_and_carries_artifacts():
    with tempfile.TemporaryDirectory() as tmp:
        payload = build(fixture(Path(tmp), stacks=["web"]))
    kinds = {e["kind"]: e["source"] for e in payload["evidence"]}
    assert kinds.get("dom") == "/tmp/d/dom.html"
    assert kinds.get("screenshot") == "/tmp/d/page.png"
    assert "runtime_observed" in payload["allowed_claims"]


def test_an_observed_page_failure_blocks_the_runtime_rung():
    with tempfile.TemporaryDirectory() as tmp:
        browser = {"tool": "browser", "ran": True, "parsed": True, "signal": 60.0,
                   "findings": [{"severity": "critical", "claim": "did not mount"}],
                   "note": "observed file:///x; dom=/d.html screenshot=/p.png; 1 critical"}
        payload = build(fixture(Path(tmp), stacks=["web"], browser=browser))
    blocked = payload["blocked_claims"][0]
    assert blocked["claim"] == "runtime_observed"
    assert "40 point" in blocked["reason"]


# --- CI and publication are receipts, never memories ----------------------------


def test_a_ci_receipt_for_another_commit_does_not_open_the_rung():
    with tempfile.TemporaryDirectory() as tmp:
        root = fixture(Path(tmp))
        claims.record_ci(root, OTHER, "success", "https://ci/1")
        blocked = build(root)["blocked_claims"][0]
    assert blocked["claim"] == "ci_observed"
    assert OTHER[:12] in blocked["reason"] and SHA[:12] in blocked["reason"]


def test_a_ci_receipt_that_names_no_commit_is_not_evidence():
    with tempfile.TemporaryDirectory() as tmp:
        root = fixture(Path(tmp))
        path = root / claims.CI_RECEIPT
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"conclusion": "success", "url": "https://ci/x"}), encoding="utf-8")
        blocked = build(root)["blocked_claims"][0]
    assert blocked["claim"] == "ci_observed"
    assert "names no commit" in blocked["reason"]


def test_record_ci_refuses_a_short_sha():
    with tempfile.TemporaryDirectory() as tmp:
        root = fixture(Path(tmp))
        try:
            claims.record_ci(root, SHA[:12], "success", "https://ci/1")
        except ValueError as exc:
            assert "40-character" in str(exc)
        else:
            raise AssertionError("a short sha was accepted")


def test_a_failing_ci_receipt_is_not_a_pass():
    with tempfile.TemporaryDirectory() as tmp:
        root = fixture(Path(tmp))
        claims.record_ci(root, SHA, "failure", "https://ci/2")
        blocked = build(root)["blocked_claims"][0]
    assert blocked["claim"] == "ci_observed"
    assert "`failure`" in blocked["reason"]


def test_a_passing_ci_receipt_opens_merge_ready():
    with tempfile.TemporaryDirectory() as tmp:
        root = fixture(Path(tmp))
        claims.record_ci(root, SHA, "success", "https://ci/3")
        payload = build(root)
    assert payload["claim_state"] == "merge_ready"
    assert payload["blocked_claims"][0]["claim"] == "published"


def test_ci_alone_does_not_open_merge_ready_on_a_failing_verdict():
    with tempfile.TemporaryDirectory() as tmp:
        root = fixture(Path(tmp), findings=[{"severity": "critical", "status": "open",
                                             "claim": "x", "location": {"path": "a", "line_range": "1"}}])
        claims.record_ci(root, SHA, "success", "https://ci/4")
        payload = build(root)
    assert "ci_observed" in payload["allowed_claims"]
    assert payload["blocked_claims"][0]["claim"] == "merge_ready"


def test_publishing_is_the_top_rung_and_needs_a_read_back_url():
    with tempfile.TemporaryDirectory() as tmp:
        root = fixture(Path(tmp))
        claims.record_ci(root, SHA, "success", "https://ci/5")
        claims.record_published(root, "https://github.com/o/r/pull/7#issuecomment-1", 1, SHA)
        payload = build(root)
    assert payload["claim_state"] == "published"
    assert payload["blocked_claims"] == []


def test_a_receipt_with_no_url_is_not_publication():
    with tempfile.TemporaryDirectory() as tmp:
        root = fixture(Path(tmp))
        claims.record_ci(root, SHA, "success", "https://ci/6")
        path = root / claims.PUBLISH_RECEIPT
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"sha": SHA}), encoding="utf-8")
        blocked = build(root)["blocked_claims"][0]
    assert blocked["claim"] == "published"
    assert "not observed" in blocked["reason"]


# --- pointing at a round directory ----------------------------------------------


def test_a_round_directory_finds_its_run_root_and_receipts():
    with tempfile.TemporaryDirectory() as tmp:
        root = fixture(Path(tmp))
        claims.record_ci(root, SHA, "success", "https://ci/7")
        payload = build(root / "round-1")
    assert payload["run"] == "run-1"
    assert "ci_observed" in payload["allowed_claims"]


def test_the_summary_names_the_first_blocked_rung():
    with tempfile.TemporaryDirectory() as tmp:
        payload = build(fixture(Path(tmp)))
    assert "Blocked at `ci_observed`" in payload["safe_summary"]
    assert payload["next_action"] == "ci_observed"


# --- the CLI ---------------------------------------------------------------------


def _cli(argv):
    import contextlib
    import io

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = claims.main(argv)
    return code, buffer.getvalue()


def test_the_cli_exits_one_when_something_is_blocked():
    with tempfile.TemporaryDirectory() as tmp:
        root = fixture(Path(tmp))
        code, out = _cli(["--run", str(root), "--json"])
    assert code == 1
    assert json.loads(out)["claim_state"] == "verdict_calibrated"


def test_the_cli_exits_zero_when_the_required_rung_is_reached():
    with tempfile.TemporaryDirectory() as tmp:
        root = fixture(Path(tmp))
        claims.record_ci(root, SHA, "success", "https://ci/8")
        code, out = _cli(["--run", str(root), "--json", "--require", "merge_ready"])
    assert code == 0, out


def test_the_cli_refuses_a_rung_it_cannot_reach():
    with tempfile.TemporaryDirectory() as tmp:
        root = fixture(Path(tmp))
        code, _ = _cli(["--run", str(root), "--json", "--require", "published"])
    assert code == 1


# --- the snapshot the loop records ------------------------------------------------


def _loop():
    spec = importlib.util.spec_from_file_location("council_loop_probe", REPO / "scripts" / "council_loop.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["council_loop_probe"] = module
    spec.loader.exec_module(module)
    return module


def test_the_outcome_snapshot_is_the_ladder_and_is_fail_open():
    loop = _loop()
    with tempfile.TemporaryDirectory() as tmp:
        payload, error = loop.claims_snapshot(fixture(Path(tmp)))
    assert error is None
    assert payload["schema_version"] == claims.SCHEMA_VERSION
    assert payload["claim_state"] == "verdict_calibrated"


def test_the_outcome_snapshot_reports_a_named_error_instead_of_raising():
    loop = _loop()
    original = loop.HERE
    try:
        loop.HERE = Path("/nonexistent-council-scripts")
        payload, error = loop.claims_snapshot(Path("/tmp"))
    finally:
        loop.HERE = original
    assert payload is None
    assert error and "Error" in error


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
