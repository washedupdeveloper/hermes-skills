"""The rebuild's first module set: one verdict, one config, three verbs.

Run standalone: python tests/test_reviewc.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from reviewc import cli, config, verdict  # noqa: E402


def finding(**kw):
    base = dict(id="F-1", dimension="security", severity="high", state="proven")
    base.update(kw)
    return verdict.Finding(**base)


# --- the verdict ------------------------------------------------------------------

def test_no_findings_passes():
    result = verdict.decide([])
    assert result.verdict == "pass", result.reason
    assert verdict.exit_code(result) == 0


def test_a_proven_critical_fails():
    result = verdict.decide([finding(severity="critical")])
    assert result.verdict == "fail"
    assert "block" in result.reason, result.reason
    assert verdict.exit_code(result) == 1


def test_high_blocks_in_security_and_not_in_readability():
    assert verdict.decide([finding(dimension="security", severity="high")]).verdict == "fail"
    assert verdict.decide([finding(dimension="readability", severity="high")]).verdict == "pass"
    assert verdict.decide([finding(dimension="readability", severity="critical")]).verdict == "fail"


def test_an_unsettled_blocking_claim_is_incomplete_not_fail():
    """The one answer that stops a run certifying on the strength of not having looked."""
    result = verdict.decide([finding(state="unsettled")])
    assert result.verdict == "incomplete", result.reason
    assert verdict.exit_code(result) == 3


def test_a_proven_defect_outranks_an_unknown_one():
    result = verdict.decide([finding(state="unsettled"),
                             finding(id="F-2", severity="critical", state="proven")])
    assert result.verdict == "fail", result.reason


def test_a_refuted_finding_never_blocks():
    """A refuted claim is evidence of absence, not a defect."""
    assert verdict.decide([finding(state="refuted")]).verdict == "pass"


def test_a_skipped_proof_kind_makes_it_incomplete():
    result = verdict.decide([], {"dom": "skipped", "diff": "ran"})
    assert result.verdict == "incomplete", result.reason
    assert "dom" in result.reason


def test_the_verdict_carries_no_score():
    payload = verdict.decide([finding()]).to_dict()
    assert "score" not in payload
    assert not any(isinstance(v, float) for v in payload.values()), payload


def test_render_names_the_word_and_the_findings():
    text = verdict.render(verdict.decide([finding(severity="critical", path="a.py", line="4",
                                                   claim="key committed")]))
    assert text.startswith("FAIL:")
    assert "a.py:4" in text and "key committed" in text


def test_render_hides_refuted_findings():
    text = verdict.render(verdict.decide([finding(state="refuted")]))
    assert text.count("\n") == 0, text


# --- the config -------------------------------------------------------------------

def test_an_empty_config_is_the_defaults():
    cfg = config.load(None)
    assert cfg.scope == "whole-repo"
    assert len(cfg.to_dict()) == len(config.KEYS) <= 12


def test_the_key_list_and_the_dataclass_agree():
    assert config.missing_keys() == []


def test_an_unknown_key_is_refused_with_the_list():
    try:
        config.from_mapping({"tommor": 1})
    except config.ConfigError as exc:
        assert "tommor" in str(exc) and "unknown key" in str(exc)
    else:
        raise AssertionError("a typo was accepted")


def test_a_wrong_type_is_refused():
    for bad in ({"timeout_s": "ten"}, {"colour": "yes"}, {"ignore": "build"}):
        try:
            config.from_mapping(bad)
        except config.ConfigError:
            continue
        raise AssertionError(f"accepted {bad}")


def test_an_out_of_range_value_is_refused():
    for bad in ({"timeout_s": 0}, {"passes": 0}, {"max_files": -1}):
        try:
            config.from_mapping(bad)
        except config.ConfigError:
            continue
        raise AssertionError(f"accepted {bad}")


def test_an_enum_is_enforced():
    assert config.from_mapping({"scope": "changed"}).scope == "changed"
    try:
        config.from_mapping({"scope": "partial"})
    except config.ConfigError:
        pass
    else:
        raise AssertionError("an unknown scope was accepted")


def test_a_toml_file_round_trips():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "reviewc.toml"
        path.write_text('scope = "changed"\npasses = 3\n', encoding="utf-8")
        cfg = config.load(path)
    assert cfg.scope == "changed" and cfg.passes == 3


# --- the three verbs --------------------------------------------------------------

def test_exactly_three_verbs():
    assert cli.VERBS == ("review", "explain", "ci")


def test_no_verb_prints_help_and_exits_two():
    assert cli.main([]) == 2


def test_explain_answers_a_topic_without_a_second_tool():
    assert cli.main(["explain", "verdict"]) == 0
    assert cli.main(["explain", "severity"]) == 0


def test_an_unported_verb_says_so_and_does_not_pass():
    """A stub that exits 0 would be a lie about capability."""
    assert cli.main(["ci", "."]) == 3
    assert cli.main(["explain", "proofs", "--self-test"]) == 3


def test_review_reads_a_finished_run_and_exits_by_its_verdict():
    golden = REPO / "tests" / "golden" / "rounds"
    assert cli.main(["review", str(golden / "clean")]) == 0
    assert cli.main(["review", str(golden / "defects")]) in (1, 3)


def test_review_refuses_a_directory_that_is_not_a_review():
    with tempfile.TemporaryDirectory() as tmp:
        assert cli.main(["review", tmp]) == 2


def test_a_bad_config_exits_two_with_the_reason():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "bad.toml"
        path.write_text("nonsense = 1\n", encoding="utf-8")
        assert cli.main(["--config", str(path), "explain", "verdict"]) == 2


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
