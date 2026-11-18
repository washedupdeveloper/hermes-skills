"""The corpus pipeline: plan, collect, derive — and every refusal that stops it lying.

Run standalone (no pytest needed):
    python tests/test_corpus.py
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

for _name in ("score_reviews", "adjudicate", "calibrate", "corpus"):
    _spec = importlib.util.spec_from_file_location(_name, SCRIPTS / f"{_name}.py")
    _module = importlib.util.module_from_spec(_spec)
    sys.modules[_name] = _module
    _spec.loader.exec_module(_module)

score = sys.modules["score_reviews"]
calibrate = sys.modules["calibrate"]
corpus = sys.modules["corpus"]

DIMS = ("security", "correctness", "readability", "architecture", "performance")


def make_run(root: Path, level: int, severities=(), probe_defects=0) -> Path:
    """One round directory for a rung: reviews, probes, and the proofs an adjudication wrote."""
    repo = root / f"tree-{level}"
    (repo / "src").mkdir(parents=True, exist_ok=True)
    (repo / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")
    run = root / f"level-{level}"
    run.mkdir(parents=True, exist_ok=True)
    (run / "meta.json").write_text(json.dumps(
        {"repo": str(repo), "stacks": ["generic"], "target_sha": "a" * 40,
         "require_proof": True}), encoding="utf-8")
    (run / "probes.json").write_text(json.dumps(
        [{"tool": "gitleaks", "ran": True, "parsed": True, "signal": 40.0,
          "findings": [{"path": "src/app.py", "line": 1}] * probe_defects, "note": ""}]),
        encoding="utf-8")
    records = []
    findings = []
    for index, severity in enumerate(severities, start=1):
        ident = f"SEC-{index}"
        findings.append({"id": ident, "dimension": "security", "severity": severity,
                         "status": "open", "location": {"path": "src/app.py", "line_range": "1"},
                         "claim": "seeded"})
        records.append({"id": ident, "dimension": "security", "severity": severity,
                        "state": "confirmed", "location": {"path": "src/app.py",
                                                           "line_range": "1"},
                        "reason": "reproduced", "blocks_certification": True})
    for dimension in DIMS:
        (run / f"{dimension}.json").write_text(json.dumps(
            {"dimension": dimension, "score": 95,
             "findings": findings if dimension == "security" else []}), encoding="utf-8")
    (run / "proofs.json").write_text(json.dumps(
        {"schema_version": 1, "findings": records}), encoding="utf-8")
    return run


def manifest_with(root: Path, specs) -> dict:
    """A corpus manifest pointing at the runs built by *specs*: [(level, label, severities)]."""
    rungs = []
    for level, label, severities in specs:
        run = make_run(root, level, severities)
        result = score.evaluate(run, 0.0)
        rungs.append({"level": level, "label": label, "tree": str(root / f"tree-{level}"),
                      "defects_seeded": len(severities), "seeded": [], "run": str(run),
                      "score": result["aggregate"], "score_source": result["score_source"],
                      "detected": len(severities), "certification": result["certification"]})
    return {"schema_version": 1, "scale": "claims", "base": str(root), "seed": 1, "rungs": rungs}


# --- plan ---------------------------------------------------------------------------
def test_plan_writes_a_manifest_and_marks_level_zero_good():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "base"
        (base / "src").mkdir(parents=True)
        (base / "src" / "app.py").write_text("x = 1\n" * 40, encoding="utf-8")
        document = corpus.plan(base, Path(tmp) / "corpus", ("0", "1"))
    levels = [r["level"] for r in document["rungs"]]
    labels = {r["level"]: r["label"] for r in document["rungs"]}
    assert levels == [0, 1], levels
    assert labels[0] == "good" and labels[1] == "bad", labels
    assert all(r["run"] is None for r in document["rungs"])


def test_plan_writes_the_manifest_to_disk():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "base"
        base.mkdir()
        corpus.plan(base, Path(tmp) / "corpus", ("0",))
        on_disk = json.loads((Path(tmp) / "corpus" / "corpus.json").read_text())
    assert on_disk["rungs"][0]["label"] == "good"


# --- collect ------------------------------------------------------------------------
def test_collect_marks_a_rung_without_a_run():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "base"
        base.mkdir()
        corpus.plan(base, Path(tmp) / "corpus", ("0", "1"))
        document = corpus.collect(Path(tmp) / "corpus" / "corpus.json", Path(tmp) / "runs")
    assert all(r["run"] is None for r in document["rungs"]), document["rungs"]
    assert all(r["note"] == "not run" for r in document["rungs"])


def test_collect_scores_a_rung_and_records_detection():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "corpus").mkdir()
        make_run(root, 0)
        make_run(root, 1, ["critical"])
        document = {"schema_version": 1, "scale": "claims", "base": str(root), "seed": 1,
                    "rungs": [{"level": 0, "label": "good", "tree": str(root / "tree-0"),
                               "defects_seeded": 0, "seeded": [], "run": None, "score": None},
                              {"level": 1, "label": "bad", "tree": str(root / "tree-1"),
                               "defects_seeded": 1,
                               "seeded": [{"path": "src/app.py", "line": 1}],
                               "run": None, "score": None}]}
        corpus.write(root / "corpus" / "corpus.json", document)
        collected = corpus.collect(root / "corpus" / "corpus.json", root)
    good, bad = collected["rungs"]
    assert good["score"] == 100.0, good["score"]
    assert bad["score"] < 100.0, bad["score"]
    assert bad["detected"] == 1, bad
    assert bad["score_source"] == "claims"


# --- derive: every refusal ----------------------------------------------------------
def test_derive_refuses_an_unrun_rung():
    with tempfile.TemporaryDirectory() as tmp:
        document = manifest_with(Path(tmp), [(0, "good", ()), (1, "bad", ["critical"])])
        document["rungs"][1]["run"] = None
        document["rungs"][1]["score"] = None
        try:
            calibrate.derive_from_runs(document)
        except calibrate.CorpusError as exc:
            assert "no scored run" in str(exc), exc
            return
    raise AssertionError("an unrun rung was accepted")


def test_derive_refuses_an_undetected_bad_rung():
    """A blind reviewer on a defective rung is a reviewer failure, not threshold data."""
    with tempfile.TemporaryDirectory() as tmp:
        document = manifest_with(Path(tmp), [(0, "good", ()), (1, "bad", ["critical"])])
        document["rungs"][1]["detected"] = 0
        document["rungs"][1]["score"] = 100.0
        try:
            calibrate.derive_from_runs(document, min_per_class=1)
        except calibrate.CorpusError as exc:
            assert "proved none of the seeded defects" in str(exc), exc
            return
    raise AssertionError("an undetected bad rung was accepted")


def test_derive_refuses_mixed_scales():
    with tempfile.TemporaryDirectory() as tmp:
        document = manifest_with(Path(tmp), [(0, "good", ()), (1, "bad", ["critical"])])
        document["rungs"][0]["score_source"] = "reviewer"
        try:
            calibrate.derive_from_runs(document, min_per_class=1)
        except calibrate.CorpusError as exc:
            assert "mixed scoring scales" in str(exc), exc
            return
    raise AssertionError("mixed scales were pooled")


def test_derive_refuses_when_the_classes_overlap():
    with tempfile.TemporaryDirectory() as tmp:
        document = manifest_with(Path(tmp), [(0, "good", ()), (1, "bad", ["medium"])])
        document["rungs"][1]["score"] = 100.0
        try:
            calibrate.derive_from_runs(document, min_per_class=1)
        except calibrate.CorpusError as exc:
            assert "do not separate" in str(exc), exc
            return
    raise AssertionError("an overlapping corpus produced a threshold")


def test_derive_refuses_too_few_runs_unless_told():
    with tempfile.TemporaryDirectory() as tmp:
        document = manifest_with(Path(tmp), [(0, "good", ()), (1, "bad", ["critical"])])
        try:
            calibrate.derive_from_runs(document)
        except calibrate.CorpusError as exc:
            assert "runs per class" in str(exc), exc
        else:
            raise AssertionError("a single draw was accepted as calibrating")
    with tempfile.TemporaryDirectory() as tmp:
        document = manifest_with(Path(tmp), [(0, "good", ()), (1, "bad", ["critical"])])
        result = calibrate.derive_from_runs(document, allow_provisional=True)
    assert result["provisional"] is True
    assert "PROVISIONAL" in result["provenance"]["note"]


# --- derive: the happy path, and what it buys ---------------------------------------
def test_a_separating_corpus_produces_a_threshold_between_the_classes():
    """Scores are set explicitly: this test is about the derivation, not the scoring pipeline."""
    specs = [(0, "good", ()), (2, "good", ()), (3, "good", ()),
             (1, "bad", ["critical"]), (4, "bad", ["critical", "high"]),
             (5, "bad", ["critical", "critical"])]
    with tempfile.TemporaryDirectory() as tmp:
        document = manifest_with(Path(tmp), specs)
        for rung, score in zip(document["rungs"], (98.0, 97.0, 99.0, 60.0, 55.0, 50.0)):
            rung["score"] = score
        result = calibrate.derive_from_runs(document)
    good = [p["score"] for p in result["points"] if p["label"] == "good"]
    bad = [p["score"] for p in result["points"] if p["label"] != "good"]
    assert result["scale"] == "claims"
    assert result["provisional"] is False
    assert result["n"] == {"good": 3, "bad": 3}
    assert max(bad) < result["threshold"] <= min(good), (bad, result["threshold"], good)


def test_derive_refuses_a_margin_narrower_than_the_repeat_spread():
    """Noise is the spread of repeats on ONE rung, not the spread of the class.

    Those differ: the bad class also contains the real difference between one defect and four.
    Measured on the nine-run corpus: margin 3.87 against level 1's own spread of 11.71.
    """
    def rung(level: int, repeat: int, score: float) -> dict:
        return {"id": f"level-{level}-run-{repeat}", "level": level, "label": "bad",
                "tree": "/t", "defects_seeded": 1, "seeded": [], "run": "/r",
                "score": score, "detected": 1, "score_source": "claims", "certification": "x"}

    document = {"schema_version": 1, "scale": "claims", "base": "/b", "seed": 1, "rungs": [
        {"id": "level-0-run-1", "level": 0, "label": "good", "tree": "/t", "defects_seeded": 0,
         "seeded": [], "run": "/r", "score": 98.0, "detected": 0, "score_source": "claims",
         "certification": "x"},
        rung(4, 1, 96.0), rung(4, 2, 60.0), rung(4, 3, 55.0),   # spread 41.0, margin 2.0
    ]}
    try:
        calibrate.derive_from_runs(document, min_per_class=1)
    except calibrate.CorpusError as exc:
        assert "repeat spread on level 4" in str(exc), exc
        return
    raise AssertionError("a margin narrower than the repeat spread was accepted")


def test_the_derived_threshold_is_what_the_gate_then_uses():
    """End to end: a claims calibration makes a clean adjudicated run certify."""
    specs = [(0, "good", ()), (2, "good", ()), (3, "good", ()),
             (1, "bad", ["critical"]), (4, "bad", ["critical", "high"]),
             (5, "bad", ["critical", "critical"])]
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        document = manifest_with(root, specs)
        result = calibrate.derive_from_runs(document)
        destination = root / "calibration.claims.json"
        destination.write_text(json.dumps(result), encoding="utf-8")
        original = score.calibration_path
        score.calibration_path = lambda scale: destination  # noqa: ARG005
        try:
            with tempfile.TemporaryDirectory() as clean:
                run = make_run(Path(clean), 0)
                verdict = score.evaluate(run, result["threshold"])
        finally:
            score.calibration_path = original
    assert verdict["calibrated_for_scale"] is True, verdict["calibration_scale"]
    assert verdict["certification"] == "certified", verdict["reason"]


# --- the coverage rule --------------------------------------------------------------
def test_a_run_that_proves_nothing_where_the_probes_found_something_is_unprovable():
    with tempfile.TemporaryDirectory() as tmp:
        run = make_run(Path(tmp), 0, severities=(), probe_defects=2)
        verdict = score.evaluate(run, 0.0)
    assert verdict["certification"] == "unprovable", verdict["certification"]
    assert verdict["coverage_gap"] and "settled no claim" in verdict["coverage_gap"]
    assert verdict["aggregate"] == 100.0, "the number is still 100 — that is the hole"


def test_a_low_severity_probe_nit_does_not_make_a_silent_run_unprovable():
    """A clean tree yields low-severity probe findings — an unused lambda, no AGENTS.md.

    A reviewer that says nothing about them is right, not blind. Counting them made a
    clean rung `unprovable` and cost a real corpus a rung.
    """
    with tempfile.TemporaryDirectory() as tmp:
        run = make_run(Path(tmp), 0)
        probes = json.loads((run / "probes.json").read_text(encoding="utf-8"))
        probes[0]["findings"] = [{"path": "flake.nix", "severity": "low", "claim": "unused lambda"}]
        (run / "probes.json").write_text(json.dumps(probes), encoding="utf-8")
        verdict = score.evaluate(run, 0.0)
    assert verdict["coverage_gap"] is None
    assert verdict["certification"] in ("certified", "uncalibrated"), verdict["certification"]


def test_a_high_severity_probe_finding_still_makes_a_silent_run_unprovable():
    with tempfile.TemporaryDirectory() as tmp:
        run = make_run(Path(tmp), 0)
        probes = json.loads((run / "probes.json").read_text(encoding="utf-8"))
        probes[0]["findings"] = [{"path": "flake.nix", "severity": "high", "claim": "bad"}]
        (run / "probes.json").write_text(json.dumps(probes), encoding="utf-8")
        verdict = score.evaluate(run, 0.0)
    assert verdict["certification"] == "unprovable"


def test_a_run_that_settled_a_claim_has_no_gap():
    with tempfile.TemporaryDirectory() as tmp:
        run = make_run(Path(tmp), 1, severities=["critical"], probe_defects=1)
        verdict = score.evaluate(run, 0.0)
    assert verdict["coverage_gap"] is None
    assert verdict["certification"] == "unsatisfied", verdict["certification"]


def test_a_repo_the_probes_found_clean_has_no_gap():
    with tempfile.TemporaryDirectory() as tmp:
        run = make_run(Path(tmp), 0, severities=(), probe_defects=0)
        verdict = score.evaluate(run, 0.0)
    assert verdict["coverage_gap"] is None
    assert verdict["certification"] in ("certified", "uncalibrated"), verdict["certification"]


# --- collect: a sample-only round has to be assembled first --------------------------
def test_collect_merges_samples_before_scoring():
    """A round that only wrote generalist samples must be merged, not scored as an error.

    The first real corpus hit this: `collect` scored the unmerged round, `evaluate` returned
    `{"error": …}`, and the KeyError on `certification` hid which rung was unreadable.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        tree = root / "tree-0"
        (tree / "src").mkdir(parents=True)
        (tree / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")
        round_dir = root / "level-0" / "round-1"
        round_dir.mkdir(parents=True)
        (round_dir / "meta.json").write_text(
            json.dumps({"repo": str(tree), "stacks": ["generic"]}), encoding="utf-8")
        findings = [{"id": f"{dim}-1", "dimension": dim, "severity": "low", "status": "open",
                     "location": {"path": "src/app.py", "line_range": "1"}, "claim": "x"}
                    for dim in DIMS]
        (round_dir / "generalist-1.json").write_text(
            json.dumps({"reviewer": "council-generalist", "findings": findings}),
            encoding="utf-8")
        document = {"schema_version": 1, "scale": "claims", "base": str(root), "seed": 1,
                    "rungs": [{"level": 0, "label": "good", "tree": str(tree),
                               "defects_seeded": 0, "seeded": [], "run": None, "score": None}]}
        corpus.write(root / "corpus.json", document)
        collected = corpus.collect(root / "corpus.json", root)
        merged = (round_dir / "security.json").exists()
    rung = collected["rungs"][0]
    assert merged, "collect did not merge the samples"
    assert rung["score"] is not None, rung.get("note")
    assert "could not be scored" not in (rung.get("note") or ""), rung.get("note")


# --- the ladder that varies only defects --------------------------------------------
def test_in_place_ladder_keeps_the_file_count_constant():
    """Every rung must have the same files, or `det` drifts with the rung and nothing separates.

    Measured on the first ladder: adding sixteen files raised det by 6.8–13.7 points per dimension,
    so the 16-defect rung outscored the clean one.
    """
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "base"
        (base / "src").mkdir(parents=True)
        (base / "src" / "a.py").write_text("x = 1\n" * 20, encoding="utf-8")
        (base / "src" / "b.py").write_text("y = 2\n" * 20, encoding="utf-8")
        document = corpus.plan(base, Path(tmp) / "c", ("0", "1", "4"), in_place=True)
        counts = {r["level"]: len(list(Path(r["tree"]).rglob("*.py")))
                  for r in document["rungs"]}
    assert len(set(counts.values())) == 1, f"file count varies by rung: {counts}"
    assert document["in_place"] is True


def test_in_place_defects_record_where_they_are():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "base"
        (base / "src").mkdir(parents=True)
        (base / "src" / "a.py").write_text("x = 1\n" * 20, encoding="utf-8")
        document = corpus.plan(base, Path(tmp) / "c", ("0", "4"), in_place=True)
    rung = next(r for r in document["rungs"] if r["level"] == 4)
    assert len(rung["seeded"]) == 4, rung["seeded"]
    assert all(item.get("line") and item.get("path") for item in rung["seeded"]), rung["seeded"]


def test_derive_refuses_a_barely_detected_rung():
    """Missing defects keeps a rung's score high, so a low-detection rung cannot calibrate.

    Measured: level 4 (4/4 detected) 53.56, level 16 (2/16) 58.79 — missing twelve defects was
    worth five points in the wrong direction.
    """
    with tempfile.TemporaryDirectory() as tmp:
        document = manifest_with(Path(tmp), [(0, "good", ()),
                                             (1, "bad", ["critical"] * 4)])
        document["rungs"][1]["detected"] = 1        # 1 of 4 — below the default 50%
        try:
            calibrate.derive_from_runs(document, min_per_class=1)
        except calibrate.CorpusError as exc:
            assert "detection below" in str(exc), exc
            return
    raise AssertionError("a rung with 25% detection was accepted")


def test_a_rung_can_be_excluded_deliberately_and_it_is_recorded():
    with tempfile.TemporaryDirectory() as tmp:
        document = manifest_with(Path(tmp), [(0, "good", ()),
                                             (1, "bad", ["critical"] * 4),
                                             (2, "bad", ["critical"])])
        document["rungs"][1]["detected"] = 1
        result = calibrate.derive_from_runs(document, min_per_class=1, exclude_levels=(1,))
    assert result["provenance"]["excluded"] == [1]
    assert 1 not in [point["level"] for point in result["points"]]


def test_repeats_get_their_own_run_directories():
    """A repeat is a separate draw: it needs its own directory, or it overwrites the first."""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "base"
        (base / "src").mkdir(parents=True)
        (base / "src" / "a.py").write_text("x = 1\n" * 20, encoding="utf-8")
        document = corpus.plan(base, Path(tmp) / "c", ("0", "1"), in_place=True, repeats=3)
        ids = [r["id"] for r in document["rungs"]]
        dirs = [corpus.run_dir_for(Path("/runs"), r) for r in document["rungs"]]
    assert ids == ["level-0-run-1", "level-0-run-2", "level-0-run-3",
                   "level-1-run-1", "level-1-run-2", "level-1-run-3"], ids
    assert len(set(dirs)) == 6, dirs
    assert document["repeats"] == 3


# --- agreement: what varies between passes of the same rung -------------------------
def test_agreement_separates_stable_from_one_off_and_flags_severity_flips():
    """The instrument M11 depends on: without it 'did the fix help' is unanswerable."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        passes = [
            [("a.py", "4", "critical"), ("b.py", "9", "high")],
            [("a.py", "4", "critical")],
            [("a.py", "4", "medium")],
        ]
        rungs = []
        for index, records in enumerate(passes, start=1):
            run = root / f"level-4-run-{index}"
            run.mkdir(parents=True)
            (run / "proofs.json").write_text(json.dumps({"findings": [
                {"id": f"F-{i}", "state": "confirmed", "severity": sev,
                 "location": {"path": path, "line_range": line}}
                for i, (path, line, sev) in enumerate(records)]}), encoding="utf-8")
            rungs.append({"id": f"level-4-run-{index}", "level": 4, "repeat": index, "label": "bad",
                          "tree": str(root), "defects_seeded": 1,
                          "seeded": [{"path": "c.py", "line": 7}], "run": str(run),
                          "score": 50.0, "detected": 0})
        report = corpus.agreement({"rungs": rungs})

    level = report["levels"][0]
    assert level["passes"] == 3
    assert level["stable"] == ["a.py:4"], level["stable"]
    assert level["one_off"] == ["b.py:9"], level["one_off"]
    assert level["severity_disagreements"] == {"a.py:4": ["critical", "medium"]}, \
        level["severity_disagreements"]
    assert level["blind_spots"] == ["c.py"], level["blind_spots"]
    assert "BLIND SPOT: c.py" in corpus.format_agreement(report)


def test_agreement_measures_the_severity_the_gate_uses():
    """Two passes, one asserting critical and one high, both uncorroborated: same verdict, no flip."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        rungs = []
        for index, (asserted, scored) in enumerate((("critical", "high"), ("high", "high")), 1):
            run = root / f"level-1-run-{index}"
            (run / "round-1").mkdir(parents=True)
            (run / "round-1" / "proofs.json").write_text(json.dumps({"findings": [
                {"id": "F-1", "state": "confirmed", "severity": asserted,
                 "severity_scored": scored,
                 "location": {"path": "a.py", "line_range": "8"}}]}), encoding="utf-8")
            rungs.append({"id": f"level-1-run-{index}", "level": 1, "repeat": index,
                          "label": "bad", "tree": str(root), "defects_seeded": 0, "seeded": [],
                          "run": str(run), "score": 60.0, "detected": 0})
        report = corpus.agreement({"rungs": rungs})
    assert report["levels"][0]["severity_disagreements"] == {}, \
        report["levels"][0]["severity_disagreements"]


def test_agreement_counts_a_location_once_per_pass():
    """The same location twice in one pass is still one pass's worth of agreement."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        run = root / "level-1-run-1"
        (run / "round-1").mkdir(parents=True)
        (run / "round-1" / "proofs.json").write_text(json.dumps({"findings": [
            {"id": "F-1", "state": "confirmed", "severity": "high",
             "location": {"path": "a.py", "line_range": "4"}},
            {"id": "F-2", "state": "confirmed", "severity": "high",
             "location": {"path": "a.py", "line_range": "4"}},
        ]}), encoding="utf-8")
        report = corpus.agreement({"rungs": [
            {"id": "level-1-run-1", "level": 1, "repeat": 1, "label": "bad", "tree": str(root),
             "defects_seeded": 0, "seeded": [], "run": str(run), "score": 60.0, "detected": 0}]})
    assert report["levels"][0]["stable"] == ["a.py:4"]


def test_detection_is_measured_at_the_seeded_line_not_the_file():
    """Path-only matching counted an unrelated finding in the same file as detection."""
    seeded = [{"path": "src/svc/pricing.py", "line": 30}]

    def claim(line_range, ident="F-1"):
        return {"id": ident, "state": "confirmed",
                "location": {"path": "src/svc/pricing.py", "line_range": line_range}}

    assert corpus._match(seeded, [claim("30")])[0]["matched"] is True
    assert corpus._match(seeded, [claim("20-45")])[0]["matched"] is True, "a span containing it"
    assert corpus._match(seeded, [claim("8-11")])[0]["matched"] is False, "a different line"
    assert corpus._match(seeded, [claim("")])[0]["matched"] is False, "a file with no line"
    why = corpus._match(seeded, [claim("8-11")])[0]["why"]
    assert "8-11" in why, why


def test_a_defect_block_matches_a_claim_inside_it():
    """Measured: the eval seed spans `def` and `return eval(...)`; every pass cited the second line
    and was scored as having missed a defect seeded at the first."""
    seeded = [{"path": "src/svc/client.py", "line": 19, "line_end": 20, "kind": "eval"}]
    claim = {"id": "F-1", "state": "confirmed",
             "location": {"path": "src/svc/client.py", "line_range": "20"}}
    result = corpus._match(seeded, [claim])[0]
    assert result["matched"] is True, result
    assert result["line_end"] == 20, result


def test_a_manifest_that_recorded_only_a_start_still_gets_its_span():
    """Old manifests have no line_end; the span comes from the template that planted the text."""
    seeded = [{"path": "a.py", "line": 19, "kind": "eval"}]
    claim = {"id": "F-1", "state": "confirmed",
             "location": {"path": "a.py", "line_range": "20"}}
    assert corpus._match(seeded, [claim])[0]["matched"] is True
    outside = {"id": "F-2", "state": "confirmed",
               "location": {"path": "a.py", "line_range": "21"}}
    assert corpus._match(seeded, [outside])[0]["matched"] is False


def test_the_seed_span_matches_the_text_the_seed_plants():
    calibrate = corpus._module("calibrate")
    assert calibrate.inserted_span("secret") == 1
    assert calibrate.inserted_span("eval") == 2
    assert calibrate.inserted_span("syntax") == 2
    assert calibrate.inserted_span("complexity") > 10, "the 12-branch body is one block"


def test_a_seed_without_a_line_still_matches_its_file():
    seeded = [{"path": "a.py"}]
    claim = {"id": "F-1", "state": "confirmed", "location": {"path": "a.py", "line_range": "3"}}
    assert corpus._match(seeded, [claim])[0]["matched"] is True


def test_an_empty_sample_is_not_a_clean_tree():
    """Measured: a tree with one README scored 100.00 — zero tools, zero findings, perfect score.

    The gate cannot tell "nothing found" from "nothing looked at". The corpus must, or the best
    rung in the corpus is whichever sample crashed quietly.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        tree = root / "tree-0"
        tree.mkdir()
        (tree / "README.md").write_text("not a repo\n", encoding="utf-8")
        round_dir = root / "level-0" / "round-1"
        round_dir.mkdir(parents=True)
        (round_dir / "meta.json").write_text(
            json.dumps({"repo": str(tree), "stacks": ["generic"]}), encoding="utf-8")
        (round_dir / "generalist-1.json").write_text(
            json.dumps({"reviewer": "council-generalist", "findings": [], "tools_run": []}),
            encoding="utf-8")
        document = {"schema_version": 1, "scale": "claims", "base": str(root), "seed": 1,
                    "rungs": [{"level": 0, "label": "good", "tree": str(tree),
                               "defects_seeded": 0, "seeded": [], "run": None, "score": None}]}
        corpus.write(root / "corpus.json", document)
        collected = corpus.collect(root / "corpus.json", root)
    rung = collected["rungs"][0]
    assert rung["score"] is None, f"an empty sample was scored {rung['score']}"
    assert "uninformative" in (rung.get("note") or ""), rung.get("note")


def test_a_sample_that_ran_tools_and_found_nothing_is_clean_not_uninformative():
    """The other side of the rule: no findings is a real result when something was examined."""
    with tempfile.TemporaryDirectory() as tmp:
        round_dir = Path(tmp)
        (round_dir / "generalist-1.json").write_text(
            json.dumps({"findings": [], "tools_run": ["bandit", "ruff"]}), encoding="utf-8")
        ok, why = corpus._informative(round_dir)
    assert ok is True, why


def test_reported_but_unproven_findings_are_still_informative():
    """A reviewer that raised issues and proved none examined the tree; that is not the empty case."""
    with tempfile.TemporaryDirectory() as tmp:
        round_dir = Path(tmp)
        (round_dir / "generalist-1.json").write_text(
            json.dumps({"findings": [{"id": "F-1"}], "tools_run": []}), encoding="utf-8")
        ok, why = corpus._informative(round_dir)
    assert ok is True, why


def test_a_round_that_scored_on_another_scale_is_not_recorded():
    """Measured: a corpus declaring `claims` got a deterministic 100.00 because no claims
    calibration file existed, and recorded it as its best rung."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "corpus").mkdir()
        make_run(root, 0)
        document = {"schema_version": 1, "scale": "claims", "base": str(root), "seed": 1,
                    "rungs": [{"level": 0, "label": "good", "tree": str(root / "tree-0"),
                               "defects_seeded": 0, "seeded": [], "run": None, "score": None}]}
        corpus.write(root / "corpus" / "corpus.json", document)
        collected = corpus.collect(root / "corpus" / "corpus.json", root)
    rung = collected["rungs"][0]
    if rung["score"] is not None and rung.get("score_source") == "claims":
        return  # a claims calibration was present; the rule is not exercised here
    assert rung["score"] is None, f"recorded {rung['score']} from scale {rung.get('score_source')}"
    assert "declares" in (rung.get("note") or ""), rung.get("note")


def _verdict_manifest(certifications):
    return {"rungs": [
        {"id": f"level-{level}-run-1", "level": level,
         "label": "good" if level == 0 else "bad",
         "score": 80.0, "certification": cert}
        for level, cert in certifications]}


def test_verdicts_separate_when_labels_and_certifications_agree():
    report = corpus.verdicts(_verdict_manifest([(0, "certified"), (1, "unsatisfied"),
                                                (4, "unprovable")]))
    assert report["separates"] is True, report
    assert report["wrong"] == [] and report["unrun"] == []
    assert "separate every rung" in corpus.format_verdicts(report)


def test_verdicts_report_a_clean_rung_that_fails_to_certify():
    """A check that cannot fail is not a check — measured on a relabelled manifest."""
    report = corpus.verdicts(_verdict_manifest([(0, "unsatisfied"), (1, "unsatisfied")]))
    assert report["separates"] is False
    assert report["wrong"] == ["level-0-run-1"], report
    assert "WRONG" in corpus.format_verdicts(report)


def test_verdicts_report_a_rung_with_no_verdict():
    report = corpus.verdicts(_verdict_manifest([(0, "certified"), (1, None)]))
    assert report["separates"] is False
    assert report["unrun"] == ["level-1-run-1"], report
    assert "no verdict" in corpus.format_verdicts(report)


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
            except Exception as exc:  # noqa: BLE001
                failures += 1
                print(f"FAIL {name}: {type(exc).__name__}: {exc}")
    print(f"\n{len([n for n in globals() if n.startswith('test_')]) - failures} passed, "
          f"{failures} failed")
    raise SystemExit(1 if failures else 0)
