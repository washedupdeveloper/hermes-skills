"""Adjudication: four states, one of which is a pass, and the refuted-only asymmetry.

Run standalone (no pytest needed):
    python tests/test_adjudicate.py
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

for name, filename in (("proofs", "proofs.py"), ("score_reviews", "score_reviews.py")):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)

_spec = importlib.util.spec_from_file_location("adjudicate", SCRIPTS / "adjudicate.py")
adjudicate = importlib.util.module_from_spec(_spec)
sys.modules["adjudicate"] = adjudicate
_spec.loader.exec_module(adjudicate)


def tree(root: Path) -> Path:
    """A repo with an unused symbol, so `absent` can be proven and refuted for real."""
    (root / "app.py").write_text("def live():\n    return 1\n\nlive()\n", encoding="utf-8")
    (root / "dead.py").write_text("def orphan_helper():\n    return 2\n", encoding="utf-8")
    return root


def round_with(root: Path, findings, name="round-1", meta=True) -> Path:
    repos = root / "repo"
    repos.mkdir(exist_ok=True)
    tree(repos)
    round_dir = root / "run" / name
    round_dir.mkdir(parents=True)
    if meta:
        (root / "run" / "meta.json").write_text(json.dumps({"repo": str(repos)}), encoding="utf-8")
        (round_dir / "meta.json").write_text(json.dumps({"repo": str(repos)}), encoding="utf-8")
    (round_dir / "security.json").write_text(
        json.dumps({"dimension": "security", "score": 90, "findings": findings}), encoding="utf-8")
    return round_dir


CLEAN_PROOF = {"kind": "absent", "params": {"pattern": "orphan_helper\\(", "exclude": ["dead.py"]},
               "control": {"params": {"pattern": "orphan_helper\\("}}}


def finding(**over) -> dict:
    base = {"id": "GEN-0001", "dimension": "security", "severity": "high", "status": "open",
            "location": {"path": "app.py", "line_range": "3"}, "claim": "something is wrong",
            "falsifiable_check": "grep -c 'orphan_helper' app.py"}
    base.update(over)
    return base


# --- the four states ----------------------------------------------------------------


def test_no_proof_is_unsettled_and_blocks():
    with tempfile.TemporaryDirectory() as tmp:
        payload = adjudicate.adjudicate_round(round_with(Path(tmp), [finding()]), None)
    record = payload["findings"][0]
    assert record["state"] == "unsettled"
    assert record["blocks_certification"] is True
    assert "no structured proof" in record["reason"]
    # the prose the reviewer did supply is preserved, not discarded
    assert record["candidate"].startswith("grep -c")


def test_a_proven_blocking_finding_still_blocks_a_merge():
    """`confirmed` is a real defect. It blocks for the opposite reason to `unsettled`."""
    with tempfile.TemporaryDirectory() as tmp:
        payload = adjudicate.adjudicate_round(
            round_with(Path(tmp), [finding(proof=CLEAN_PROOF)]), None)
    record = payload["findings"][0]
    assert record["state"] == "confirmed"
    assert record["blocks_certification"] is True
    assert "reproduced" in record["reason"]


def test_a_refuted_proof_clears_the_finding():
    with tempfile.TemporaryDirectory() as tmp:
        bad = {"kind": "absent", "params": {"pattern": "orphan_helper"},
               "control": {"params": {"pattern": "orphan_helper"}}}
        payload = adjudicate.adjudicate_round(round_with(Path(tmp), [finding(proof=bad)]), None)
    record = payload["findings"][0]
    assert record["state"] == "refuted"
    assert record["blocks_certification"] is False, "refuted is the only state that clears a block"


def test_an_unrunnable_proof_blocks_and_says_why():
    with tempfile.TemporaryDirectory() as tmp:
        bad = {"kind": "vibes", "params": {}}
        payload = adjudicate.adjudicate_round(round_with(Path(tmp), [finding(proof=bad)]), None)
    record = payload["findings"][0]
    assert record["state"] == "unrunnable"
    assert record["blocks_certification"] is True
    assert "could not run" in record["reason"]


def test_a_control_that_also_passes_is_unsettled_not_confirmed():
    """The vacuity case: a check that supports the claim and its negation proves nothing."""
    with tempfile.TemporaryDirectory() as tmp:
        vacuous = {"kind": "absent", "params": {"pattern": "nothing_matches_this"},
                   "control": {"params": {"pattern": "nothing_matches_this"}}}
        payload = adjudicate.adjudicate_round(round_with(Path(tmp), [finding(proof=vacuous)]), None)
    record = payload["findings"][0]
    assert record["admission"] == "control_did_not_fail"
    assert record["state"] == "unsettled"
    assert "opposite" in record["reason"]


# --- the blocking rule is the gate's, not a copy ------------------------------------


def test_high_blocks_in_security_and_not_in_performance():
    with tempfile.TemporaryDirectory() as tmp:
        findings = [
            finding(id="A", dimension="security", severity="high"),
            finding(id="B", dimension="performance", severity="high"),
            finding(id="C", dimension="performance", severity="critical"),
            finding(id="D", dimension="security", severity="medium"),
        ]
        payload = adjudicate.adjudicate_round(round_with(Path(tmp), findings), None)
    blocking = {r["id"]: r["blocks_certification"] for r in payload["findings"]}
    assert blocking == {"A": True, "B": False, "C": True, "D": False}


def test_a_closed_finding_never_blocks():
    with tempfile.TemporaryDirectory() as tmp:
        payload = adjudicate.adjudicate_round(
            round_with(Path(tmp), [finding(status="fixed", severity="critical")]), None)
    assert payload["findings"][0]["blocks_certification"] is False


# --- the report ---------------------------------------------------------------------


def test_the_summary_counts_every_state():
    with tempfile.TemporaryDirectory() as tmp:
        findings = [finding(id="A", proof=CLEAN_PROOF),
                    finding(id="B", proof={"kind": "absent", "params": {"pattern": "orphan_helper"},
                                           "control": {"params": {"pattern": "orphan_helper"}}}),
                    finding(id="C")]
        payload = adjudicate.adjudicate_round(round_with(Path(tmp), findings), None)
    assert payload["summary"] == {
        "findings": 3, "confirmed": 1, "refuted": 1, "unsettled": 1, "unrunnable": 0,
        "blocking": 2, "blocking_confirmed": 1, "blocking_unsettled": 1,
        "certification_blocked": True,
    }


def test_the_report_says_it_is_not_enforced():
    with tempfile.TemporaryDirectory() as tmp:
        payload = adjudicate.adjudicate_round(round_with(Path(tmp), [finding()]), None)
        text = adjudicate.render(payload)
    assert payload["enforced"] is False
    assert "does not change the verdict" in text
    assert "[unsettled]" in text


def test_adjudication_is_deterministic():
    with tempfile.TemporaryDirectory() as tmp:
        round_dir = round_with(Path(tmp), [finding(id="B"), finding(id="A", severity="low")])
        first = adjudicate.adjudicate_round(round_dir, None)
        second = adjudicate.adjudicate_round(round_dir, None)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_it_writes_proofs_json_beside_the_round_and_never_reads_it_back():
    with tempfile.TemporaryDirectory() as tmp:
        round_dir = round_with(Path(tmp), [finding()])
        adjudicate.adjudicate_round(round_dir, None)
        assert (round_dir / "proofs.json").is_file()
        again = adjudicate.adjudicate_round(round_dir, None)
    assert again["summary"]["findings"] == 1, "proofs.json was re-read as a reviewer file"


# --- locating -----------------------------------------------------------------------


def test_a_run_directory_picks_the_highest_round_numerically():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        round_with(root, [finding(id="two")], name="round-2")
        round_with(root, [finding(id="ten")], name="round-10")
        payload = adjudicate.adjudicate_round(root / "run", None)
    assert payload["round"] == "round-10"
    assert [r["id"] for r in payload["findings"]] == ["ten"]


def test_a_merged_round_is_read_once_not_twice():
    """After a merge the directory holds both the samples and the merged files. Adjudicating every
    file counted each finding twice — 30 records for 25 findings on a five-sample round."""
    with tempfile.TemporaryDirectory() as tmp:
        round_dir = round_with(Path(tmp), [finding(id="dim-1")])
        (round_dir / "generalist-1.json").write_text(json.dumps(
            {"reviewer": "council-generalist", "findings": [finding(id="sample-1")]}),
            encoding="utf-8")
        payload = adjudicate.adjudicate_round(round_dir, None)
    assert [r["id"] for r in payload["findings"]] == ["dim-1"], "the merged set wins"


def test_an_unmerged_round_falls_back_to_the_samples():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        repos = root / "repo"
        repos.mkdir()
        tree(repos)
        round_dir = root / "run" / "round-1"
        round_dir.mkdir(parents=True)
        (round_dir / "meta.json").write_text(json.dumps({"repo": str(repos)}), encoding="utf-8")
        (round_dir / "generalist-1.json").write_text(json.dumps(
            {"reviewer": "council-generalist", "findings": [finding(id="sample-1")]}),
            encoding="utf-8")
        payload = adjudicate.adjudicate_round(round_dir, None)
    assert [r["id"] for r in payload["findings"]] == ["sample-1"]


def test_a_round_directory_works_on_its_own():
    with tempfile.TemporaryDirectory() as tmp:
        round_dir = round_with(Path(tmp), [finding()])
        payload = adjudicate.adjudicate_round(round_dir, None)
    assert payload["round"] == "round-1"


def test_samples_and_dimension_files_are_not_both_adjudicated():
    """Superseded rule made explicit: the merged set is the round's findings, the samples are its
    inputs. Reading both counted every claim twice."""
    with tempfile.TemporaryDirectory() as tmp:
        round_dir = round_with(Path(tmp), [finding(id="dim-1")])
        (round_dir / "generalist-2.json").write_text(json.dumps(
            {"reviewer": "council-generalist", "findings": [finding(id="sample-1", severity="low")]}),
            encoding="utf-8")
        payload = adjudicate.adjudicate_round(round_dir, None)
    assert {r["id"] for r in payload["findings"]} == {"dim-1"}


def test_the_merged_dimension_files_win_over_the_samples():
    """Both live in a round dir after a merge; adjudicating both counts every claim twice."""
    with tempfile.TemporaryDirectory() as tmp:
        round_dir = round_with(Path(tmp), [finding(id="merged-1")], name="round-1")
        (round_dir / "generalist-1.json").write_text(json.dumps(
            {"reviewer": "council-generalist",
             "findings": [finding(id="sample-1", severity="low")]}), encoding="utf-8")
        payload = adjudicate.adjudicate_round(round_dir, None)
    assert [r["id"] for r in payload["findings"]] == ["merged-1"], \
        "the merged files are what the gate reads, so they are what gets adjudicated"


def test_no_round_at_all_is_an_error_not_an_empty_pass():
    with tempfile.TemporaryDirectory() as tmp:
        try:
            adjudicate.adjudicate_round(Path(tmp), None)
        except FileNotFoundError as exc:
            assert "no round" in str(exc)
        else:
            raise AssertionError("an empty directory adjudicated clean")


def test_a_missing_repository_is_an_error():
    with tempfile.TemporaryDirectory() as tmp:
        round_dir = round_with(Path(tmp), [finding()], meta=False)
        (round_dir.parent / "meta.json").unlink(missing_ok=True)
        try:
            adjudicate.adjudicate_round(round_dir, None)
        except FileNotFoundError as exc:
            assert "no repository" in str(exc)
        else:
            raise AssertionError("adjudicated without a tree to run proofs against")


# --- the CLI ------------------------------------------------------------------------


def test_the_cli_exits_one_only_when_asked():
    with tempfile.TemporaryDirectory() as tmp:
        round_dir = round_with(Path(tmp), [finding()])
        assert adjudicate.main([str(round_dir)]) == 0
        assert adjudicate.main([str(round_dir), "--fail-on-unproven"]) == 1


def test_the_cli_succeeds_with_fail_on_unproven_when_nothing_blocks():
    with tempfile.TemporaryDirectory() as tmp:
        round_dir = round_with(Path(tmp), [finding(severity="low")])
        assert adjudicate.main([str(round_dir), "--fail-on-unproven"]) == 0


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
