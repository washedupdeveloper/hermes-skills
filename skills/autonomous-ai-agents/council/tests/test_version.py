"""Tests for version.py — the semver policy in docs/VERSIONING.md.

Run standalone (no pytest needed):
    python tests/test_version.py
"""
from __future__ import annotations

import importlib.util
import os
import re
import sys
import tempfile
import types
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("version", REPO / "scripts" / "version.py")
version = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(version)


class _DeployedCopy(unittest.SkipTest):
    """A test that reads repo-only files was reached in a shipped copy.

    Subclasses `unittest.SkipTest` because pytest maps that to a SKIP natively,
    so this needs no pytest import and works in the standalone runner too.
    Calling `pytest.skip()` directly was wrong: it raises `Skipped`, which is a
    `BaseException`, so the standalone path crashed with exit 1 instead of
    skipping.
    """


def _require_repo_source() -> None:
    """Skip when this is a deployed copy, where the repo-only files are absent.

    `sync_to_skill.py` is the copier and never ships, so its absence is what
    distinguishes a deployment from the repository. Without this guard three
    tests below die with `FileNotFoundError` on `pyproject.toml` and `docs/` in
    every deployed skill -- measured, and the same guard `test_portability.py`
    and `test_skills.py` already carry.
    """
    if (REPO / "scripts" / "sync_to_skill.py").exists():
        return
    raise _DeployedCopy("deployed copy: this test asserts the repo-side wiring")



# --- semver arithmetic -------------------------------------------------------

def test_parses_a_plain_version():
    assert version.parse_version("1.2.3") == (1, 2, 3)


def test_refuses_anything_that_is_not_major_minor_patch():
    """A lenient parser accepts `1.2` and silently means `1.2.0`. Refusing is the
    only reading that cannot be wrong."""
    for bad in ("1.2", "1", "v1.2.3", "01.2.3", "1.2.3-rc1", "1.2.3+build", "", "latest"):
        try:
            version.parse_version(bad)
        except ValueError:
            continue
        raise AssertionError(f"accepted {bad!r}")


def test_a_bump_resets_everything_to_its_right():
    assert version.bump_version("1.4.2", "major") == "2.0.0"
    assert version.bump_version("1.4.2", "minor") == "1.5.0"
    assert version.bump_version("1.4.2", "patch") == "1.4.3"


def test_an_unknown_part_is_refused():
    try:
        version.bump_version("1.0.0", "feature")
    except ValueError:
        return
    raise AssertionError("accepted an unknown part")


# --- a tree to check ---------------------------------------------------------

def _tree(root: Path, *, pyproject_version: str = "1.0.0", changelog: str) -> None:
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "review-council"\nversion = "{pyproject_version}"\n'
        f'\n[tool.ruff]\nline-length = 100\n', encoding="utf-8")
    (root / "CHANGELOG.md").write_text(changelog, encoding="utf-8")


GOOD = """# Changelog

## [Unreleased]

### Added

- something new

## [1.0.0] — 2026-10-11

First release.
"""


def _check(root: Path, tag=None):
    return version.check(tag=tag, path_changelog=root / "CHANGELOG.md",
                         path_pyproject=root / "pyproject.toml")


def test_a_consistent_tree_has_no_problems():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _tree(root, changelog=GOOD)
        assert _check(root) == [], _check(root)


def test_the_real_repository_is_consistent():
    """The tree this test runs in must satisfy its own policy."""
    _require_repo_source()
    problems = version.check()
    assert not problems, "\n".join(problems)


# --- prose that quotes the version ------------------------------------------

# "Current release **v1.5.0**" is a checkable claim, and it is the one nobody
# was checking: pyproject, CHANGELOG and tags all agreed at 1.5.2 while
# docs/MILESTONES.md still advertised v1.5.0. The policy in docs/VERSIONING.md
# says a claim that can be measured must be measured; this is that measurement.
_PROSE_VERSION = re.compile(r"[Cc]urrent release\s+\*{0,2}v(\d+\.\d+\.\d+)\*{0,2}")

# Files that speak about the release to a reader. Excluded: CHANGELOG.md (it is
# the history, not a claim about now) and runs/ (records of a past moment).
_PROSE_FILES = ("README.md", "docs")


def _prose_version_claims(root: Path = REPO) -> list[tuple[str, str]]:
    """(where, version) for every "current release" claim in the prose."""
    claims: list[tuple[str, str]] = []
    for name in _PROSE_FILES:
        target = root / name
        paths = sorted(target.rglob("*.md")) if target.is_dir() else [target]
        for path in paths:
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for match in _PROSE_VERSION.finditer(text):
                claims.append((str(path.relative_to(root)), match.group(1)))
    return claims


