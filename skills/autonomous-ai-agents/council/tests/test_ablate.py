"""Tests for ablate.py — the ablation that decides whether the five specialists earn their keep.

Run standalone (no pytest needed):
    python tests/test_ablate.py

Nothing here calls a model. The arms themselves are I/O against `hermes`; what
these tests pin down is the part that decides the verdict — fingerprinting
findings so two arms describing the same defect match, recovering ground truth
from the ladder, and the arithmetic of recall versus false positives. A bug in
any of those produces a confident wrong answer about the architecture, which is
the most expensive kind of bug this repo can have.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS))

_spec = importlib.util.spec_from_file_location("ablate", SCRIPTS / "ablate.py")
ablate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ablate)


# --- the pre-registered rule ------------------------------------------------

def test_margin_is_the_preregistered_value():
    """The rule was fixed before any run; moving it invalidates every result."""
    assert ablate.MARGIN == 1.5, (
        f"MARGIN is {ablate.MARGIN}. The rule in docs/MILESTONES.md M8.5 says 1.5x. "
        "Changing it after a run means the run no longer decides anything."
    )


def test_the_equal_cost_arms_are_actually_equal_cost():
    """`specialists` and `generalist-rubrics` are the pair the rule compares.

    If their turn counts ever diverge, the rule silently compares unequal things.
    """
    spec = ablate.ARMS["specialists"]
    gen = ablate.ARMS["generalist-rubrics"]
    specialist_turns = len(ablate.DIMENSIONS) * spec["samples"]
    generalist_turns = gen["samples"]
    assert specialist_turns == generalist_turns == 5, (specialist_turns, generalist_turns)


def test_bare_arm_has_no_rubrics():
    assert ablate.ARMS["generalist-bare"]["rubrics"] is False
    assert ablate.ARMS["generalist-rubrics"]["rubrics"] is True


# --- fingerprints -----------------------------------------------------------

def test_fingerprint_ignores_case_and_punctuation():
    """Two arms will not phrase the same defect identically; identity must not care."""
    a = {"location": {"path": "src/a.py", "line_range": "10"},
         "claim": "A live API credential is committed as a plaintext literal!"}
    b = {"location": {"path": "src/a.py", "line_range": "10"},
         "claim": "a live api credential is committed as a plaintext literal"}
    assert ablate._fingerprint(a) == ablate._fingerprint(b)


def test_fingerprint_separates_different_locations():
    a = {"location": {"path": "src/a.py", "line_range": "10"}, "claim": "same words here"}
    b = {"location": {"path": "src/b.py", "line_range": "10"}, "claim": "same words here"}
    assert ablate._fingerprint(a) != ablate._fingerprint(b)


def test_fingerprint_survives_a_missing_location():
    """A malformed finding must not crash the collector — it just sorts to the end."""
    assert ablate._fingerprint({}) == "||"


# --- line ranges ------------------------------------------------------------

def test_lines_of_parses_a_single_line_and_a_range():
    assert ablate._lines_of("12") == (12, 12)
    assert ablate._lines_of("12-18") == (12, 18)


def test_lines_of_tolerates_junk():
    assert ablate._lines_of("") == (0, 0)
    assert ablate._lines_of(None) == (0, 0)
    assert ablate._lines_of("n/a") == (0, 0)


# --- matching a finding to ground truth -------------------------------------

def test_matches_on_path_and_overlapping_lines():
    truth = {"path": "src/a.py", "line_range": "10-12", "kind": "changed"}
    assert ablate.matches({"location": {"path": "src/a.py", "line_range": "11"}}, truth)


def test_matches_respects_the_slack_window():
    truth = {"path": "src/a.py", "line_range": "10", "kind": "changed"}
    assert ablate.matches({"location": {"path": "src/a.py", "line_range": "13"}}, truth)
    assert not ablate.matches({"location": {"path": "src/a.py", "line_range": "14"}}, truth)


def test_matches_a_new_file_on_path_alone():
    """A planted file has no 'changed lines' — the file itself is the defect."""
    truth = {"path": "src/seeded_secret_0.py", "line_range": "1", "kind": "new-file"}
    assert ablate.matches({"location": {"path": "src/seeded_secret_0.py", "line_range": "1"}},
                          truth)


def test_matches_ignores_a_leading_dot_slash():
    truth = {"path": "src/a.py", "line_range": "5", "kind": "changed"}
    assert ablate.matches({"location": {"path": "./src/a.py", "line_range": "5"}}, truth)


def test_matches_gives_benefit_of_the_doubt_without_a_line():
    """A finding naming the right file but no usable line is not a false positive."""
    truth = {"path": "src/a.py", "line_range": "10", "kind": "changed"}
    assert ablate.matches({"location": {"path": "src/a.py", "line_range": ""}}, truth)


# --- reading what an arm produced -------------------------------------------

def _write(tmp: Path, name: str, text: str) -> Path:
    p = tmp / name
    p.write_text(text, encoding="utf-8", newline="\n")
    return p


def test_read_findings_takes_plain_json():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        p = _write(tmp, "f.json", json.dumps({"findings": [{"id": "A"}]}))
        assert ablate.read_findings(p) == [{"id": "A"}]


def test_read_findings_tolerates_a_code_fence():
    """Models wrap JSON in fences however you ask; that must not lose the findings."""
    with tempfile.TemporaryDirectory() as td:
        p = _write(Path(td), "f.json", '```json\n{"findings": [{"id": "A"}]}\n```')
        assert ablate.read_findings(p) == [{"id": "A"}]


def test_read_findings_tolerates_leading_prose():
    with tempfile.TemporaryDirectory() as td:
        p = _write(Path(td), "f.json", 'Here is my review.\n{"findings": [{"id": "A"}]}\nDone.')
        assert ablate.read_findings(p) == [{"id": "A"}]


def test_read_findings_returns_empty_on_garbage():
    with tempfile.TemporaryDirectory() as td:
        assert ablate.read_findings(_write(Path(td), "f.json", "no json at all")) == []


def test_read_findings_returns_empty_when_the_file_is_missing():
    assert ablate.read_findings(Path("/nonexistent/findings.json")) == []


def test_collect_dedupes_across_samples():
    """Five samples of one generalist will overlap; distinct is what the rule counts."""
    with tempfile.TemporaryDirectory() as td:
        arm = Path(td)
        same = {"location": {"path": "src/a.py", "line_range": "10"}, "claim": "one defect here"}
        other = {"location": {"path": "src/b.py", "line_range": "2"}, "claim": "a second defect"}
        _write(arm, "findings-1.json", json.dumps({"findings": [same, other]}))
        _write(arm, "findings-2.json", json.dumps({"findings": [same]}))
        c = ablate.collect(arm)
        assert c["total"] == 3, c
        assert c["distinct"] == 2, c


# --- scoring ----------------------------------------------------------------

def test_score_arm_counts_recall_and_false_positives():
    truth = [{"path": "src/a.py", "line_range": "10", "kind": "changed"},
             {"path": "src/b.py", "line_range": "5", "kind": "new-file"}]
    collected = {"distinct": 3, "total": 3, "findings": [
        {"location": {"path": "src/a.py", "line_range": "10"}, "claim": "x"},
        {"location": {"path": "src/b.py", "line_range": "1"}, "claim": "y"},
        {"location": {"path": "src/z.py", "line_range": "99"}, "claim": "hallucinated"},
    ]}
    s = ablate.score_arm(collected, truth, known_good=False)
    assert s["true"] == 2, s
    assert s["false_positives"] == 1, s
    assert s["recall"] == 1.0, s
    assert s["found_of_planted"] == "2/2", s


def test_score_arm_on_the_clean_rung_makes_every_finding_a_false_positive():
    """Rung 0 is declared known-good, so recall is undefined and precision is everything."""
    collected = {"distinct": 2, "total": 2, "findings": [{}, {}]}
    s = ablate.score_arm(collected, None, known_good=True)
    assert s["false_positives"] == 2, s
    assert s["recall"] is None, s


def test_score_arm_reports_unknown_without_truth():
    collected = {"distinct": 2, "total": 2, "findings": [{}, {}]}
    s = ablate.score_arm(collected, None, known_good=False)
    assert s["true"] is None and s["false_positives"] is None, s


def test_recall_counts_planted_defects_found_not_findings():
    """Two findings pointing at ONE planted defect is recall 1/2, not 2/2."""
    truth = [{"path": "src/a.py", "line_range": "10", "kind": "changed"},
             {"path": "src/b.py", "line_range": "5", "kind": "changed"}]
    collected = {"distinct": 2, "total": 2, "findings": [
        {"location": {"path": "src/a.py", "line_range": "10"}, "claim": "one way to say it"},
        {"location": {"path": "src/a.py", "line_range": "11"}, "claim": "another way"},
    ]}
    s = ablate.score_arm(collected, truth, known_good=False)
    assert s["recall"] == 0.5, s
    assert s["true"] == 1, s          # ONE planted defect found, however many ways it is said
    assert s["true_findings"] == 2, s  # both findings did point at it
    assert s["false_positives"] == 0, s


# --- the signal-quality pair -------------------------------------------------
# M8 lists SNR and usefulness rate as first-class metrics because recall can be
# bought with volume, and a high-recall agent that gets there by reporting more is a
# trust hazard (research/sota-multi-agent-code-review.md §3.6). Volume must not read
# as improvement.

def test_score_arm_reports_snr_and_usefulness():
    truth = [{"path": "src/a.py", "line_range": "10", "kind": "changed"},
             {"path": "src/b.py", "line_range": "5", "kind": "new-file"}]
    collected = {"distinct": 3, "total": 3, "findings": [
        {"location": {"path": "src/a.py", "line_range": "10"}, "claim": "x"},
        {"location": {"path": "src/b.py", "line_range": "1"}, "claim": "y"},
        {"location": {"path": "src/z.py", "line_range": "99"}, "claim": "noise"},
    ]}
    s = ablate.score_arm(collected, truth, known_good=False)
    assert s["signal"] == 2, s
    assert s["noise"] == 1, s
    assert s["snr"] == 2.0, s
    assert s["usefulness_rate"] == 0.6667, s


def test_volume_lowers_snr_at_equal_recall():
    """The anti-gaming property: same recall, more noise, strictly worse.

    This is the reading the ablation's rule could not make before -- both arms here
    have recall 1.0, so a recall-only verdict calls them equal. They are not.
    """
    truth = [{"path": "src/a.py", "line_range": "10", "kind": "changed"}]
    focused = {"distinct": 1, "total": 1, "findings": [
        {"location": {"path": "src/a.py", "line_range": "10"}, "claim": "the defect"},
    ]}
    verbose = {"distinct": 5, "total": 5, "findings": [
        {"location": {"path": "src/a.py", "line_range": "10"}, "claim": "the defect"},
        {"location": {"path": "src/a.py", "line_range": "40"}, "claim": "noise 1"},
        {"location": {"path": "src/a.py", "line_range": "60"}, "claim": "noise 2"},
        {"location": {"path": "src/b.py", "line_range": "3"}, "claim": "noise 3"},
        {"location": {"path": "src/b.py", "line_range": "9"}, "claim": "noise 4"},
    ]}
    a = ablate.score_arm(focused, truth, known_good=False)
    b = ablate.score_arm(verbose, truth, known_good=False)

    assert a["recall"] == b["recall"] == 1.0, (a, b)
    assert a["true"] == b["true"] == 1, (a, b)

    # The focused arm has no noise at all; the verbose one is 1 signal in 5.
    assert a["snr"] is None and a["noise"] == 0, a
    assert b["snr"] == 0.25, b
    assert a["usefulness_rate"] == 1.0, a
    assert b["usefulness_rate"] == 0.2, b
    assert b["usefulness_rate"] < a["usefulness_rate"], "volume read as improvement"


def test_no_noise_is_distinguishable_from_unknown():
    """`snr` is None both when there is no noise and when truth is unknown, so the
    fields beside it have to tell the two apart -- otherwise 'best possible' reads
    as 'no information'."""
    truth = [{"path": "src/a.py", "line_range": "10", "kind": "changed"}]
    clean = {"distinct": 1, "total": 1, "findings": [
        {"location": {"path": "src/a.py", "line_range": "10"}, "claim": "the defect"},
    ]}
    s = ablate.score_arm(clean, truth, known_good=False)
    assert s["snr"] is None and s["signal"] == 1 and s["noise"] == 0, s

    unknown = ablate.score_arm(clean, None, known_good=False)
    assert unknown["snr"] is None and unknown["signal"] is None, unknown


def test_clean_rung_scores_zero_snr_not_unknown():
    """Nothing is planted, so every finding is noise: SNR 0, not undefined."""
    collected = {"distinct": 2, "total": 2, "findings": [{}, {}]}
    s = ablate.score_arm(collected, None, known_good=True)
    assert s["signal"] == 0, s
    assert s["noise"] == 2, s
    assert s["snr"] == 0.0, s
    assert s["usefulness_rate"] == 0.0, s


# --- ground truth from the ladder -------------------------------------------

def test_planted_defects_finds_a_new_file_and_a_changed_file():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        rung0, rungN = root / "level-0", root / "level-8"
        (rung0 / "src").mkdir(parents=True)
        (rungN / "src").mkdir(parents=True)
        (rung0 / "src" / "keep.py").write_text("a = 1\nb = 2\n", encoding="utf-8")
        (rungN / "src" / "keep.py").write_text("a = 1\nb = 999\n", encoding="utf-8")
        (rungN / "src" / "seeded_secret_0.py").write_text("KEY = 'sk_live_x'\n", encoding="utf-8")

        truth = ablate.planted_defects(rung0, rungN)
        by_path = {t["path"]: t for t in truth}
        assert set(by_path) == {"src/keep.py", "src/seeded_secret_0.py"}, by_path
        assert by_path["src/seeded_secret_0.py"]["kind"] == "new-file"
        assert by_path["src/keep.py"]["kind"] == "changed"
        assert by_path["src/keep.py"]["line_range"] == "2-2", by_path["src/keep.py"]


def test_planted_defects_ignores_an_identical_tree():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        rung0, rungN = root / "a", root / "b"
        rung0.mkdir()
        rungN.mkdir()
        (rung0 / "x.py").write_text("same\n", encoding="utf-8")
        (rungN / "x.py").write_text("same\n", encoding="utf-8")
        assert ablate.planted_defects(rung0, rungN) == []


# --- the prompt -------------------------------------------------------------

def test_the_generalist_prompt_lists_every_dimension():
    """An arm that silently forgets a dimension loses for the wrong reason."""
    prompt = ablate.GENERALIST_PROMPT.format(
        repo="r", scope="whole-repo", sha="abc", stacks="nix",
        dimensions=", ".join(ablate.DIMENSIONS), rubric_instruction="R",
        probe_json="[]", out_path="/tmp/x.json", profile="p", prefix="GEN")
    for dimension in ablate.DIMENSIONS:
        assert dimension in prompt, dimension


def test_the_bare_instruction_does_not_name_the_rubrics():
    """The bare arm is the control for rubric knowledge; leaking a rubric name breaks it."""
    for rubric in ablate.RUBRICS:
        assert rubric not in ablate.NO_RUBRIC_INSTRUCTION, rubric
    # The template carries a {rubrics} placeholder, so check the FORMATTED form.
    with_rubrics = ablate.RUBRIC_INSTRUCTION.format(rubrics=", ".join(ablate.RUBRICS))
    for rubric in ablate.RUBRICS:
        assert rubric in with_rubrics, rubric


# --- the labelling sheet ----------------------------------------------------

def test_label_sheet_lists_every_distinct_finding_once():
    """The sheet is the operator's whole job; a missing row is an unmeasured finding."""
    with tempfile.TemporaryDirectory() as td:
        run = Path(td)
        (run / "single").mkdir()
        (run / "specialists").mkdir()
        shared = {"location": {"path": "src/a.py", "line_range": "10"},
                  "severity": "high", "claim": "the same defect"}
        only = {"location": {"path": "src/b.py", "line_range": "3"},
                "severity": "low", "claim": "a different defect"}
        _write(run / "single", "findings-1.json", json.dumps({"findings": [shared]}))
        _write(run / "specialists", "findings-security.json",
               json.dumps({"findings": [shared, only]}))
        _write(run, "ablation.json", json.dumps({
            "repo": "/tmp/x", "sha": "abc",
            "arms": {"single": {}, "specialists": {}},
        }))

        args = SimpleNamespace(run=str(run))
        ablate.cmd_label(None, args)

        text = (run / "LABELS.md").read_text(encoding="utf-8")
        assert text.count("| `src/a.py:10`") == 1, text   # deduped across arms
        assert text.count("| `src/b.py:3`") == 1, text
        assert "single, specialists" in text, text        # provenance is recorded


