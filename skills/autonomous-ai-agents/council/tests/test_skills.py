"""Contract tests for the skill files this repo ships (skills/*/SKILL.md).

These guard the properties that make the skills loadable and non-overlapping:
frontmatter shape, the 60-char description ceiling, resolvable cross-references,
and that no skill re-states a rule another skill owns.

Run standalone (no pytest needed):
    python tests/test_skills.py
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILLS = REPO / "skills"

REQUIRED_FIELDS = ("name", "description", "version", "author", "license", "platforms")


def _require_repo() -> None:
    """Skip when running from the DEPLOYED skill rather than the repo.

    The sync module is deliberately NOT shipped — it IS the copier — so its
    absence means we are inside the deployment, where the repo<->deployment
    wiring these tests assert cannot hold by construction. Reporting them as
    failures would ship a suite that always shows red, and a reader who learns to
    ignore red learns to ignore the real failure.
    """
    if (REPO / "scripts" / "sync_to_skill.py").exists():
        return
    try:
        import pytest
        pytest.skip("deployed copy: this test asserts the repo-side wiring")
    except ImportError:  # pragma: no cover — the toolchain always has pytest
        raise RuntimeError("skipped: deployed copy") from None

# Rules that have exactly ONE owner. If a rule's distinctive vocabulary shows up in
# another skill, the two have drifted into overlap and one copy will go stale.
OWNED_RULES = {
    # skill -> tokens that must appear ONLY there
    "nixos-clan-flake": ("outputHashMode", "cygpath", "bash_logout", "wsl.exe"),
    "deterministic-quality-gates": ("Absence is not cleanliness",),
}


def _parse(path: Path) -> tuple[dict, str]:
    """Minimal frontmatter split — stdlib only, no yaml dependency."""
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---"), f"{path} must start with --- at byte 0"
    m = re.search(r"\n---\s*\n", text[3:])
    assert m, f"{path} has no closing ---"
    fm: dict = {}
    for line in text[3:m.start() + 3].splitlines():
        mm = re.match(r"^([a-z_]+):\s*(.*)$", line)
        if mm:
            fm[mm.group(1)] = mm.group(2).strip().strip('"')
    return fm, text[m.end() + 3:]


def _skill_files() -> list[Path]:
    return sorted(SKILLS.glob("*/SKILL.md"))


def test_every_skill_has_the_required_frontmatter():
    missing = []
    for p in _skill_files():
        fm, _ = _parse(p)
        for field in REQUIRED_FIELDS:
            if field not in fm:
                missing.append(f"{p.parent.name}:{field}")
    assert not missing, f"missing frontmatter fields: {missing}"


def test_description_fits_the_index_window():
    """The skill index truncates at 57 chars + '...', so the trigger must be
    self-contained there. The repo hardline is 60, well under the validator's 1024."""
    bad = []
    for p in _skill_files():
        fm, _ = _parse(p)
        d = fm.get("description", "")
        if len(d) > 60:
            bad.append(f"{p.parent.name}: {len(d)} chars")
        if not d.endswith("."):
            bad.append(f"{p.parent.name}: no trailing period")
    assert not bad, f"description violates the 60-char hardline: {bad}"


def test_name_matches_the_directory():
    """The skill registers as /<name> from the frontmatter, and the installer
    copies it by directory name — a mismatch silently installs the wrong skill."""
    bad = []
    for p in _skill_files():
        fm, _ = _parse(p)
        if fm.get("name") != p.parent.name:
            bad.append(f"{p.parent.name} != {fm.get('name')}")
    assert not bad, f"name/directory mismatch: {bad}"


def test_related_skills_resolve():
    """A related_skills entry pointing at a skill that does not exist is a dead
    reference the reader cannot follow."""
    names = {p.parent.name for p in _skill_files()}
    bad = []
    for p in _skill_files():
        _, body = _parse(p)
        m = re.search(r"related_skills:\s*\[([^\]]*)\]", body)
        if not m:
            continue
        for ref in (x.strip() for x in m.group(1).split(",")):
            # Only entries that are OUR skills must resolve; bundled Hermes skills
            # (requesting-code-review, hermes-agent, …) live outside this repo.
            if ref in names or not ref:
                continue
            if ref.startswith("reviewer-") or ref.startswith("review-council"):
                bad.append(f"{p.parent.name} -> {ref}")
    assert not bad, f"unresolved in-repo related_skills: {bad}"


def test_owned_rules_are_not_restated_elsewhere():
    """Each cross-cutting rule has one owner. A second copy drifts out of date —
    the failure this repo already hit with the fetchurl hash-mode rules."""
    problems = []
    for owner, tokens in OWNED_RULES.items():
        for p in _skill_files():
            if p.parent.name == owner:
                continue
            body = p.read_text(encoding="utf-8")
            for token in tokens:
                if token in body:
                    problems.append(f"{p.parent.name} restates {owner}'s '{token}'")
    assert not problems, problems