def _wrong_claims(root: Path = REPO) -> list[tuple[str, str]]:
    current = version.read_pyproject_version(root / "pyproject.toml")
    return [(where, claimed) for where, claimed in _prose_version_claims(root)
            if claimed != current]


def test_prose_version_claims_match_the_release():
    """A doc that names the current release must name the current one.

    Skipped in a deployed copy: `docs/` does not ship, and this asserts a
    property of the repository, not of the skill.
    """
    _require_repo_source()
    current = version.read_pyproject_version(REPO / "pyproject.toml")
    wrong = _wrong_claims()
    assert not wrong, (
        f"prose claims a release other than {current}: "
        + ", ".join(f"{w} says v{c}" for w, c in wrong)
    )


def _prose_tree(root: Path, *, pyproject_version: str, readme: str,
                milestone: str) -> None:
    _tree(root, pyproject_version=pyproject_version, changelog=GOOD)
    (root / "README.md").write_text(readme, encoding="utf-8")
    (root / "docs").mkdir(exist_ok=True)
    (root / "docs" / "MILESTONES.md").write_text(milestone, encoding="utf-8")


def test_a_stale_prose_claim_is_caught():
    """The failure this check exists for: docs naming a superseded release."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _prose_tree(root, pyproject_version="1.5.2",
                    readme="Current release **v1.5.2**.\n",
                    milestone="Current release **v1.5.0**. The threshold ...\n")
        assert _wrong_claims(root) == [("docs/MILESTONES.md", "1.5.0")]


def test_agreeing_prose_is_accepted():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _prose_tree(root, pyproject_version="1.5.2",
                    readme="Current release **v1.5.2**.\n",
                    milestone="Current release v1.5.2, see the notes.\n")
        assert _wrong_claims(root) == []


def test_a_historical_version_is_not_a_current_claim():
    """A run record may name the version it ran under without being wrong."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _prose_tree(root, pyproject_version="1.5.2",
                    readme="Current release **v1.5.2**.\n",
                    milestone="Release v1.2.0 scored 74.00.\n"
                              "## [1.2.0] — 2026-10-01\n")
        assert _wrong_claims(root) == []




# --- each way the file can lie ----------------------------------------------

def test_pyproject_and_the_newest_release_must_agree():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _tree(root, pyproject_version="1.1.0", changelog=GOOD)
        problems = _check(root)
        assert any("newest release is 1.0.0" in p for p in problems), problems


def test_a_version_released_twice_is_caught():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _tree(root, changelog=GOOD + "\n## [1.0.0] — 2026-09-01\n\nAgain.\n")
        problems = _check(root)
        assert any("released more than once" in p for p in problems), problems


def test_releases_must_descend():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _tree(root, pyproject_version="1.0.0", changelog="""# Changelog

## [Unreleased]

## [0.9.0] — 2026-09-01

Old.

## [1.0.0] — 2026-10-11

Newer, but listed below.
""")
        problems = _check(root)
        assert any("must descend" in p for p in problems), problems


def test_unreleased_must_come_first():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _tree(root, changelog="""# Changelog

## [1.0.0] — 2026-10-11

First.

## [Unreleased]

### Added

- late entry
""")
        problems = _check(root)
        assert any("not the first section" in p for p in problems), problems


def test_a_missing_unreleased_section_is_caught():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _tree(root, changelog="# Changelog\n\n## [1.0.0] — 2026-10-11\n\nFirst.\n")
        problems = _check(root)
        assert any("no `## [Unreleased]`" in p for p in problems), problems


def test_a_release_needs_a_real_date():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _tree(root, changelog="""# Changelog

## [Unreleased]

## [1.0.0] — 2026-13-45

Impossible date.
""")
        problems = _check(root)
        assert any("is not a date" in p for p in problems), problems


def test_an_unparseable_heading_is_quoted_not_ignored():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _tree(root, changelog="""# Changelog

## [Unreleased]

## [1.0.0] 2026-10-11

No dash.
""")
        problems = _check(root)
        assert any("is not `## [X.Y.Z]" in p for p in problems), problems