def test_label_sheet_escapes_a_pipe_in_a_claim():
    """An unescaped pipe in a claim breaks the table and silently loses a row."""
    with tempfile.TemporaryDirectory() as td:
        run = Path(td)
        (run / "single").mkdir()
        _write(run / "single", "findings-1.json", json.dumps({"findings": [
            {"location": {"path": "a.py", "line_range": "1"},
             "severity": "low", "claim": "a | b"}]}))
        _write(run, "ablation.json", json.dumps(
            {"repo": "/tmp/x", "sha": "abc", "arms": {"single": {}}}))

        args = SimpleNamespace(run=str(run))
        ablate.cmd_label(None, args)
        text = (run / "LABELS.md").read_text(encoding="utf-8")
        assert "a \\| b" in text, text


def test_label_sheet_blind_withholds_provenance():
    """Judging a finding must not depend on which arm reported it."""
    with tempfile.TemporaryDirectory() as td:
        run = Path(td)
        (run / "specialists").mkdir()
        _write(run / "specialists", "findings-security.json", json.dumps({"findings": [
            {"location": {"path": "a.py", "line_range": "1"},
             "severity": "high", "claim": "a real defect"}]}))
        _write(run, "ablation.json", json.dumps(
            {"repo": "/tmp/x", "sha": "abc", "arms": {"specialists": {}}}))

        ablate.cmd_label(None, SimpleNamespace(run=str(run), blind=True))
        text = (run / "LABELS.md").read_text(encoding="utf-8")
        assert "arms that found it" not in text, text
        assert "specialists" not in text, "the arm name leaked into a blind sheet"
        assert "a real defect" in text, text


