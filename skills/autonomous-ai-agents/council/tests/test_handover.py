"""The handover is an OpenSpec change, and the check on it can fail.

    python tests/test_handover.py

`openspec validate` cannot run inside a review — the runtime image has no Node — so the shape is
checked by `validate_handover()`. These tests pin that check in both directions: a real change
passes, and each way of being malformed is named.
"""
from __future__ import annotations

import importlib.util
import os
import pathlib
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "council_loop", REPO / "scripts" / "council_loop.py")
loop = importlib.util.module_from_spec(spec)
spec.loader.exec_module(loop)
os.environ.setdefault("REVIEW_COUNCIL_DISPATCHED", "1")

PROPOSAL = """# Proposal

## Why

The gate fails on a high finding, so the tree cannot ship.

## What Changes

- The two paths become one.

## Capabilities

- `rounds`

## Impact

`scripts/x.py`.
"""

SPEC_OK = """# Spec Delta

## ADDED Requirements

### Requirement: One path, not two

The fixture SHALL resolve through a single path.

#### Scenario: The second path is used

- **WHEN** a caller passes the legacy path
- **THEN** it is rewritten to the canonical one
"""

TASKS_OK = """# Tasks

## 1. Work

- [ ] 1.1 Rewrite the legacy path.
- [ ] 1.2 Prove it: `pytest tests/ -q`.
"""


def _change(root: pathlib.Path, *, proposal=PROPOSAL, spec_text=SPEC_OK, tasks=TASKS_OK,
            name="fix-the-path") -> pathlib.Path:
    change = root / "changes" / name
    (change / "specs" / "rounds").mkdir(parents=True, exist_ok=True)
    if proposal is not None:
        (change / "proposal.md").write_text(proposal, encoding="utf-8")
    if spec_text is not None:
        (change / "specs" / "rounds" / "spec.md").write_text(spec_text, encoding="utf-8")
    if tasks is not None:
        (change / "tasks.md").write_text(tasks, encoding="utf-8")
    return root / "changes"


def test_a_well_formed_change_validates():
    root = pathlib.Path(tempfile.mkdtemp())
    result = loop.validate_handover(_change(root))
    assert result["found"] and result["valid"], result["problems"]
    assert result["changes"][0]["name"] == "fix-the-path"


def test_the_archive_directory_is_not_treated_as_a_change():
    """Scaffolding a handover creates `changes/archive/`; it is bookkeeping, not a change.

    Found by the first live run: a correct scaffold failed validation because the archive was
    read as an empty change.
    """
    root = pathlib.Path(tempfile.mkdtemp())
    changes = _change(root, name="close-round-1-findings")
    (changes / "archive" / "some-old-change").mkdir(parents=True)
    result = loop.validate_handover(changes)
    assert result["found"] and result["valid"], result["problems"]
    assert [c["name"] for c in result["changes"]] == ["close-round-1-findings"]


def test_an_empty_scaffold_is_invalid():
    """`.openspec.yaml` alone is an empty change, and must be reported as one."""
    root = pathlib.Path(tempfile.mkdtemp())
    change = root / "changes" / "scaffolded-but-empty"
    change.mkdir(parents=True)
    (change / ".openspec.yaml").write_text("schema: spec-driven\n", encoding="utf-8")
    result = loop.validate_handover(root / "changes")
    assert result["found"] and not result["valid"]
    assert any("proposal.md missing" in p for p in result["problems"]), result["problems"]


def test_no_change_is_reported_as_absent_not_valid():
    result = loop.validate_handover(pathlib.Path(tempfile.mkdtemp()) / "changes")
    assert result["found"] is False
    assert result["valid"] is False


def test_a_requirement_without_a_scenario_is_named():
    root = pathlib.Path(tempfile.mkdtemp())
    bad = "# Spec Delta\n\n## ADDED Requirements\n\n### Requirement: Unproven\n\nIt SHALL work.\n"
    result = loop.validate_handover(_change(root, spec_text=bad))
    assert not result["valid"]
    assert any("has no scenario" in p for p in result["problems"]), result["problems"]


def test_a_scenario_without_then_is_named():
    root = pathlib.Path(tempfile.mkdtemp())
    bad = ("# Spec Delta\n\n## ADDED Requirements\n\n### Requirement: Half a scenario\n\n"
           "It SHALL work.\n\n#### Scenario: Only when\n\n- **WHEN** it runs\n- and nothing else\n")
    result = loop.validate_handover(_change(root, spec_text=bad))
    assert not result["valid"]
    assert any("**WHEN** and **THEN**" in p for p in result["problems"]), result["problems"]


def test_a_proposal_without_why_is_named():
    root = pathlib.Path(tempfile.mkdtemp())
    result = loop.validate_handover(_change(root, proposal="# Proposal\n\n## What Changes\n\n- x\n"))
    assert not result["valid"]
    assert any("## Why" in p for p in result["problems"]), result["problems"]


def test_tasks_without_a_checkbox_is_named():
    root = pathlib.Path(tempfile.mkdtemp())
    result = loop.validate_handover(_change(root, tasks="# Tasks\n\n1. do it\n"))
    assert not result["valid"]
    assert any("no checkbox task" in p for p in result["problems"]), result["problems"]


def test_a_real_archived_change_passes_this_check():
    """The check must accept what the toolchain actually produces, not only my fixtures.

    Optional: skips when the sibling skill repository is absent, like the claim audit's own
    sibling check.
    """
    archived = (REPO.parent / "hermes-agent" / "openspec" / "changes" / "archive")
    if not archived.is_dir():
        print("    (skipped: no sibling checkout at %s)" % archived)
        return
    result = loop.validate_handover(archived)
    assert result["found"], "no archived changes found to check against"
    assert result["valid"], result["problems"]


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
