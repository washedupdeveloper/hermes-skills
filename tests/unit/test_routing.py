"""The routing score is a gate, not a report.

Its claim: *a prompt that names a task selects exactly one skill.* These controls prove
the scorer can fail -- a tie is ambiguous, a prompt naming no task matches nothing, and a
score below the recorded floor exits 1. A measure that has only ever reported 100% is
indistinguishable from one that always returns the first skill alphabetically.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SPEC = importlib.util.spec_from_file_location("routing", ROOT / "scripts" / "routing-score.py")
routing = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(routing)


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "routing-score.py"), *args],
        capture_output=True, text=True, cwd=ROOT,
    )


def test_the_catalog_routes_the_corpus():
    """The claim itself: every prompt with a named task reaches its one skill."""
    result = run("--strict")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "100%" in result.stdout, result.stdout


def test_a_tie_is_ambiguous():
    """Two skills scoring the same is a routing failure, not a coin flip."""
    catalog = {
        "alpha": {"scope_triggers": ["same phrase here"], "scope_answers": ["same answer"]},
        "beta": {"scope_triggers": ["same phrase here"], "scope_answers": ["same answer"]},
    }
    got, top = routing.route("same phrase here", catalog)
    assert got == "ambiguous", (got, top)


def test_a_prompt_naming_no_task_matches_nothing():
    """A scorer that always picks something is a scorer that says nothing."""
    catalog = {
        "alpha": {"scope_triggers": ["fix a widget"], "scope_answers": ["whether a widget works"]},
    }
    got, _ = routing.route("what is the weather in oslo", catalog)
    assert got == "none", got


def test_a_score_below_the_floor_fails():
    """The ratchet: a corpus that degrades below the recorded floor turns the gate red.

    The floor is a flag, not a file the test rewrites: the suite runs inside a read-only
    store copy, and a test that edits the tree it measures is a test that can pass on a
    tree it just changed.
    """
    result = run("--strict", "--floor", "1.01")
    assert result.returncode == 1, result.stdout
    assert "floor" in (result.stdout + result.stderr)


def test_every_corpus_prompt_names_a_skill_that_exists():
    """A corpus that expects a skill nobody wrote would pass while measuring nothing."""
    skills = {path.parent.name for path in (ROOT / "skills").glob("*/*/SKILL.md")}
    corpus = routing.load_corpus()
    assert corpus, "the corpus is empty"
    ghosts = sorted({row["expect"] for row in corpus} - skills)
    assert not ghosts, f"corpus expects skills that do not exist: {ghosts}"