def test_the_rule_says_undecided_when_no_arm_found_anything():
    """0 vs 0 is not a win for the specialists; the corpus just failed to discriminate."""
    with tempfile.TemporaryDirectory() as td:
        run = Path(td)
        for arm in ("generalist-rubrics", "specialists"):
            (run / arm).mkdir()
        _write(run, "ablation.json", json.dumps(
            {"repo": "/tmp/x", "sha": "abc",
             "arms": {"generalist-rubrics": {}, "specialists": {}}}))

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ablate.cmd_score(None, SimpleNamespace(run=str(run), truth=None,
                                                   known_good=True))
        out = buf.getvalue()
        assert "UNDECIDED" in out, out
        assert "KEEP" not in out, "0 vs 0 must not read as a win for the specialists"


# --- scoring against an injected manifest -----------------------------------

def test_scores_against_an_injected_manifest_without_a_kind_field():
    """The injected manifest has no `kind`; matching must fall through to line
    ranges rather than silently returning no hits."""
    truth = [
        {"id": "SEC-1", "path": "modules/base-system/default.nix", "line_range": "112",
         "dimension": "security", "severity": "critical", "claim": "password auth on"},
        {"id": "COR-2", "path": "machines/host/configuration.nix",
         "line_range": "107", "dimension": "correctness", "severity": "medium",
         "claim": "/mnt no longer pruned"},
    ]
    collected = {"distinct": 3, "total": 3, "findings": [
        {"location": {"path": "modules/base-system/default.nix", "line_range": "112"},
         "claim": "ssh password auth enabled"},
        {"location": {"path": "machines/host/configuration.nix",
                      "line_range": "109"}, "claim": "/mnt missing from prunePaths"},
        {"location": {"path": "flake.nix", "line_range": "1"}, "claim": "unrelated"},
    ]}
    s = ablate.score_arm(collected, truth, known_good=False)
    assert s["true"] == 2, s
    assert s["recall"] == 1.0, s
    assert s["false_positives"] == 1, s