def test_a_tag_that_disagrees_with_the_version_fails():
    """CI passes the pushed tag, so a mistyped tag fails instead of publishing."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _tree(root, changelog=GOOD)
        assert _check(root, tag="v1.0.0") == []
        problems = _check(root, tag="v1.0.1")
        assert any("tag v1.0.1 does not match" in p for p in problems), problems


# --- bump --------------------------------------------------------------------

def _bump(root: Path, part="minor", date="2026-10-17", dry_run=False):
    """Run cmd_bump against a temporary tree."""
    saved_env = os.environ.get("REVIEW_COUNCIL_AUDIENCE")
    os.environ["REVIEW_COUNCIL_AUDIENCE"] = "dev"
    try:
        return version.cmd_bump(types.SimpleNamespace(
            part=part, date=date, dry_run=dry_run, repo=str(root)))
    finally:
        if saved_env is None:
            os.environ.pop("REVIEW_COUNCIL_AUDIENCE", None)
        else:
            os.environ["REVIEW_COUNCIL_AUDIENCE"] = saved_env


def test_bump_moves_unreleased_to_a_dated_release():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _tree(root, changelog=GOOD)
        assert _bump(root) == 0

        text = (root / "CHANGELOG.md").read_text(encoding="utf-8")
        assert "## [Unreleased]\n\n## [1.1.0] — 2026-10-17" in text, text
        assert "- something new" in text, "the entry must survive the move"
        assert version.read_pyproject_version(root / "pyproject.toml") == "1.1.0"
        # and the result satisfies the policy it just changed
        assert _check(root) == [], _check(root)


def test_bump_leaves_an_empty_unreleased_behind():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _tree(root, changelog=GOOD)
        _bump(root)
        log = version.read_changelog(root / "CHANGELOG.md")
        assert log.unreleased_line == min([log.unreleased_line] +
                                          [r.line for r in log.releases])
        assert log.unreleased_body.strip() == "", repr(log.unreleased_body)


def test_bump_refuses_an_empty_unreleased_section():
    """Nothing to release: a heading with no entries is not a release."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _tree(root, changelog="# Changelog\n\n## [Unreleased]\n\n## [1.0.0] — 2026-10-11\n\nFirst.\n")
        assert _bump(root) == 1
        assert version.read_pyproject_version(root / "pyproject.toml") == "1.0.0"


def test_bump_refuses_when_pyproject_and_changelog_disagree():
    """Bumping from a disagreement would pick one of two numbers arbitrarily."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _tree(root, pyproject_version="1.0.0", changelog=GOOD.replace("1.0.0", "0.9.0"))
        assert _bump(root) == 1
        assert version.read_pyproject_version(root / "pyproject.toml") == "1.0.0"


def test_bump_dry_run_writes_nothing():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _tree(root, changelog=GOOD)
        before = (root / "CHANGELOG.md").read_text(encoding="utf-8")
        assert _bump(root, dry_run=True) == 0
        assert (root / "CHANGELOG.md").read_text(encoding="utf-8") == before
        assert version.read_pyproject_version(root / "pyproject.toml") == "1.0.0"


def test_bump_is_devshell_only():
    """It edits the repository, so the shipped app must refuse it."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _tree(root, changelog=GOOD)
        saved_env = os.environ.pop("REVIEW_COUNCIL_AUDIENCE", None)
        try:
            rc = version.cmd_bump(types.SimpleNamespace(
                part="minor", date="2026-10-17", dry_run=False, repo=str(root)))
        finally:
            if saved_env is not None:
                os.environ["REVIEW_COUNCIL_AUDIENCE"] = saved_env
        assert rc == 2, rc
        assert version.read_pyproject_version(root / "pyproject.toml") == "1.0.0"


# --- which repository is meant ----------------------------------------------
#
# The CLI runs from a nix store copy, so `__file__` is not the working tree. This
# is the bug that made `council version check` read the store's missing
# `pyproject.toml` instead of the repository the user was standing in.

def test_find_root_prefers_the_directory_you_stand_in():
    """No argument means the repository the command was run in."""
    _require_repo_source()
    assert os.path.samefile(version.find_root(), REPO)


def test_find_root_walks_up_from_a_subdirectory():
    """A command run in `docs/` is still about the repository."""
    _require_repo_source()
    saved = Path.cwd()
    os.chdir(REPO / "docs")
    try:
        assert os.path.samefile(version.find_root(), REPO)
    finally:
        os.chdir(saved)


def test_find_root_honours_an_explicit_repo():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _tree(root, changelog=GOOD)
        # samefile, not ==: macOS resolves /var to /private/var and Windows can
        # return a short path, so two names for one directory must compare equal.
        assert os.path.samefile(version.find_root(str(root)), root)


def test_find_root_refuses_a_directory_that_is_not_a_repository():
    with tempfile.TemporaryDirectory() as td:
        try:
            version.find_root(td)
        except SystemExit as exc:
            assert "no pyproject.toml" in str(exc), exc
            return
        raise AssertionError("accepted a directory with no pyproject.toml")


def main() -> int:
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    passed = failed = skipped = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS {name}")
            passed += 1
        except _DeployedCopy:
            print(f"  SKIP {name} (deployed copy)")
            skipped += 1
        except AssertionError as exc:
            print(f"  FAIL {name} -> {exc}")
            failed += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  ERROR {name} -> {type(exc).__name__}: {exc}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed, {skipped} skipped")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
