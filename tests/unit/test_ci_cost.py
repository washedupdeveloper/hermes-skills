"""The cost table: what it counts, what it refuses to guess."""
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/ci-cost.py"
spec = importlib.util.spec_from_file_location("ci_cost", SCRIPT)
ci_cost = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci_cost)

PAYLOAD = {
    "jobs": [
        {"name": "nix gate", "started_at": "2026-10-28T20:00:00Z",
         "completed_at": "2026-10-28T20:01:30Z", "conclusion": "success"},
        {"name": "tests (macos-26)", "started_at": "2026-10-28T20:00:01Z",
         "completed_at": "2026-10-28T20:01:01Z", "conclusion": "cancelled"},
        {"name": "cost", "started_at": "2026-10-28T20:01:31Z",
         "completed_at": None, "conclusion": None},
    ]
}


def test_rows_are_longest_first():
    assert [r[0] for r in ci_cost.cost_rows(PAYLOAD)] == ["nix gate", "tests (macos-26)", "cost"]


def test_a_running_job_has_no_seconds_and_sorts_last():
    rows = ci_cost.cost_rows(PAYLOAD)
    assert rows[-1] == ("cost", None, "running")


def test_seconds_come_from_the_two_timestamps():
    by_name = {r[0]: r[1] for r in ci_cost.cost_rows(PAYLOAD)}
    assert by_name["nix gate"] == 90
    assert by_name["tests (macos-26)"] == 60


def test_the_span_is_not_the_sum():
    """60 + 90 = 150, but the run's wall clock is 91s: the jobs overlap."""
    assert ci_cost.span_seconds(PAYLOAD) == 91
    assert ci_cost.span_seconds({"jobs": []}) is None


def test_the_table_names_the_run_span_and_marks_a_running_job():
    out = ci_cost.table(PAYLOAD)
    assert out.startswith("| job | seconds | conclusion |")
    assert "| cost | — | running |" in out
    assert "**Run span:** 91s" in out


def test_missing_jobs_key_is_not_a_crash():
    assert ci_cost.table({}).splitlines()[0] == "| job | seconds | conclusion |"
