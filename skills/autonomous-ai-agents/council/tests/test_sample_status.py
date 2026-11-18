"""Prove the status file is written — the half the missing-tree test could not reach."""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
_spec = importlib.util.spec_from_file_location("sample", REPO / "scripts" / "sample.py")
sample = importlib.util.module_from_spec(_spec)
sys.modules["sample"] = sample
_spec.loader.exec_module(sample)

PROVIDER_404 = "HTTP 404 — no marketplace sellers meet the minimum 89% discount"


def test_a_failed_sample_records_why_beside_the_round():
    with tempfile.TemporaryDirectory() as tmp:
        round_dir = Path(tmp)
        log = round_dir / "sample-1.log"
        log.write_text(PROVIDER_404, encoding="utf-8")
        status = sample.write_status(round_dir, 1, 1, round_dir / "generalist-1.json", log, False)
        written = json.loads((round_dir / "sample-1.status.json").read_text())
    assert written == {"rc": 1, "artefact": "missing", "reason": "provider_refused"}, written
    assert status == written


def test_a_file_written_before_a_nonzero_exit_is_still_a_sample():
    with tempfile.TemporaryDirectory() as tmp:
        round_dir = Path(tmp)
        artefact = round_dir / "generalist-1.json"
        artefact.write_text(json.dumps({"findings": []}), encoding="utf-8")
        status = sample.write_status(round_dir, 1, 1, artefact, round_dir / "nope.log", True)
    assert status["artefact"] == "parsed" and status["reason"] is None, status
    assert status["rc"] == 1, "the exit code is recorded even when the artefact is good"


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
