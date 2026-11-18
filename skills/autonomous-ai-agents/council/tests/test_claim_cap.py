"""A cap must come from a severity the evidence supports, not from the reviewer's word.

Measured: a formatting finding asserted `critical` and proven by a linter produced the corpus's
lowest score (52.49) and a 15.59-point spread across six passes of one tree.

Run standalone: python tests/test_claim_cap.py
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
_spec = importlib.util.spec_from_file_location("score_reviews", REPO / "scripts" / "score_reviews.py")
score = importlib.util.module_from_spec(_spec)
sys.modules["score_reviews"] = score
_spec.loader.exec_module(score)


def record(state="confirmed", severity="critical", scored=None, **extra):
    item = {"state": state, "severity": severity}
    if scored is not None:
        item["severity_scored"] = scored
    item.update(extra)
    return item


def test_a_corroborated_critical_still_caps_at_thirty():
    assert score.claim_cap([record(scored="critical")]) == 30.0


def test_an_uncorroborated_critical_is_held_at_high():
    """adjudication writes severity_scored=high when the evidence does not support critical."""
    assert score.claim_cap([record(scored="high")]) == 60.0


def test_records_without_the_field_fall_back_to_severity():
    assert score.claim_cap([record()]) == 30.0


def test_only_confirmed_claims_cap():
    assert score.claim_cap([record(state="unsettled", scored="critical")]) is None


def test_the_hardest_confirmed_claim_wins():
    both = [record(scored="high"), record(scored="critical")]
    assert score.claim_cap(both) == 30.0


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
