"""The repository's communication and dependency policy is executable."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_dependabot_checks_actions_and_python_weekly() -> None:
    text = read(".github/dependabot.yml")
    assert 'package-ecosystem: "github-actions"' in text
    assert 'package-ecosystem: "pip"' in text
    assert text.count('interval: "weekly"') == 2


def test_the_nix_dependency_workflow_is_weekly_and_opens_a_pr() -> None:
    text = read(".github/workflows/dependencies.yml")
    assert 'cron: "0 6 * * 1"' in text
    assert "nix flake update" in text
    assert "gh pr create" in text
    assert "auto_merge" not in text.lower()
    assert "gh pr merge" not in text.lower()


def test_agents_makes_the_openspec_change_the_brief() -> None:
    text = read("AGENTS.md")
    assert "openspec/changes/" in text
    assert "subagent" in text.lower()
    assert "chat is a short pointer" in text.lower()
