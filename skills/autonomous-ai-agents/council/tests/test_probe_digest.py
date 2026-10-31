"""The reviewer's probe digest is bounded, and the record is not.

    python tests/test_probe_digest.py

The prompt and the run record have different budgets. `probes.json` is evidence: every finding,
read by the gate and by the next incremental diff. The prompt is a message to a model, and a
message past its context window produces no review at all — measured as a 518 KB prompt with a
504 at 240 s and 900 s, against a 20 s answer to a small one.
"""
from __future__ import annotations

import importlib.util
import json
import os
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "council_loop", REPO / "scripts" / "council_loop.py")
loop = importlib.util.module_from_spec(spec)
spec.loader.exec_module(loop)

# A scripts/ module refuses to execute unless the dispatcher said so.
os.environ.setdefault("REVIEW_COUNCIL_DISPATCHED", "1")


def _finding(rule: str, severity: str, path: str, n: int) -> dict:
    return {
        "severity": severity,
        "status": "open",
        "location": {"path": path, "line_range": str(n)},
        "claim": f"ruff {rule}: something worth a line of text in the report",
        "falsifiable_check": f"ruff check {path}",
    }


def _thousand(repo: Path) -> list:
    return [_finding("UP006", "low", str(repo / "scripts" / "council_loop.py"), i)
            for i in range(1000)]


def test_a_thousand_findings_are_capped_labelled_and_inside_the_budget():
    repo = Path(tempfile.mkdtemp())
    probes = [{"tool": "ruff", "ran": True, "signal": 9.1, "parsed": True,
               "note": "1000 findings over 1 files", "findings": _thousand(repo)}]
    rendered = loop.probe_digest(probes, repo)
    data = json.loads(rendered)
    entry = data[0]

    assert len(entry["findings"]) <= loop.PROMPT_FINDINGS_PER_PROBE, len(entry["findings"])
    assert entry["findings_total"] == 1000
    assert entry["findings_omitted"] == 1000 - len(entry["findings"])
    assert entry["omitted_by_rule"]["UP006"] == entry["findings_omitted"]
    assert len(rendered) <= loop.PROMPT_PROBE_BUDGET_BYTES, len(rendered)


def test_the_record_is_not_mutated():
    repo = Path(tempfile.mkdtemp())
    probe = {"tool": "ruff", "ran": True, "signal": 9.1, "parsed": True,
             "note": "n", "findings": _thousand(repo)}
    before = json.dumps(probe, sort_keys=True)
    loop.probe_digest([probe], repo)
    assert json.dumps(probe, sort_keys=True) == before, "the digest mutated its input"


def test_severity_beats_position():
    repo = Path(tempfile.mkdtemp())
    findings = [_finding("UP006", "low", str(repo / "a.py"), i) for i in range(40)]
    findings.append(_finding("S105", "high", str(repo / "b.py"), 1))
    kept = json.loads(loop.probe_digest([{"tool": "ruff", "findings": findings}], repo))[0]
    assert any(f["severity"] == "high" for f in kept["findings"]), kept["findings"][:3]


def test_paths_under_the_repo_become_relative_and_outside_ones_are_left():
    # POSIX on every host: this assertion is what caught the Windows form in CI.

    repo = Path(tempfile.mkdtemp())
    inside = _finding("E501", "low", str(repo / "scripts" / "x.py"), 1)
    outside = _finding("E501", "low", "/nix/store/abc/site-packages/y.py", 1)
    data = json.loads(loop.probe_digest(
        [{"tool": "ruff", "findings": [inside, outside]}], repo))[0]
    paths = sorted(f["location"]["path"] for f in data["findings"])
    assert "scripts/x.py" in paths, paths
    assert "/nix/store/abc/site-packages/y.py" in paths, paths


def test_long_strings_are_truncated():
    repo = Path(tempfile.mkdtemp())
    f = _finding("E501", "low", str(repo / "x.py"), 1)
    f["claim"] = "ruff E501: " + "x" * 500
    f["falsifiable_check"] = "ruff check " + "y" * 500
    kept = json.loads(loop.probe_digest([{"tool": "ruff", "findings": [f]}], repo))[0]
    one = kept["findings"][0]
    assert len(one["claim"]) <= loop.PROMPT_CLAIM_CHARS + 1, len(one["claim"])
    assert len(one["falsifiable_check"]) <= loop.PROMPT_CHECK_CHARS + 1


def test_an_impossible_budget_degrades_to_counts_that_still_parse():
    repo = Path(tempfile.mkdtemp())
    probes = [{"tool": "ruff", "findings": _thousand(repo)}]
    rendered = loop.probe_digest(probes, repo, budget_bytes=200)
    data = json.loads(rendered)  # must still be JSON
    assert data[0]["findings"] == []
    assert data[0]["findings_total"] == 1000
    assert data[0]["findings_omitted"] == 1000


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ok    {name}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL  {name}\n        {exc}")
    print(f"\n  {len(tests) - failed}/{len(tests)} passed")
    raise SystemExit(1 if failed else 0)