def test_an_injected_manifest_entry_is_matched_within_the_slack_window():
    """A reviewer naming the list rather than the exact line must still count."""
    truth = [{"path": "a.nix", "line_range": "100", "dimension": "security",
              "severity": "high", "claim": "x"}]
    for reported in ("100", "102", "98"):
        collected = {"distinct": 1, "total": 1, "findings": [
            {"location": {"path": "a.nix", "line_range": reported}, "claim": "x"}]}
        s = ablate.score_arm(collected, truth, known_good=False)
        assert s["true"] == 1, (reported, s)


def test_assign_picks_the_nearest_defect_not_the_first_in_the_manifest():
    """Two injected defects within the slack window of each other must not be
    conflated: first-match attribution credits whichever the manifest lists first,
    double-counting one defect and losing the other."""
    truth = [
        {"path": "a.nix", "line_range": "46", "dimension": "performance",
         "severity": "low", "claim": "the setting"},
        {"path": "a.nix", "line_range": "49", "dimension": "readability",
         "severity": "low", "claim": "the commented-out block"},
    ]
    # A finding at 49-52 describes the commented-out block, not the setting at 46.
    assert ablate.assign({"location": {"path": "a.nix", "line_range": "49-52"}},
                         truth) == 1
    assert ablate.assign({"location": {"path": "a.nix", "line_range": "46"}},
                         truth) == 0


