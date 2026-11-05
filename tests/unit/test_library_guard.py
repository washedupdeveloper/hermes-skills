"""library-guard: the contract, the hook, and the negative controls.

Every rule here is exercised in both directions — a clean skill passes *and* the same skill with
one field broken fails — because a guard never observed to block is a guess.
"""
import importlib.util
import json
import os
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
MODULE = REPO / "plugins/library-guard/library_guard.py"
spec = importlib.util.spec_from_file_location("library_guard", MODULE)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

CLEAN = """---
name: sample
description: "Use when testing the guard. Does one thing."
version: 1.0.0
author: user
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [test]
---

# sample
"""


def _write(tmp_path: Path, text: str, dirname: str = "sample") -> Path:
    directory = tmp_path / "skills" / "software-development" / dirname
    directory.mkdir(parents=True)
    path = directory / "SKILL.md"
    path.write_text(text, encoding="utf-8")
    return path


# --- the contract has one home -------------------------------------------------


def test_the_mirror_equals_the_repository_contract():
    """DEFAULTS is a copy with an owner: if the file changes and the mirror does not, fail here."""
    on_disk = json.loads((REPO / "library" / "contract.json").read_text(encoding="utf-8"))
    on_disk.pop("_why", None)
    mirror = dict(guard.DEFAULTS)
    assert on_disk == mirror


def test_the_contract_is_found_from_the_plugin_directory():
    assert guard.repository_root() == REPO
    assert guard.contract()["description_window"] == 57


# --- the validator -------------------------------------------------------------


def test_a_clean_skill_has_no_violations():
    assert guard.check_skill_text(CLEAN, "sample") == []


@pytest.mark.parametrize(
    "mutation, expected",
    [
        (lambda t: t.replace("description: \"Use when testing the guard. Does one thing.\"",
                             "description: \"" + "x" * 40 + " a description far past the index window\""),
         "the index window is 57"),
        (lambda t: t.replace("name: sample", "name: other"), "does not match its directory"),
        (lambda t: t.replace("license: MIT\n", ""), "missing `license`"),
        (lambda t: t.replace("platforms: [linux, macos, windows]", "platforms: linux"),
         "must be a bracketed list"),
        (lambda t: t.replace("\n", "\r\n"), "CRLF"),
        (lambda t: "no frontmatter\n", "does not start with a '---' frontmatter block"),
        (lambda t: t.replace("\n---", "", 1), "never closed"),
    ],
)
def test_one_broken_field_is_one_named_violation(mutation, expected):
    violations = guard.check_skill_text(mutation(CLEAN), "sample")
    assert any(expected in v for v in violations), violations


def test_the_window_is_read_from_the_contract_not_hardcoded():
    """Negative control: shrink the window and a previously-valid description fails."""
    tight = dict(guard.DEFAULTS, description_window=10)
    assert guard.check_skill_text(CLEAN, "sample", settings=tight)


# --- pre_tool_call: a bundled skill is not ours to edit ------------------------


def test_a_write_into_a_bundled_skill_is_blocked(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "skills").mkdir(parents=True)
    (home / "skills" / ".bundled_manifest").write_text("sample:deadbeef\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(guard, "_BUNDLED", None)

    target = home / "skills" / "sample" / "SKILL.md"
    directive = guard.on_pre_tool_call(tool_name="write_file", args={"path": str(target)})

    assert directive is not None
    assert directive["action"] == "block"
    assert "hermes update" in directive["message"]


def test_a_write_into_our_own_tree_is_allowed(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "skills").mkdir(parents=True)
    (home / "skills" / ".bundled_manifest").write_text("sample:deadbeef\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(guard, "_BUNDLED", None)

    target = tmp_path / "repo" / "skills" / "devops" / "sample" / "SKILL.md"
    assert guard.on_pre_tool_call(tool_name="write_file", args={"path": str(target)}) is None


def test_a_crlf_skill_write_is_blocked_before_it_lands(tmp_path, monkeypatch):
    """The tree is LF-only and the gate rejects CRLF; the note arrives after the damage, so the
    write is refused instead."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(guard, "_BUNDLED", None)
    target = tmp_path / "repo" / "skills" / "devops" / "sample" / "SKILL.md"

    directive = guard.on_pre_tool_call(
        tool_name="write_file", args={"path": str(target), "content": CLEAN.replace("\n", "\r\n")}
    )
    assert directive is not None
    assert directive["action"] == "block"
    assert "CRLF" in directive["message"]


def test_an_lf_skill_write_is_not_blocked(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(guard, "_BUNDLED", None)
    target = tmp_path / "repo" / "skills" / "devops" / "sample" / "SKILL.md"
    assert guard.on_pre_tool_call(
        tool_name="write_file", args={"path": str(target), "content": CLEAN}
    ) is None


def test_another_tool_is_never_blocked(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(guard, "_BUNDLED", None)
    assert guard.on_pre_tool_call(tool_name="terminal", args={"command": "rm -rf /"}) is None


# --- transform_tool_result: the violation arrives with the tool result ---------


def test_a_broken_skill_write_returns_the_note(tmp_path):
    path = _write(tmp_path, CLEAN.replace("name: sample", "name: other"))
    result = guard.on_transform_tool_result(
        tool_name="write_file", args={"path": str(path)}, result="Wrote 300 bytes"
    )
    assert result.startswith("Wrote 300 bytes")
    assert guard.NOTE_PREFIX in result
    assert "does not match its directory" in result


def test_a_clean_skill_write_is_left_alone(tmp_path):
    path = _write(tmp_path, CLEAN)
    assert guard.on_transform_tool_result(
        tool_name="write_file", args={"path": str(path)}, result="Wrote 300 bytes"
    ) is None


def test_a_dict_result_gains_a_key_rather_than_losing_its_shape(tmp_path):
    path = _write(tmp_path, CLEAN.replace("license: MIT\n", ""))
    out = guard.on_transform_tool_result(
        tool_name="patch", args={"path": str(path)}, result={"success": True}
    )
    assert out["success"] is True
    assert "missing `license`" in out["library_guard"]


def test_a_write_to_something_else_is_ignored(tmp_path):
    other = tmp_path / "README.md"
    other.write_text("hi", encoding="utf-8")
    assert guard.on_transform_tool_result(
        tool_name="write_file", args={"path": str(other)}, result="ok"
    ) is None


# --- the CLI the gate runs -----------------------------------------------------


def test_the_cli_passes_on_the_real_tree(capsys):
    spec_cli = importlib.util.spec_from_file_location("skill_contract", REPO / "scripts/skill-contract.py")
    cli = importlib.util.module_from_spec(spec_cli)
    spec_cli.loader.exec_module(cli)

    assert cli.main(["--all"]) == 0
    captured = capsys.readouterr().out
    assert "0 violation(s)" in captured
    assert "skill(s)" in captured

# --- how Hermes actually loads the plugin -------------------------------------


def test_the_directory_drop_entry_imports_the_way_hermes_loads_it():
    """Hermes loads a directory plugin by file path with ``__path__`` set to that directory.

    An absolute ``from library_guard import register`` passes a plain file-path import and fails
    here, and Hermes then skips the plugin with one warning in ``logs/errors.log`` — which is how
    this was found: the unit tests were green and the guard was not loaded.
    """
    import sys

    directory = MODULE.parent
    spec = importlib.util.spec_from_file_location(
        "_library_guard_dirplugin",
        directory / "__init__.py",
        submodule_search_locations=[str(directory)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        assert callable(module.register)
    finally:
        sys.modules.pop(spec.name, None)