def test_the_council_skill_has_a_repo_source():
    """The council skill's own SKILL.md used to live only at the install location,
    so losing that directory lost the documentation. It is version-controlled here
    and copied in by the sync module."""
    _require_repo()
    src = SKILLS / "council" / "SKILL.md"
    assert src.exists(), "skills/council/SKILL.md must exist (the sync source)"
    fm, _ = _parse(src)
    assert fm["name"] == "council"
    assert "skills/council/SKILL.md" in (
        REPO / "scripts" / "sync_to_skill.py").read_text(encoding="utf-8"), (
        "the sync module must copy skills/council/SKILL.md into the skill"
    )


def test_rubrics_are_installed_by_a_prefix_glob():
    """The installer picks up rubrics with `reviewer-*`. A bare `*` would sweep
    skills/council/ into every bot profile, including the skill's own docs.

    The glob lives in council_config.reviewer_rubrics, which the installer calls,
    so this checks where it actually is rather than where it used to be."""
    config = (REPO / "scripts" / "council_config.py").read_text(encoding="utf-8")
    assert 'RUBRIC_GLOB = "reviewer-*"' in config, "the rubrics glob changed"
    assert ".glob(RUBRIC_GLOB)" in config, (
        "reviewer_rubrics must glob by the prefix constant"
    )
    source = (REPO / "scripts" / "install_bots.py").read_text(encoding="utf-8")
    assert "cfg_mod.reviewer_rubrics(ROOT)" in source, (
        "the installer must take the rubric list from the config module"
    )
    assert '.glob("*")' not in source, "a bare glob would leak skills/council/ in"
    assert 'glob("reviewer-*")' not in source, (
        "the glob belongs in council_config, not duplicated in the installer"
    )


def test_the_council_ships_the_caveman_voice_in_every_soul():
    """The communication contract is the member's IDENTITY, not a skill.

    `SOUL.md` is slot #1 of the system prompt — injected every turn. A skill is
    chosen per task and may not be chosen, so a voice that lives only in a skill is
    a suggestion. Each member ships its own SOUL.md in this repo (so the voice is
    version-controlled and portable), and `setup bots` copies it into the profile.

    The member's HERMES_HOME is the profile directory, so `SOUL.md` is loaded from
    there — a global ~/.hermes/SOUL.md does NOT reach a council profile.
    """
    _require_repo()
    members = sorted(p.name for p in (REPO / "bots").iterdir() if p.is_dir())
    assert members, "no bot definitions under bots/"
    for name in members:
        soul = REPO / "bots" / name / "SOUL.md"
        assert soul.is_file(), f"{name} ships no SOUL.md, so it has no voice"
        body = soul.read_text(encoding="utf-8")
        assert "Speak caveman" in body, f"{name}: SOUL.md does not carry the voice"
        assert "Never perform caveman" in body, (
            f"{name}: SOUL.md must forbid performing the voice")


def test_the_reviewer_is_installed_with_a_soul_source():
    """The reviewer's profile used to keep whatever SOUL.md it was cloned with.

    A member with no SOUL source has an identity nobody chose, and the installer's
    copy is conditional — so this is the assertion that the file exists to copy.
    """
    _require_repo()
    assert (REPO / "bots" / "council-generalist" / "SOUL.md").is_file(), (
        "the reviewer needs a SOUL.md source, or its voice is unmanaged")


def test_the_voice_skills_are_declared_on_demand_not_core():
    """`caveman` is the long form of a voice the SOUL.md already carries.

    Installing it as a CORE skill would put ~4.5 KB into every sample to restate
    what the identity slot says in ~400 tokens. It is declared optional so the
    member can load it by name when the short form is not enough.
    """
    config = (REPO / "scripts" / "council_config.py").read_text(encoding="utf-8")
    for skill in ("caveman", "caveman-review"):
        assert f'"{skill}"' in config, f"{skill} must be declared on demand"
    reviewer_core = _core_skills_for("reviewer")
    assert "caveman" not in reviewer_core, (
        "caveman is the long form; the SOUL.md is the always-on voice")


def _core_skills_for(role: str) -> list:
    """The static core list for a role, read from the config module."""
    sys.path.insert(0, str(REPO / "scripts"))
    import council_config as cfg_mod
    return list(cfg_mod.CORE_SKILLS.get(role) or [])