def test_assign_returns_none_for_an_unrelated_finding():
    truth = [{"path": "a.nix", "line_range": "10", "dimension": "security",
              "severity": "high", "claim": "x"}]
    assert ablate.assign({"location": {"path": "a.nix", "line_range": "900"}},
                         truth) is None
    assert ablate.assign({"location": {"path": "other.nix", "line_range": "10"}},
                         truth) is None


def test_two_findings_on_two_close_defects_score_both():
    """The regression this fixes: a mis-assignment made one defect look
    double-counted and the other missed."""
    truth = [
        {"path": "a.nix", "line_range": "46", "dimension": "performance",
         "severity": "low", "claim": "the setting"},
        {"path": "a.nix", "line_range": "49", "dimension": "readability",
         "severity": "low", "claim": "the commented-out block"},
    ]
    collected = {"distinct": 2, "total": 2, "findings": [
        {"location": {"path": "a.nix", "line_range": "46"}, "claim": "buffer size"},
        {"location": {"path": "a.nix", "line_range": "49-52"}, "claim": "commented block"},
    ]}
    s = ablate.score_arm(collected, truth, known_good=False)
    assert s["true"] == 2, s
    assert s["recall"] == 1.0, s
    assert s["false_positives"] == 0, s


def test_recall_credits_a_defect_any_finding_points_at():
    """The regression that under-counted a real run: two defects on adjacent lines
    (46 and 47), one finding spanning both. Exclusive nearest-match credited the
    first and reported the second as missed, even though the arm had named it."""
    truth = [
        {"path": "a.nix", "line_range": "46", "dimension": "security",
         "severity": "high", "claim": "trusted-users widened"},
        {"path": "a.nix", "line_range": "47", "dimension": "performance",
         "severity": "low", "claim": "download buffer raised"},
    ]
    collected = {"distinct": 1, "total": 1, "findings": [
        {"location": {"path": "a.nix", "line_range": "43-48"},
         "claim": "trusted-users is widened to @users"}]}
    s = ablate.score_arm(collected, truth, known_good=False)
    assert s["true"] == 2, (s, "a finding covering both defects must credit both")
    assert s["recall"] == 1.0, s


