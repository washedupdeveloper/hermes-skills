"""Every surface renders from the change, and says so when there is no change.

    python tests/test_surfaces.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


loop = _load("council_loop")
pr = _load("pr")
goal = _load("goal")
os.environ.setdefault("REVIEW_COUNCIL_DISPATCHED", "1")


class _FakeGate:
    """The renderer's only contact with the gate is the improvement list."""

    @staticmethod
    def improvement_opportunities(result, target=None):
        return []


loop._gate_module = lambda: _FakeGate  # type: ignore[assignment]

RESULT = {"aggregate": 96.97, "threshold": 80.0, "status": "not_satisfied",
          "blocking": [], "stacks": ["python"], "size_kloc": 1.0, "reason": "advisory"}


def _change(root: pathlib.Path) -> pathlib.Path:
    change = root / "handover" / "openspec" / "changes" / "close-the-findings"
    (change / "specs" / "rounds").mkdir(parents=True, exist_ok=True)
    (change / "proposal.md").write_text(
        "# Proposal\n\n## Why\n\nx\n\n## What Changes\n\n- y\n", encoding="utf-8")
    (change / "specs" / "rounds" / "spec.md").write_text(
        "# Spec Delta\n\n## ADDED Requirements\n\n### Requirement: One path\n\nThe fixture SHALL "
        "resolve once.\n\n#### Scenario: Used\n\n- **WHEN** called\n- **THEN** it resolves\n",
        encoding="utf-8")
    (change / "tasks.md").write_text(
        "# Tasks\n\n- [ ] 1.1 Rewrite the path.\n- [ ] 1.2 Verify: `pytest -q`.\n",
        encoding="utf-8")
    return change


def test_next_steps_renders_the_change_not_a_second_plan():
    root = pathlib.Path(tempfile.mkdtemp())
    change = _change(root)
    handover = {"found": True, "valid": True, "path": str(change.parent), "changes": [],
                "problems": []}
    text = loop.render_next_steps(
        result=RESULT, history=[], outcome="escalate", reason="advisory",
        threshold=80.0, repo=root, mode="advisory", rounds_used=1, handover=handover)

    assert "## The change" in text, text[:400]
    assert "- [ ] 1.1 Rewrite the path." in text, "the tasks are the plan, verbatim"
    assert "`rounds` — One path" in text, "the requirement is named with its capability"
    assert "## A. Required" not in text, "two plans is the defect this replaces"


def test_next_steps_falls_back_and_says_so_when_no_change_exists():
    root = pathlib.Path(tempfile.mkdtemp())
    text = loop.render_next_steps(
        result=RESULT, history=[], outcome="escalate", reason="advisory",
        threshold=80.0, repo=root, mode="advisory", rounds_used=1, handover=None)
    assert "## A. Required" in text, text[:400]
    assert "No validated change was written" in text


def test_read_handover_plan_skips_the_archive_and_reads_requirements_and_tasks():
    root = pathlib.Path(tempfile.mkdtemp())
    change = _change(root)
    (change.parent / "archive" / "old").mkdir(parents=True)
    plan = loop.read_handover_plan(change.parent)
    assert plan["change"] == "close-the-findings"
    assert plan["requirements"], plan
    assert plan["requirements"][0]["capability"] == "rounds", plan["requirements"]
    assert len(plan["tasks"]) == 2, plan["tasks"]


def test_the_fix_turn_is_handed_the_change_tasks():
    """The turn that edits the tree must work the same plan the reader is given."""
    root = pathlib.Path(tempfile.mkdtemp())
    change = _change(root)
    handover = {"found": True, "valid": True, "path": str(change.parent), "changes": [],
                "problems": []}
    text = loop.fix_plan(handover, RESULT, 80.0)
    assert "OpenSpec change `close-the-findings`" in text, text
    assert "- [ ] 1.1 Rewrite the path." in text, text


def test_the_fix_turn_falls_back_without_a_change():
    text = loop.fix_plan({}, RESULT, 80.0)
    assert "OpenSpec change" not in text


def test_the_console_verdict_names_the_change():
    import argparse
    import io
    from contextlib import redirect_stdout

    root = pathlib.Path(tempfile.mkdtemp())
    args = argparse.Namespace(threshold=80.0, mode="advisory", min_rounds=1,
                              max_rounds=1, budget_seconds=0.0)
    out = io.StringIO()
    with redirect_stdout(out):
        loop.write_outcome(root, "escalate", "advisory", [96.97], args, root,
                           handover={"found": True, "valid": True,
                                     "path": "/runs/x/handover/openspec/changes", "changes": [],
                                     "problems": []})
    assert "change:" in out.getvalue(), out.getvalue()
    assert "valid" in out.getvalue()


def test_the_pr_body_names_the_change_from_outcome_json():
    root = pathlib.Path(tempfile.mkdtemp())
    round_dir = root / "round-1"
    round_dir.mkdir()
    (root / "outcome.json").write_text(json.dumps(
        {"handover": {"found": True, "valid": True,
                      "path": "/runs/x/handover/openspec/changes", "changes": [],
                      "problems": []}}), encoding="utf-8")
    pointer = pr._change_line(round_dir)
    assert pointer and "OpenSpec change" in pointer and "validates" in pointer


def test_the_goal_contract_says_the_plan_is_the_change():
    fields = goal.contract(pathlib.Path("/tmp/repo"), 80.0, "council gate --latest")
    assert "OpenSpec change" in fields["boundaries"], fields["boundaries"]


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
