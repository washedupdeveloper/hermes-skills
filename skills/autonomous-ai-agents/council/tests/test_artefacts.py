"""The reader, and the purpose register that keeps modules honest.

Run standalone: python tests/test_artefacts.py
"""
from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from reviewc import artefacts, verdict  # noqa: E402

GOLDEN = REPO / "tests" / "golden"
#: Hand-built, deliberately outside tests/golden/: `scripts/golden.py` hashes every file under that
#: tree, so a fixture added there makes `council golden --check` report drift — it would break the
#: M11.0 freeze it is meant to protect.
ADJUDICATED = REPO / "tests" / "fixtures" / "adjudicated"


def write_round(tmp: Path, dimension: str, payload: dict) -> Path:
    tmp.mkdir(parents=True, exist_ok=True)
    (tmp / f"{dimension}.json").write_text(json.dumps(payload), encoding="utf-8")
    return tmp


def finding(severity="high", line="4", path="a.nix", claim="c", ident="SEC-0001"):
    return {"id": ident, "dimension": "security", "severity": severity, "status": "open",
            "claim": claim, "location": {"path": path, "line_range": line}}


def test_a_missing_directory_is_named_not_guessed():
    try:
        artefacts.load(Path("/nonexistent/run"))
    except artefacts.ArtefactError as exc:
        assert "does not exist" in str(exc)
    else:
        raise AssertionError("a missing tree was accepted")


def test_a_directory_without_a_round_is_refused():
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "README.md").write_text("nothing here", encoding="utf-8")
        try:
            artefacts.load(Path(tmp))
        except artefacts.ArtefactError as exc:
            assert "no round" in str(exc)
        else:
            raise AssertionError("an empty directory produced a review")


def test_an_unproven_claim_is_unsettled_not_refuted():
    with tempfile.TemporaryDirectory() as tmp:
        write_round(Path(tmp), "security", {"findings": [finding()]})
        loaded = artefacts.load(Path(tmp))
    assert [f.state for f in loaded.findings] == ["unsettled"]
    assert verdict.decide(loaded.findings, loaded.proof_coverage).verdict == "incomplete"


def test_an_unreadable_severity_is_not_assumed_low():
    """Unknown cannot be assumed safe: it becomes the most severe, so it gets looked at."""
    with tempfile.TemporaryDirectory() as tmp:
        write_round(Path(tmp), "security", {"findings": [finding(severity="SEV-1")]})
        loaded = artefacts.load(Path(tmp))
    assert loaded.findings[0].severity == "critical"


def test_two_findings_sharing_an_id_stay_distinct():
    """v1 reuses ids inside a file — two SEC-0001s were measured in real output."""
    with tempfile.TemporaryDirectory() as tmp:
        write_round(Path(tmp), "security",
                    {"findings": [finding(line="8"), finding(line="15")]})
        loaded = artefacts.load(Path(tmp))
    ids = {f.id for f in loaded.findings}
    assert len(ids) == 2, ids
    assert any("name more than one finding" in note for note in loaded.notes)


def test_an_ambiguous_id_proves_neither_finding():
    """A proof of one is not a proof of the other — the same rule as the place check."""
    with tempfile.TemporaryDirectory() as tmp:
        root = write_round(Path(tmp), "security",
                           {"findings": [finding(line="8"), finding(line="15")]})
        (root / "adjudication.json").write_text(json.dumps(
            {"claims": [{"id": "SEC-0001", "state": "confirmed"}]}), encoding="utf-8")
        loaded = artefacts.load(root)
    assert [f.state for f in loaded.findings] == ["unsettled", "unsettled"]
    assert verdict.decide(loaded.findings, loaded.proof_coverage).verdict == "incomplete"


def test_a_round_with_no_adjudication_says_so():
    with tempfile.TemporaryDirectory() as tmp:
        write_round(Path(tmp), "security", {"findings": []})
        loaded = artefacts.load(Path(tmp))
    assert loaded.adjudicated is False
    assert any("no adjudication" in note for note in loaded.notes)


def test_a_tool_that_did_not_run_is_a_gap_not_a_pass():
    with tempfile.TemporaryDirectory() as tmp:
        write_round(Path(tmp), "security", {"findings": [], "tools_run": [
            {"tool": "statix", "ran": False, "parsed": True},
            {"tool": "gitleaks", "ran": True, "parsed": True},
        ]})
        loaded = artefacts.load(Path(tmp))
    assert loaded.proof_coverage["statix"] == "unrunnable"
    assert verdict.decide(loaded.findings, loaded.proof_coverage).verdict == "incomplete"


def test_a_run_directory_is_read_through_its_latest_round():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_round(root / "round-1", "security", {"findings": [finding(line="1")]})
        write_round(root / "round-2", "security", {"findings": [finding(line="9")]})
        loaded = artefacts.load(root)
    assert [f.line for f in loaded.findings] == ["9"]