def test_no_text_file_carries_crlf():
    """The skill is mounted on Linux, macOS, Windows and WSL2, and ships scripts.

    A CRLF shebang fails on Linux and WSL2 with `bad interpreter ...^M`, and a
    CRLF-vs-LF pair makes `council setup skill --check` report false drift on a
    machine whose checkout differs. Generated files are the real risk:
    Path.write_text() translates \\n to os.linesep, so calibration.json and
    eval-baseline.json came out CRLF on Windows until they were pinned with
    newline="\\n". The same inputs must produce the same bytes everywhere.
    """
    crlf_ok = {".bat", ".ps1", ".cmd"}
    # Tool caches are not shipped source, and a stale one fails this test in a dev
    # clone while the gate (which checks a git-filtered tree) stays green.
    skip = {".git", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache"}
    offenders = []
    for p in REPO.rglob("*"):
        # `is_file()` FOLLOWS symlinks: `nix build .#container` (the README's own
        # command) leaves `result -> /nix/store/<...>.tar.gz`, so this walked into a
        # 348 MiB gzip and failed on bytes never in the repository. Check link first.
        if p.is_symlink() or not p.is_file() or any(part in skip for part in p.parts):
            continue
        if p.suffix.lower() in crlf_ok:
            continue
        if b"\r\n" in p.read_bytes():
            offenders.append(str(p.relative_to(REPO)))
    assert not offenders, f"text files must be LF-only: {offenders}"


def test_generators_pin_lf_line_endings():
    """Guards the fix, not just its symptom: a new write_text() without
    newline="\\n" would reintroduce CRLF on Windows.

    Parsed with ast rather than counted as text: comments in these files discuss
    the pin, and a substring count would score the prose as well as the code.
    """
    for rel in ("scripts/calibrate.py", "scripts/probes.py"):
        tree = ast.parse((REPO / rel).read_text(encoding="utf-8"))
        calls = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute)
                 and n.func.attr == "write_text"]
        assert calls, f"{rel}: expected at least one write_text() call"
        for c in calls:
            kw = {k.arg: k.value for k in c.keywords}
            assert "newline" in kw, (
                f"{rel}:{c.lineno}: write_text must pass newline='\\n' so output "
                "is byte-identical across platforms"
            )
            assert isinstance(kw["newline"], ast.Constant) and kw["newline"].value == "\n", (
                f"{rel}:{c.lineno}: newline must be the literal '\\n'"
            )


def test_sync_targets_the_mounted_library():
    """The sync module must resolve its destination from skills.external_dirs.

    The library is mounted read-only and is the source of truth. Writing to the
    installed copy instead is invisible: local skills outrank external ones, so
    the agent loads the shadowed copy while the repo updates a file nobody reads.
    """
    _require_repo()
    source = (REPO / "scripts" / "sync_to_skill.py").read_text(encoding="utf-8")
    assert "skills.external_dirs" in source, (
        "the sync module must ask Hermes where the mount is"
    )
    assert "resolve_mounted_skills_root" in source
    # The mount must win over the installed dir, not merely be mentioned.
    body = source[source.index("def main"):]
    mounted_idx = body.index("resolve_mounted_skills_root()")
    fallback_idx = body.index("installed skills dir")
    assert mounted_idx < fallback_idx, (
        "the mounted library must be tried BEFORE the installed fallback"
    )


def test_every_relative_doc_link_resolves():
    """A link to a file that does not exist is a broken pointer, and the README is
    the first thing a stranger reads.

    Only RELATIVE targets are checked: an http(s) link needs the network, and a
    bare `#anchor` needs the rendered page. The `#fragment` is stripped before the
    path test, because `README.md#install-it` is a real file plus a fragment --
    testing the raw target reports every anchored link broken, which is a false
    alarm in a gate whose whole job is to be trusted when it is red.

    Repo-side only: the DEPLOYED skill ships SKILL.md and its support dirs, not the
    project's README or docs/, so there is nothing here to check there.
    """
    _require_repo()
    docs = [REPO / "README.md"] + sorted((REPO / "docs").glob("*.md"))
    bad: list[str] = []
    for doc in docs:
        for _label, target in re.findall(r"\[([^\]]*)\]\(([^)]+)\)",
                                        doc.read_text(encoding="utf-8")):
            if target.startswith(("http", "#", "mailto:")):
                continue
            path = target.split("#", 1)[0]
            if not path:
                continue
            if not (doc.parent / path).exists():
                bad.append(f"{doc.relative_to(REPO)} -> {target}")
    assert not bad, "dead relative links:\n" + "\n".join(f"  {b}" for b in bad)


def main() -> int:
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    passed = failed = skipped = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS {name}")
            passed += 1
        except AssertionError as exc:
            print(f"  FAIL {name} -> {exc}")
            failed += 1
        except BaseException as exc:  # noqa: BLE001
            # pytest.skip raises Skipped, which derives from BaseException — a bare
            # `except Exception` lets it escape and the runner dies with a traceback
            # instead of skipping. Matched by name so this file needs no pytest import.
            if type(exc).__name__ == "Skipped":
                print(f"  SKIP {name} -> {exc}")
                skipped += 1
                continue
            if not isinstance(exc, Exception):
                raise  # KeyboardInterrupt and friends must not be swallowed
            print(f"  ERROR {name} -> {type(exc).__name__}: {exc}")
            failed += 1
    tail = f", {skipped} skipped" if skipped else ""
    print(f"\n{passed} passed, {failed} failed{tail}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
