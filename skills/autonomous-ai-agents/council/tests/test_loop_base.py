"""The loop's base tree: materialised from git, without a .git of its own.

Run standalone (no pytest needed):
    python tests/test_loop_base.py
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS))

_spec = importlib.util.spec_from_file_location("council_loop", SCRIPTS / "council_loop.py")
loop = importlib.util.module_from_spec(_spec)
sys.modules["council_loop"] = loop
_spec.loader.exec_module(loop)


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def make_repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    git(repo, "init", "-q", ".")
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "t")
    (repo / "app.py").write_text("x = 1\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")
    (repo / "app.py").write_text("x = 2\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "head")
    return repo


def test_the_base_tree_holds_the_old_content():
    with tempfile.TemporaryDirectory() as tmp:
        repo = make_repo(Path(tmp))
        base = loop.materialise_base(repo, "HEAD~1")
        try:
            assert base is not None, "materialise_base returned None"
            assert (base / "app.py").read_text(encoding="utf-8") == "x = 1\n"
        finally:
            if base:
                import shutil
                shutil.rmtree(base, ignore_errors=True)


def test_the_base_tree_has_no_git_directory():
    """A proof that runs `git` in the base tree must not answer about the real repository."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = make_repo(Path(tmp))
        base = loop.materialise_base(repo, "HEAD~1")
        try:
            assert base is not None
            assert not (base / ".git").exists(), "the base tree carries a .git"
        finally:
            if base:
                import shutil
                shutil.rmtree(base, ignore_errors=True)


def test_an_unknown_revision_returns_none():
    with tempfile.TemporaryDirectory() as tmp:
        repo = make_repo(Path(tmp))
        assert loop.materialise_base(repo, "no-such-rev") is None


def test_a_non_repository_returns_none():
    with tempfile.TemporaryDirectory() as tmp:
        assert loop.materialise_base(Path(tmp), "HEAD") is None


def test_meta_records_which_question_was_asked():
    """Two rounds with different prompts are not comparable; the digest is how you can tell."""
    import json

    with tempfile.TemporaryDirectory() as tmp:
        round_dir = Path(tmp) / "round-1"
        round_dir.mkdir()
        repo = Path(tmp) / "repo"
        repo.mkdir()
        loop.write_meta(round_dir, repo, "whole-repo", 1, ["python"], "a" * 40)
        first = json.loads((round_dir / "meta.json").read_text())
        loop.write_meta(round_dir, repo, "whole-repo", 1, ["python"], "a" * 40)
        second = json.loads((round_dir / "meta.json").read_text())
    digest = first.get("harness_sha") or ""
    assert len(digest) == 64 and all(c in "0123456789abcdef" for c in digest), digest
    assert digest == second["harness_sha"], "the digest is not stable across identical runs"
    assert loop.harness_digest("some-other-profile") != digest, \
        "the digest ignores the profile, so two different reviewers would look comparable"


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok   {name}")
            except AssertionError as exc:
                failures += 1
                print(f"FAIL {name}: {exc}")
            except Exception as exc:  # noqa: BLE001
                failures += 1
                print(f"FAIL {name}: {type(exc).__name__}: {exc}")
    total = len([n for n in globals() if n.startswith("test_")])
    print(f"\n{total - failures} passed, {failures} failed")
    raise SystemExit(1 if failures else 0)
