"""`install.sh --check` verifies an install without changing it.

The check is the difference between "I installed it" and "the host reads this library".
Each case is one scenario from the change's delta.

Two platforms, two shapes: `ln -s` on Linux produces links, MSYS on Windows falls back to
copying. The check accepts both, so nothing here assumes which one it got -- a test that
only holds where symlinks work would be a test that fails on the platform in CI.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
INSTALL = ROOT / "install.sh"


def run(target: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sh", str(INSTALL), str(target), *args],
        capture_output=True, text=True, cwd=ROOT,
    )


def installed(tmp_path: Path) -> None:
    result = run(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr


def an_entry(tmp_path: Path) -> Path:
    return sorted(path for path in tmp_path.iterdir())[0]


def test_a_matching_install_passes(tmp_path: Path) -> None:
    installed(tmp_path)
    result = run(tmp_path, "--check")
    assert result.returncode == 0, result.stdout + result.stderr
    assert str(tmp_path) in result.stdout


def test_a_missing_skill_is_named(tmp_path: Path) -> None:
    installed(tmp_path)
    victim = an_entry(tmp_path)
    if victim.is_symlink():
        victim.unlink()
    else:
        shutil.rmtree(victim)
    result = run(tmp_path, "--check")
    assert result.returncode == 1
    assert victim.name in result.stdout + result.stderr


def test_a_stale_copy_is_named(tmp_path: Path) -> None:
    installed(tmp_path)
    victim = an_entry(tmp_path)
    if victim.is_symlink():
        source = victim.resolve()
        victim.unlink()
        # `copy_function=copyfile` so the copy is writable: the store's SKILL.md is 0444
        # and `copytree` would preserve that, leaving the test unable to edit its fixture.
        shutil.copytree(source, victim, copy_function=shutil.copyfile)
    # A directory copied by `install.sh` keeps the store's mode too.
    (victim / "SKILL.md").chmod(0o644)
    (victim / "SKILL.md").write_text("---\nname: changed\n---\n", encoding="utf-8")
    result = run(tmp_path, "--check")
    assert result.returncode == 1
    assert "stale" in (result.stdout + result.stderr).lower()


def test_an_entry_that_is_not_a_skill_is_named(tmp_path: Path) -> None:
    installed(tmp_path)
    victim = an_entry(tmp_path)
    if victim.is_symlink():
        victim.unlink()
    else:
        shutil.rmtree(victim)
    victim.write_text("not a skill\n", encoding="utf-8")
    result = run(tmp_path, "--check")
    assert result.returncode == 1
    assert "foreign" in (result.stdout + result.stderr).lower()