def test_recall_is_not_inflated_by_a_finding_nowhere_near_a_defect():
    truth = [{"path": "a.nix", "line_range": "10", "dimension": "security",
              "severity": "high", "claim": "x"}]
    collected = {"distinct": 1, "total": 1, "findings": [
        {"location": {"path": "a.nix", "line_range": "900"}, "claim": "unrelated"}]}
    s = ablate.score_arm(collected, truth, known_good=False)
    assert s["true"] == 0, s
    assert s["false_positives"] == 1, s


def test_a_finding_does_not_match_a_defect_in_another_file():
    """The regression that hid every false positive: `_distance` compared only line
    numbers, so a finding in one file matched a defect in another whenever the lines
    were close, and no arm ever showed a false positive."""
    truth = [{"path": "src/a.py", "line_range": "10", "kind": "changed"}]
    collected = {"distinct": 1, "total": 1, "findings": [
        {"location": {"path": "src/z.py", "line_range": "10"}, "claim": "elsewhere"}]}
    s = ablate.score_arm(collected, truth, known_good=False)
    assert s["true"] == 0, s
    assert s["false_positives"] == 1, s


def test_a_new_file_defect_does_not_match_a_finding_in_another_file():
    """A `new-file` entry has no line range, so it matched everything until the path
    check was added."""
    truth = [{"path": "src/seeded_secret_0.py", "line_range": "1", "kind": "new-file"}]
    collected = {"distinct": 1, "total": 1, "findings": [
        {"location": {"path": "src/other.py", "line_range": "99"}, "claim": "elsewhere"}]}
    s = ablate.score_arm(collected, truth, known_good=False)
    assert s["true"] == 0, s
    assert s["false_positives"] == 1, s



