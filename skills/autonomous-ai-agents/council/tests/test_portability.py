"""Portability tests: no machine-specific assumptions in what ships.

The framework is meant to be adopted by someone else, so a hardcoded
`/home/<someone>` or `C:\\Users\\<someone>` is either a leftover from the author's
machine or an assumption that the reader's machine looks the same. Either way it
is wrong for everyone but one person.

Run standalone (no pytest needed):
    python tests/test_portability.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _require_repo() -> None:
    """Skip when this is the DEPLOYED skill rather than the repository checkout.

    `sync_to_skill.py` is the copier and is deliberately never shipped — so its
    absence means we are inside the deployment, where the repo<->deployment wiring
    these tests assert cannot hold by construction. A test that reads the copier's
    source without this guard fails there, and a suite that is always red is a
    suite whose real failures get ignored.
    """
    if (REPO / "scripts" / "sync_to_skill.py").exists():
        return
    try:
        import pytest
        pytest.skip("deployed copy: this test asserts the repo-side wiring")
    except ImportError:  # pragma: no cover — the toolchain always has pytest
        raise RuntimeError("skipped: deployed copy") from None


# Directories that are not shipped source, or are fixture data.
SKIP_DIRS = {
    ".git",
    ".review-council",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "node_modules",
}
SKIP_PATHS = {"tests/golden"}

# A drive letter must not be preceded by a letter (that is what makes `https://`
# match `s:/`) and must be followed by a separator then a path character.
PERSONAL = re.compile(
    r"(?<![A-Za-z0-9])"
    r"(?:"
    r"/home/(?P<unix>[A-Za-z0-9_.-]+)"
    r"|/Users/(?P<mac>[A-Za-z0-9_.-]+)"
    r"|[A-Za-z]:[\\/]Users[\\/](?P<win>[A-Za-z0-9_.-]+)"
    r")"
)

# Names that are NOT somebody's machine. Each is here for a stated reason:
#   council   -- the container image's own user (flake.nix config.User)
#   otheruser -- the path the corpus builder plants as the COR-4 defect
#   user, x, you, root -- placeholders
ALLOWED = {"council", "otheruser", "user", "x", "you", "root"}


def _shipped_files():
    for p in sorted(REPO.rglob("*")):
        # A symlink is not shipped source: `result` points into the nix store, and
        # following it would walk hundreds of unrelated paths.
        if p.is_symlink() or not p.is_file():
            continue
        rel = p.relative_to(REPO)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if any(str(rel).startswith(s) for s in SKIP_PATHS):
            continue
        if p.suffix in {".pyc", ".png", ".jpg", ".gz", ".tar", ".lock"}:
            continue
        if p.name == "flake.lock":
            continue
        yield rel


def find_personal_paths():
    """Every (file, line, path) whose path names a person's home directory."""
    hits = []
    for rel in _shipped_files():
        try:
            text = (REPO / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            for m in PERSONAL.finditer(line):
                name = m.group("unix") or m.group("mac") or m.group("win")
                if name.lower() in ALLOWED:
                    continue
                hits.append((str(rel), i, m.group(0)))
    return hits


def test_no_personal_paths_anywhere_that_ships():
    hits = find_personal_paths()
    assert not hits, "personal paths in shipped files:\n" + "\n".join(
        f"  {f}:{n}  {p}" for f, n, p in hits
    )


def test_the_allowed_names_are_actually_present():
    """A guard on the guard.

    If every allowlisted name vanished, the check above would still pass while
    testing nothing about placeholders -- and the allowlist would silently rot
    into a list of names nobody uses.
    """
    seen = set()
    for rel in _shipped_files():
        try:
            text = (REPO / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in PERSONAL.finditer(text):
            for g in ("unix", "mac", "win"):
                if m.group(g):
                    seen.add(m.group(g).lower())
    assert {"council", "otheruser"} <= seen, seen


# --- the PATH the systemd unit builds ---------------------------------------
# The unit does NOT inherit the caller's PATH, so it writes a fixed list, and a
# forgotten location is silent: the service starts, `nix` is not found, nothing says
# so. The deleted shell version carried this guard; the list is now harder to notice.

NIX_LOCATIONS = {
    "/run/current-system/sw/bin": "NixOS",
    ".nix-profile/bin": "a native nix on another distribution",
    "/nix/var/nix/profiles/default/bin": "the nix daemon's default profile",
}


def _fixed_path_lines():
    """Every PATH list written as a literal rather than extended from the ambient one.

    A value that references the ambient PATH (or interpolates one) extends it and
    needs no locations of its own; a value without a `:` is a single file, not a
    list. What is left is a list that has to be complete.
    """
    literal = re.compile(r'([A-Za-z_]*PATH[A-Za-z_]*)\s*=\s*"([^"]*)"')
    for rel in _shipped_files():
        if (REPO / rel).suffix not in {".py", ".nix"}:
            continue
        try:
            text = (REPO / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            for m in literal.finditer(line):
                value = m.group(2)
                if "{" in value or "PATH" in value or ":" not in value:
                    continue
                yield str(rel), i, line


def test_every_fixed_path_can_find_nix():
    missing = []
    for rel, n, line in _fixed_path_lines():
        for fragment, why in NIX_LOCATIONS.items():
            if fragment not in line:
                missing.append(f"{rel}:{n}  has no {fragment} ({why})\n    {line.strip()}")
    assert not missing, "a fixed PATH that cannot find nix everywhere:\n" + "\n".join(missing)


def test_the_path_check_sees_the_lines_it_claims_to():
    """A guard on the guard: the detector must match the real assignment."""
    found = list(_fixed_path_lines())
    assert len(found) >= 1, f"only matched {len(found)} PATH assignments: {found}"


# --- the council does not depend on a skill library ---------------------------
# Rubrics come from the council's OWN skills/. A Hermes install may also mount an
# external library (skills.external_dirs) and `setup bots` mirrors it into the
# profiles — but only when one exists, never on the review path: that is what keeps
# the council usable on a machine with Hermes and nothing else.

REVIEW_PATH = (
    "council_loop.py", "probes.py", "score_reviews.py", "doctor.py",
    "sample.py", "merge.py", "swarm.py", "baseline.py", "toolchain.py",
    "hermes_home.py", "entrypoint.py",
)


def test_the_review_path_never_reads_the_skill_library():
    offenders = []
    for name in REVIEW_PATH:
        path = REPO / "scripts" / name
        if not path.is_file():
            continue
        if "external_dirs" in path.read_text(encoding="utf-8"):
            offenders.append(name)
    assert not offenders, (
        "these run during a review and read skills.external_dirs, which would make "
        f"the council need a skill library mounted: {offenders}"
    )


def test_the_library_mount_is_optional_in_the_installer():
    """`setup bots` must still install when no library is configured — that is the
    whole difference between a dependency and a convenience."""
    text = (REPO / "scripts" / "install_bots.py").read_text(encoding="utf-8")
    assert 'if library and library != "[]"' in text, (
        "the installer must skip the library mount when none is configured"
    )


def test_the_rubrics_come_from_this_repo_not_a_library():
    """The rubrics are the framework's own, resolved from the framework's root —
    never from a mounted skill library, which is somebody else's repository."""
    text = (REPO / "scripts" / "install_bots.py").read_text(encoding="utf-8")
    assert "cfg_mod.rubrics_dir(ROOT)" in text, (
        "the installer must resolve the rubrics from this framework's own root"
    )
    config = (REPO / "scripts" / "council_config.py").read_text(encoding="utf-8")
    assert '"skills"' in config and '"rubrics"' in config, (
        "rubrics_dir must look in skills/ and assets/rubrics/, the two layouts"
    )


def test_capabilities_come_from_the_config_not_from_constants():
    """A member's toolsets must be READ. The installer used to hardcode them while
    `bots/*/bot.yaml` declared them again in a file nothing read, so a user could
    edit either and see no effect — configurable in appearance only."""
    text = (REPO / "scripts" / "install_bots.py").read_text(encoding="utf-8")
    assert "member.get(\"toolsets\")" in text, (
        "the installer must read each member's toolsets from the configuration"
    )
    for dead in ("REVIEWER_TOOLSETS", "ORCH_TOOLSETS", "ORCH_TOOLSETS"):
        assert dead not in text, (
            f"{dead} is a hardcoded capability set; capabilities belong in the config"
        )


def test_no_private_provider_or_model_ships():
    """No shipped file may name a model or a provider. `bots/*/bot.yaml` used to
    carry one machine's private provider, in a file that ships publicly."""
    offenders = []
    for path in sorted((REPO / "bots").rglob("*.yaml")) + [REPO / "scripts" / "council_config.py"]:
        text = path.read_text(encoding="utf-8")
        for needle in ("example-provider", "example-provider", "example-model-", "api_key"):
            if needle in text:
                offenders.append(f"{path.relative_to(REPO)}: {needle}")
    assert not offenders, (
        "a shipped file names a provider, a model or a key: " + "; ".join(offenders)
    )


def test_the_installer_never_skips_the_flake_silently():
    """The installed skill must be able to build its own toolchain, and a sync that
    cannot install the flake must SAY so.

    It used to be `if os.path.isfile(src): place(...)` with no else. Run from a nix
    framework tree — which by design carries no flake.nix — that skipped both files
    with no output at all: the deployment's flake.nix went stale, `nix build
    `<skill>#toolchain` resolved the OLD toolchain, and nothing reported it.
    """
    _require_repo()
    text = (REPO / "scripts" / "sync_to_skill.py").read_text(encoding="utf-8")
    assert "FLAKE_FILES" in text, "the flake files must be named once, as a set"
    assert "REVIEW_COUNCIL_FLAKE_DIR" in text, (
        "the sync must accept the flake's location from the launcher, because the "
        "framework tree has no flake.nix of its own"
    )
    assert "if missing:" in text, (
        "a sync that cannot install the flake files must refuse, not skip"
    )


def test_the_launchers_pass_the_flake_location():
    """Both entry points must set REVIEW_COUNCIL_FLAKE_DIR, or `setup skill` from
    the nix app or the container would refuse — and from the image there is no
    checkout to fall back to."""
    # Every Nix source, not flake.nix alone: the launchers live in nix/builders.nix
    # since the flake-parts split, and a test pinned to one filename fails on the next
    # move rather than on a regression. tests/golden is fixture data, not source.
    nix = "\n".join(
        p.read_text(encoding="utf-8")
        for p in sorted(REPO.rglob("*.nix"))
        if ".review-council" not in p.parts
        and ".git" not in p.parts
        and "golden" not in p.parts
    )
    # Counts ASSIGNMENTS (`NAME=`), not mentions: the variable is named in comments
    # explaining the staged tree, so a substring count fails on prose, not a launcher
    # that stopped setting it.
    assert nix.count("REVIEW_COUNCIL_FLAKE_DIR=") == 2, (
        "expected REVIEW_COUNCIL_FLAKE_DIR to be SET in both mkDispatcher and "
        "mkContainerEntrypoint"
    )
    assert "flakeFiles" in nix, (
        "the flake must stage the two files as their own store path"
    )


def main() -> int:
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok    {name}")
            except AssertionError as exc:
                failures += 1
                print(f"  FAIL  {name}\n        {exc}")
    print(f"\n  {failures} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
