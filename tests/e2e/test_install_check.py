"""`install.sh --check` verifies an install without changing it.

The check is the difference between "I installed it" and "the host reads this library".
Each case below is one scenario from the change's delta.
"""
from __future__ import annotations

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
    assert result.returncode == 0, result.stderr


def an_entry(tmp_path: Path) -> Path:
    return sorted(path for path in tmp_path.iterdir() if path.is_symlink())[0]


def test_a_matching_install_passes(tmp_path: Path) -> None:
    installed(tmp_path)
    result = run(tmp_path, "--check")
    assert result.returncode == 0, result.stdout + result.stderr
    assert str(tmp_path) in result.stdout


def test_a_missing_skill_is_named(tmp_path: Path) -> None:
    installed(tmp_path)
    victim = an_entry(tmp_path)
    victim.unlink()
    result = run(tmp_path, "--check")
    assert result.returncode == 1
    assert victim.name in result.stdout + result.stderr


def test_a_foreign_link_is_named(tmp_path: Path) -> None:
    installed(tmp_path)
    victim = an_entry(tmp_path)
    victim.unlink()
    elsewhere = tmp_path.parent / "elsewhere"
    elsewhere.mkdir(exist_ok=True)
    victim.symlink_to(elsewhere)
    result = run(tmp_path, "--check")
    assert result.returncode == 1
    assert "foreign" in (result.stdout + result.stderr).lower()