def test_the_ablation_prompt_asks_for_tools_run():
    """Same contract as the loop's prompt. The ablation measures recall, so a
    missing tools_run would not change the verdict -- but the score it reports
    would be LLM-only, and that is a number the run prints."""
    assert '"tools_run"' in ablate.GENERALIST_PROMPT
    assert "parsed" in ablate.GENERALIST_PROMPT


# --- path separators are not a platform detail ------------------------------

def test_planted_defects_writes_paths_the_same_way_on_every_platform():
    """Truth paths are repo-relative, so they have ONE canonical spelling.

    `str(Path.relative_to(...))` is platform-dependent: it yields `src\\keep.py` on
    Windows and `src/keep.py` elsewhere. Reviewers write `src/keep.py` (that is the
    shape the prompt documents), so on Windows EVERY finding failed `_distance`'s
    equality check — recall 0, and every finding counted as a false positive, for
    every arm, silently. This test would have caught it on any platform.
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        rung0, rungN = root / "level-0", root / "level-8"
        (rung0 / "src").mkdir(parents=True)
        (rungN / "src").mkdir(parents=True)
        (rung0 / "src" / "keep.py").write_text("a = 1\nb = 2\n", encoding="utf-8")
        (rungN / "src" / "keep.py").write_text("a = 1\nb = 9\n", encoding="utf-8")
        (rungN / "src" / "new.py").write_text("x = 1\n", encoding="utf-8")

        truth = ablate.planted_defects(rung0, rungN)
        assert truth, "the fixture must plant something"
        for entry in truth:
            assert "\\" not in entry["path"], entry
        assert {t["path"] for t in truth} == {"src/keep.py", "src/new.py"}, truth


def test_a_finding_written_with_windows_separators_still_matches():
    """The comparison tolerates either separator.

    Making the truth canonical is not enough on its own: a reviewer handed a Windows
    checkout may echo back backslashes, and that must not read as a miss. Both sides
    are normalised, so the match depends on the path, not on who wrote it.
    """
    truth = [{"path": "src/keep.py", "line_range": "2-2", "kind": "changed"}]
    for written in ("src/keep.py", "src\\keep.py", "./src/keep.py"):
        finding = {"location": {"path": written, "line_range": "2"}}
        assert ablate.is_true(finding, truth), written
        assert ablate.found_by({"findings": [finding]}, truth) == {0}, written


def test_fingerprints_do_not_depend_on_the_separator():
    """Two arms describing the same defect must fingerprint identically.

    The fingerprint is what dedupes findings across arms. If `src/keep.py` and
    `src\\keep.py` fingerprint differently, an arm's distinct-finding count is
    inflated and it looks more productive than it is — the arithmetic the ablation
    verdict rests on.
    """
    a = {"location": {"path": "src/keep.py", "line_range": "2"}, "claim": "one defect"}
    b = {"location": {"path": "src\\keep.py", "line_range": "2"}, "claim": "one defect"}
    assert ablate._fingerprint(a) == ablate._fingerprint(b)


def test_norm_path_is_the_one_place_that_knows_about_separators():
    """The canonical form, pinned directly so a future edit cannot quietly drop it."""
    assert ablate._norm_path("src\\keep.py") == "src/keep.py"
    assert ablate._norm_path("src/keep.py") == "src/keep.py"
    assert ablate._norm_path("./src/keep.py") == "src/keep.py"
    assert ablate._norm_path("a\\b\\c.py") == "a/b/c.py"
    assert ablate._norm_path("  src/keep.py  ") == "src/keep.py"
    assert ablate._norm_path(None) == ""
    assert ablate._norm_path("") == ""
if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok    {name}")
            except AssertionError as exc:
                failures += 1
                print(f"  FAIL  {name}: {exc}")
    print(f"\n{failures} failure(s)")
    sys.exit(1 if failures else 0)
