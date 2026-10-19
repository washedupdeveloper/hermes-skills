#!/usr/bin/env python3
"""version.py — check and bump the release version.

`docs/VERSIONING.md` is the policy; this is the mechanism that enforces it. The
version lives in exactly one place, `pyproject.toml`, and the CHANGELOG is checked
against it, so the two cannot drift the way they did between `v1.0.0` and the six
commits that followed it.

Three verbs:

    council version show                    what version is this tree
    council version check [--tag vX.Y.Z]    exit 1 on any inconsistency
    council version bump {major|minor|patch} move [Unreleased] to a dated release

`check` never touches the network or git: CI passes the pushed tag with `--tag`, and
the nix check runs it without one, so the same code guards both. `bump` edits two
files and prints the tag command instead of running it — tagging is publishing, and
publishing is a decision.

Exit codes follow the gate: 0 ok, 1 the tree is inconsistent, 2 could not run.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import re
import sys
from pathlib import Path
from typing import List, NamedTuple, Optional, Tuple

REPO = Path(__file__).resolve().parent.parent
PYPROJECT = REPO / "pyproject.toml"
CHANGELOG = REPO / "CHANGELOG.md"

VERSION_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
# `## [1.0.0] — 2026-10-11`. Em dash in the file; a hyphen is accepted so a
# hand-written entry is not rejected over punctuation.
RELEASE_RE = re.compile(r"^## \[(\d+\.\d+\.\d+)\]\s+[—–-]\s+(\d{4}-\d{2}-\d{2})\s*$")
UNRELEASED = "## [Unreleased]"
PARTS = ("major", "minor", "patch")

# Prose that quotes the release, and the files allowed to. Excluded deliberately:
# CHANGELOG.md is history, and runs/ records a past moment.
PROSE_VERSION = re.compile(r"[Cc]urrent release\s+\*{0,2}v(\d+\.\d+\.\d+)\*{0,2}")
PROSE_FILES = ("README.md", "docs")


class Release(NamedTuple):
    version: str
    date: str
    line: int


def parse_version(text: str) -> Tuple[int, int, int]:
    """Strict `X.Y.Z`. Pre-release and build metadata are refused, not guessed."""
    match = VERSION_RE.match(text.strip())
    if not match:
        raise ValueError(f"{text!r} is not MAJOR.MINOR.PATCH")
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def format_version(parts: Tuple[int, int, int]) -> str:
    return ".".join(str(p) for p in parts)


def bump_version(version: str, part: str) -> str:
    """Semver arithmetic: a bump resets the parts to its right."""
    major, minor, patch = parse_version(version)
    if part == "major":
        return format_version((major + 1, 0, 0))
    if part == "minor":
        return format_version((major, minor + 1, 0))
    if part == "patch":
        return format_version((major, minor, patch + 1))
    raise ValueError(f"unknown part {part!r}; expected one of {', '.join(PARTS)}")


def read_pyproject_version(path: Optional[Path] = None) -> str:
    """The `version =` line of `[project]`, and nothing else."""
    path = path or PYPROJECT
    text = path.read_text(encoding="utf-8")
    section = re.search(r"^\[project\]\s*$(.*?)(?=^\[|\Z)", text, re.M | re.S)
    if not section:
        raise ValueError(f"{path}: no [project] section")
    match = re.search(r'^version\s*=\s*"([^"]+)"', section.group(1), re.M)
    if not match:
        raise ValueError(f"{path}: [project] has no version")
    return match.group(1)


def write_pyproject_version(version: str, path: Optional[Path] = None) -> None:
    path = path or PYPROJECT
    text = path.read_text(encoding="utf-8")
    section = re.search(r"^\[project\]\s*$(.*?)(?=^\[|\Z)", text, re.M | re.S)
    if not section:
        raise ValueError(f"{path}: no [project] section")
    body = section.group(1)
    replaced, count = re.subn(r'^version\s*=\s*"[^"]+"', f'version = "{version}"',
                              body, count=1, flags=re.M)
    if count != 1:
        raise ValueError(f"{path}: [project] has no version to replace")
    path.write_text(text[:section.start(1)] + replaced + text[section.end(1):],
                    encoding="utf-8")


class Changelog(NamedTuple):
    lines: List[str]
    unreleased_line: int
    unreleased_body: str
    releases: List[Release]


def read_changelog(path: Optional[Path] = None) -> Changelog:
    """Split the file at its `## ` headings. Order in the file is the order returned."""
    path = path or CHANGELOG
    lines = path.read_text(encoding="utf-8").splitlines()
    headings = [(i, line) for i, line in enumerate(lines) if line.startswith("## [")]
    if not headings:
        raise ValueError(f"{path}: no `## [` headings")

    releases: List[Release] = []
    unreleased_line = -1
    unreleased_body = ""
    for index, (line_no, line) in enumerate(headings):
        end = headings[index + 1][0] if index + 1 < len(headings) else len(lines)
        body = "\n".join(lines[line_no + 1:end])
        if line.strip() == UNRELEASED:
            unreleased_line = line_no
            unreleased_body = body
            continue
        match = RELEASE_RE.match(line)
        if not match:
            # Unparseable heading: keep the line so `check` can quote it instead of
            # rejecting the file here.
            releases.append(Release("", "", line_no))
            continue
        releases.append(Release(match.group(1), match.group(2), line_no))
    return Changelog(lines, unreleased_line, unreleased_body, releases)


def check(tag: Optional[str] = None, path_changelog: Optional[Path] = None,
          path_pyproject: Optional[Path] = None) -> List[str]:
    """Every inconsistency, as messages. Empty means consistent."""
    path_changelog = path_changelog or CHANGELOG
    path_pyproject = path_pyproject or PYPROJECT
    problems: List[str] = []

    try:
        version = read_pyproject_version(path_pyproject)
    except ValueError as exc:
        return [str(exc)]
    try:
        parse_version(version)
    except ValueError as exc:
        problems.append(f"pyproject.toml: {exc}")

    try:
        log = read_changelog(path_changelog)
    except ValueError as exc:
        return problems + [str(exc)]

    if log.unreleased_line < 0:
        problems.append("CHANGELOG.md: no `## [Unreleased]` section")
    elif log.unreleased_line != min(r.line for r in log.releases + [Release("", "", 10 ** 9)]):
        first_heading = min([log.unreleased_line] + [r.line for r in log.releases])
        if log.unreleased_line != first_heading:
            problems.append("CHANGELOG.md: `## [Unreleased]` is not the first section")

    for release in log.releases:
        if not release.version:
            problems.append(f"CHANGELOG.md:{release.line + 1}: heading is not "
                            f"`## [X.Y.Z] — YYYY-MM-DD`")
            continue
        try:
            parse_version(release.version)
        except ValueError as exc:
            problems.append(f"CHANGELOG.md:{release.line + 1}: {exc}")
        try:
            _dt.date.fromisoformat(release.date)
        except ValueError:
            problems.append(f"CHANGELOG.md:{release.line + 1}: {release.date} is not a date")

    versions = [r.version for r in log.releases if r.version]
    for earlier, later in zip(versions, versions[1:]):
        if parse_version(earlier) <= parse_version(later):
            problems.append(f"CHANGELOG.md: {earlier} is listed before {later}; "
                            f"releases must descend")
    duplicates = sorted({v for v in versions if versions.count(v) > 1})
    if duplicates:
        problems.append(f"CHANGELOG.md: released more than once: {', '.join(duplicates)}")

    if versions and versions[0] != version:
        problems.append(f"pyproject.toml says {version}, the newest release is "
                        f"{versions[0]}")

    if tag is not None:
        wanted = tag[1:] if tag.startswith("v") else tag
        if wanted != version:
            problems.append(f"tag {tag} does not match pyproject.toml {version}")

    # Prose claims are checkable (docs/VERSIONING.md) and were the part that rotted:
    # pyproject, CHANGELOG and tags agreed while a doc advertised a superseded version.
    # Rooted at path_pyproject's parent so a fixture tree validates itself.
    problems.extend(stale_prose_claims(path_pyproject.parent))

    return problems


def _unreleased_categories(body: str) -> List[str]:
    return [line.strip() for line in body.splitlines() if line.startswith("### ")]


def find_root(explicit: Optional[str] = None) -> Path:
    """The repository this command is about.

    The CLI runs from a nix store copy — the devshell's `council` is a launcher into
    `packages.dev-framework` — so `__file__` is NOT the working tree, and a check
    written against it would read the store's copy of `pyproject.toml`, which does not
    exist because the shipped tree deliberately carries no build metadata.

    So the working tree is where the user stands: CWD first, walking up. `--repo`
    overrides, which is what CI and a caller in another directory use. The module's own
    location is the last resort, and that is exactly right for the sandboxed nix check,
    which runs this file from a copy of the tree it should inspect.
    """
    if explicit:
        root = Path(explicit).expanduser().resolve()
        if not (root / "pyproject.toml").is_file():
            raise SystemExit(f"version: {root} has no pyproject.toml")
        return root
    here = Path.cwd().resolve()
    for candidate in (here, *here.parents):
        if (candidate / "pyproject.toml").is_file() and (candidate / "CHANGELOG.md").is_file():
            return candidate
    if (REPO / "pyproject.toml").is_file():
        return REPO
    raise SystemExit(
        "version: no pyproject.toml here or above. Run this from the repository root, "
        "or pass --repo <path>.")


def cmd_show(args: argparse.Namespace) -> int:
    print(read_pyproject_version(find_root(args.repo) / "pyproject.toml"))
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    root = find_root(args.repo)
    problems = check(tag=args.tag,
                     path_changelog=root / "CHANGELOG.md",
                     path_pyproject=root / "pyproject.toml")
    if problems:
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    version = read_pyproject_version(root / "pyproject.toml")
    suffix = f" (tag {args.tag})" if args.tag else ""
    print(f"  version {version} is consistent{suffix}")
    return 0


def prose_version_claims(root: Path) -> List[Tuple[Path, str]]:
    """Every "current release vX.Y.Z" claim in the prose, as (path, version).

    A claim that can be measured must be measured (`docs/VERSIONING.md`), and this is
    the one nobody was checking: pyproject, CHANGELOG and tags all agreed at 1.5.2 while
    `docs/MILESTONES.md` still advertised v1.5.0.

    It lives here rather than in the test because TWO callers need the same definition:
    `check` validates the claims, and `bump` rewrites them. A second copy in the test
    would let the two drift, which is the failure this function exists to catch.
    """
    claims: List[Tuple[Path, str]] = []
    for name in PROSE_FILES:
        target = root / name
        paths = sorted(target.rglob("*.md")) if target.is_dir() else [target]
        for path in paths:
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for match in PROSE_VERSION.finditer(text):
                claims.append((path, match.group(1)))
    return claims


def stale_prose_claims(root: Path) -> List[str]:
    """Problems for prose claims that name a release other than the current one."""
    current = read_pyproject_version(root / "pyproject.toml")
    problems: List[str] = []
    for path, claimed in prose_version_claims(root):
        if claimed != current:
            rel = path.relative_to(root).as_posix()
            problems.append(f"{rel}: claims v{claimed} but the release is {current}")
    return problems


def rewrite_prose_versions(root: Path, new: str) -> List[Path]:
    """Point every "current release" claim at *new*. Returns the files changed."""
    changed: List[Path] = []
    for path in sorted({p for p, _ in prose_version_claims(root)}):
        text = path.read_text(encoding="utf-8")
        replaced = PROSE_VERSION.sub(
            lambda m: m.group(0).replace(m.group(1), new), text)
        if replaced != text:
            path.write_text(replaced, encoding="utf-8", newline="\n")
            changed.append(path)
    return changed


def cmd_bump(args: argparse.Namespace) -> int:
    if os.environ.get("REVIEW_COUNCIL_AUDIENCE") != "dev":
        print("version bump: this edits the repository, so it is devshell-only.\n"
              "  run it from `nix develop`, or check a version with `council version check`.",
              file=sys.stderr)
        return 2

    root = find_root(args.repo)
    changelog = root / "CHANGELOG.md"
    pyproject = root / "pyproject.toml"

    log = read_changelog(changelog)
    if log.unreleased_line < 0:
        print("CHANGELOG.md: no `## [Unreleased]` section", file=sys.stderr)
        return 1
    if not _unreleased_categories(log.unreleased_body):
        print("CHANGELOG.md: `## [Unreleased]` has no `### Added|Changed|Fixed` entry.\n"
              "  a release needs at least one entry; nothing to bump.", file=sys.stderr)
        return 1

    current = read_pyproject_version(pyproject)
    releases = [r.version for r in log.releases if r.version]
    if releases and releases[0] != current:
        print(f"pyproject.toml says {current} but the newest release is {releases[0]}.\n"
              f"  fix the disagreement before bumping; one of the two is wrong.",
              file=sys.stderr)
        return 1

    try:
        new = bump_version(current, args.part)
    except ValueError as exc:
        print(f"version bump: {exc}", file=sys.stderr)
        return 2
    if releases and parse_version(new) <= parse_version(releases[0]):
        print(f"version bump: {new} does not increase on {releases[0]}", file=sys.stderr)
        return 1

    date = args.date or _dt.date.today().isoformat()
    try:
        _dt.date.fromisoformat(date)
    except ValueError:
        print(f"version bump: --date {date} is not YYYY-MM-DD", file=sys.stderr)
        return 2

    # One line becomes three: empty Unreleased, blank, new heading. The blank already
    # after the old heading becomes the gap under the new one.
    lines = list(log.lines)
    lines[log.unreleased_line] = f"{UNRELEASED}\n\n## [{new}] — {date}"

    if args.dry_run:
        print(f"  would release {new} on {date}")
        print(f"  would set pyproject.toml version = \"{new}\"")
        print(f"  then: git tag -a v{new} -m \"v{new}\"")
        return 0

    changelog.write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_pyproject_version(new, pyproject)
    # Same commit, same command: otherwise the prose rots until the test catches it --
    # which it did three releases running.
    touched = rewrite_prose_versions(root, new)
    print(f"  released {new} on {date}; pyproject.toml updated")
    for path in touched:
        print(f"  prose claim updated: {path.relative_to(root).as_posix()}")
    print(f"  next:  git tag -a v{new} -m \"v{new}\"  &&  git push origin v{new}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="council version",
        description="Check and bump the release version (docs/VERSIONING.md).")
    sub = parser.add_subparsers(dest="cmd")

    show = sub.add_parser("show", help="print the version of this tree")
    show.add_argument("--repo", metavar="PATH", default=None,
                      help="the repository (default: here, then upwards)")
    show.set_defaults(func=cmd_show)

    check_p = sub.add_parser("check", help="exit 1 on any version inconsistency")
    check_p.add_argument("--repo", metavar="PATH", default=None,
                         help="the repository (default: here, then upwards)")
    check_p.add_argument("--tag", metavar="vX.Y.Z",
                         help="also require this tag to match (CI passes the pushed tag)")
    check_p.set_defaults(func=cmd_check)

    bump = sub.add_parser("bump", help="move [Unreleased] to a dated release")
    bump.add_argument("part", choices=PARTS)
    bump.add_argument("--repo", metavar="PATH", default=None,
                      help="the repository (default: here, then upwards)")
    bump.add_argument("--date", metavar="YYYY-MM-DD", default=None,
                      help="release date (default: today)")
    bump.add_argument("--dry-run", action="store_true", help="print, write nothing")
    bump.set_defaults(func=cmd_bump)

    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    # Not a program: reached through `council <verb>`. See council.py.
    from council import require_dispatch

    require_dispatch("version")
    sys.exit(main())