def test_an_adjudication_turns_a_claim_into_a_proven_defect():
    with tempfile.TemporaryDirectory() as tmp:
        root = write_round(Path(tmp), "security", {"findings": [finding()]})
        (root / "adjudication.json").write_text(json.dumps(
            {"claims": [{"id": "SEC-0001", "state": "confirmed", "detail": "gitleaks found it"}]}),
            encoding="utf-8")
        loaded = artefacts.load(root)
    assert loaded.findings[0].state == "proven"
    result = verdict.decide(loaded.findings, loaded.proof_coverage)
    assert result.verdict == "fail"
    assert verdict.exit_code(result) == 1


def test_an_unrunnable_proof_leaves_the_claim_unsettled():
    with tempfile.TemporaryDirectory() as tmp:
        root = write_round(Path(tmp), "security", {"findings": [finding()]})
        (root / "adjudication.json").write_text(json.dumps(
            {"claims": [{"id": "SEC-0001", "state": "unrunnable"}]}), encoding="utf-8")
        loaded = artefacts.load(root)
    assert loaded.findings[0].state == "unsettled"
    assert verdict.decide(loaded.findings, loaded.proof_coverage).verdict == "incomplete"


# --- the purpose register ---------------------------------------------------------

def test_every_module_states_its_purpose():
    """A module without a stated purpose is a defect, not a style preference."""
    package = REPO / "reviewc"
    register = (package / "PURPOSE.md").read_text(encoding="utf-8")
    declared = set(re.findall(r"^\|\s*`([a-z_]+\.py)`\s*\|", register, re.MULTILINE))
    modules = {p.name for p in package.glob("*.py")} - {"__init__.py"}
    assert modules == declared, (
        f"missing from PURPOSE.md: {sorted(modules - declared)}; "
        f"no such module: {sorted(declared - modules)}")
    for name in sorted(modules):
        (package / name).read_text(encoding="utf-8")  # readable, and every entry was matched


# --- the differential against the frozen fixtures ---------------------------------

def test_the_clean_fixture_passes_like_v1_says_it_does():
    expect = json.loads((GOLDEN / "expect.json").read_text(encoding="utf-8"))
    assert expect["rounds"]["clean"]["status"] == "satisfied"
    loaded = artefacts.load(GOLDEN / "rounds" / "clean")
    result = verdict.decide(loaded.findings, loaded.proof_coverage)
    assert result.verdict == "pass", (result.reason, loaded.notes)
    assert verdict.exit_code(result) == 0


def test_the_adjudicated_fixture_fails_on_proof_and_outranks_the_unknown():
    """A known defect outranks an unknown one: fail, even though two blocking claims are unsettled."""
    loaded = artefacts.load(ADJUDICATED)
    result = verdict.decide(loaded.findings, loaded.proof_coverage)
    assert loaded.adjudicated is True
    assert result.verdict == "fail", result.reason
    assert verdict.exit_code(result) == 1
    assert [f.id for f in result.blocking()] == ["security:SEC-0001"]
    # Only security and correctness block at `high`: architecture/high is unsettled but not
    # blocking, which is why it is absent here and the correctness one is not.
    assert {f.id for f in result.unsettled()} == {"correctness:COR-0001"}
    assert {f.id: f.state for f in loaded.findings}["architecture:ARC-0001"] == "unsettled"


def test_every_state_is_reachable_in_the_adjudicated_fixture():
    loaded = artefacts.load(ADJUDICATED)
    states = {f.id: f.state for f in loaded.findings}
    assert states["security:SEC-0001"] == "proven"
    assert states["security:SEC-0002"] == "refuted"
    assert states["correctness:COR-0001"] == "unsettled"
    assert states["architecture:ARC-0001"] == "unsettled"  # unrunnable is not a refutation


def test_a_refuted_claim_is_never_reported_as_a_defect():
    loaded = artefacts.load(ADJUDICATED)
    text = verdict.render(verdict.decide(loaded.findings, loaded.proof_coverage))
    assert "SEC-0002" not in text, text


def test_a_proof_that_could_not_run_stays_visible():
    loaded = artefacts.load(ADJUDICATED)
    assert loaded.proof_coverage["dep-graph --modules"] == "unrunnable"
    alone = verdict.decide([], {"dep-graph --modules": "unrunnable"})
    assert alone.verdict == "incomplete"


def test_the_defects_fixture_refuses_to_pass():
    """v1 calls this round `not_satisfied` on a 74.25 aggregate. reviewc reads the claims instead."""
    loaded = artefacts.load(GOLDEN / "rounds" / "defects")
    result = verdict.decide(loaded.findings, loaded.proof_coverage)
    assert result.verdict != "pass", result.reason
    assert [f.id for f in result.unsettled()], "nothing was recorded as unsettled"


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
