"""Why did a sample produce nothing? Recorded, not inferred.

Run standalone: python tests/test_failures.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))


def load(name):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


failures = load("failures")
corpus = load("corpus")

PROVIDER_404 = ("sample 1: FAILED (rc=1, file=missing)\n"
                "Error: HTTP 404 — no marketplace sellers meet the minimum 89% discount")


def test_the_provider_outage_is_named_for_what_it_was():
    """The exact text that cost three good-rung samples."""
    assert failures.classify_failure(PROVIDER_404) == "provider_refused"


def test_the_other_failure_shapes_are_distinguished():
    assert failures.classify_failure("requests.exceptions.ReadTimeout: timed out") == "timeout"
    assert failures.classify_failure("HTTP 401 unauthorized") == "auth"
    assert failures.classify_failure("HTTP 429 too many requests") == "rate_limited"
    assert failures.classify_failure("APIConnectionError: Connection refused") == "connection"
    assert failures.classify_failure("JSONDecodeError: Expecting value") == "unparseable"
    assert failures.classify_failure("something no pattern covers") == "unknown"
    assert failures.classify_failure("") == "unknown"


def test_a_valid_artefact_survives_a_nonzero_exit():
    """Observed: a background run exited 1 AFTER writing valid JSON. The file is the evidence."""
    record = failures.attempt_record(1, artefact_exists=True, parsed=True, log_text=PROVIDER_404)
    assert record["artefact"] == "parsed" and record["reason"] is None, record
    assert record["rc"] == 1, "the exit code is kept, it is just not the verdict"


def test_a_missing_artefact_keeps_the_reason():
    record = failures.attempt_record(1, False, False, PROVIDER_404)
    assert record == {"rc": 1, "artefact": "missing", "reason": "provider_refused"}, record


def test_the_note_distinguishes_never_attempted_from_refused():
    assert failures.summarise([]) == "not run"
    refused = [failures.attempt_record(1, False, False, PROVIDER_404)] * 3
    note = failures.summarise(refused)
    assert "3 attempt(s)" in note and "provider_refused" in note, note


def test_sample_corpus_retries_and_records_every_attempt():
    """First attempt missing, second good: the corpus must show both and accept the sample."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        manifest_path = root / "corpus.json"
        manifest_path.write_text(json.dumps({"rungs": [
            {"id": "level-1-run-1", "level": 1, "repeat": 1, "label": "bad",
             "tree": str(root), "defects_seeded": 0, "seeded": [], "run": None, "note": None}]}),
            encoding="utf-8")
        calls = {"n": 0}

        def runner(rung, runs_root):
            calls["n"] += 1
            out = Path(runs_root) / rung["id"] / "round-1" / "generalist-1.json"
            if calls["n"] < 2:
                return 1, out, PROVIDER_404
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps({"findings": []}), encoding="utf-8")
            return 0, out, ""

        result = corpus.sample_corpus(manifest_path, root / "runs", retries=3, runner=runner)
        rung = result["rungs"][0]
        assert len(rung["attempts"]) == 2, rung["attempts"]
        assert rung["attempts"][0]["reason"] == "provider_refused"
        assert rung["attempts"][1]["artefact"] == "parsed"
        assert rung["run"], "a sampled rung must point at its run"
        assert rung["note"] is None


def test_sample_corpus_gives_up_and_says_why():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        manifest_path = root / "corpus.json"
        manifest_path.write_text(json.dumps({"rungs": [
            {"id": "level-0-run-1", "level": 0, "repeat": 1, "label": "good",
             "tree": str(root), "defects_seeded": 0, "seeded": [], "run": None, "note": None}]}),
            encoding="utf-8")

        def runner(rung, runs_root):
            return 1, Path(runs_root) / rung["id"] / "round-1" / "generalist-1.json", PROVIDER_404

        result = corpus.sample_corpus(manifest_path, root / "runs", retries=2, runner=runner)
        rung = result["rungs"][0]
        assert len(rung["attempts"]) == 2
        assert rung["run"] is None
        assert "provider_refused" in rung["note"]


if __name__ == "__main__":
    failures_count = 0
    names = [n for n in sorted(globals()) if n.startswith("test_")]
    for name in names:
        try:
            globals()[name]()
            print(f"ok   {name}")
        except AssertionError as exc:
            failures_count += 1
            print(f"FAIL {name}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failures_count += 1
            print(f"FAIL {name}: {type(exc).__name__}: {exc}")
    print(f"\n{len(names) - failures_count} passed, {failures_count} failed")
    raise SystemExit(1 if failures_count else 0)
