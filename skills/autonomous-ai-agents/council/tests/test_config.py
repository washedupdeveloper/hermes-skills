#!/usr/bin/env python3
"""The configuration: defaults, round-trip, validation, and what must NOT ship.

Every test here is a property a stranger's first run depends on. The failure
they guard against is not "a wrong value" — it is a config that LOOKS editable
and is not, or one that this framework cannot read back after writing.
"""
from __future__ import annotations

import sys
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS))

import council_config as cfg_mod  # noqa: E402


def test_the_shipped_defaults_are_usable_with_no_config_at_all():
    """A fresh machine has no config. It must still work, and it must be valid."""
    cfg, path = cfg_mod.load(hermes_home="/nonexistent-hermes-home-xyz")
    assert path is None, "a missing config must report itself as absent"
    assert cfg_mod.validate(cfg) == [], "the shipped defaults must validate"


def test_the_defaults_carry_no_machine_specifics():
    """A default that only works on the author's machine is not a default."""
    text = (SCRIPTS / "council_config.py").read_text(encoding="utf-8")
    # Only the DEFAULTS block matters, but scanning the whole module is stricter
    # and the module has no legitimate reason to name any of these.
    #
    # These are SHAPES of machine-specific data, not anyone's actual username: a
    # username needle here would be both obsolete after sanitising and far too
    # generic to assert on ("user" appears in ordinary prose in this module).
    for needle in ("openai", "anthropic", "api_key", "sk-", "/home/", "C:\\"):
        assert needle not in text.lower(), (
            f"council_config.py names {needle!r}; defaults must carry no machine specifics"
        )


def test_the_default_members_have_no_model_or_provider():
    """Empty means inherit. Shipping a model would silently override the user's."""
    cfg, _ = cfg_mod.load(hermes_home="/nonexistent-hermes-home-xyz")
    for name, member in cfg["members"].items():
        assert not member.get("model"), f"{name} ships a model: {member.get('model')!r}"
        assert not member.get("provider"), f"{name} ships a provider: {member.get('provider')!r}"


def test_render_round_trips_through_tomllib():
    """The writer must emit what the reader can parse.

    This is the worst failure mode available to a first-run path: writing a
    config that every later verb then fails to read. Round-tripping in the test
    is what makes the guarantee checkable rather than assumed.
    """
    cfg, _ = cfg_mod.load(hermes_home="/nonexistent-hermes-home-xyz")
    text = cfg_mod.render(cfg)
    parsed = tomllib.loads(text)  # raises if the renderer is wrong
    assert parsed["schema_version"] == cfg["schema_version"]
    assert parsed["review"]["threshold"] == cfg["review"]["threshold"]
    assert set(parsed["members"]) == set(cfg["members"])
    for name, member in parsed["members"].items():
        assert member["role"] == cfg["members"][name]["role"]
        assert member["toolsets"] == cfg["members"][name]["toolsets"]


def test_render_escapes_a_hostile_description():
    """A description is free text a user or a future default may put a quote or a
    backslash in. Unescaped, that produces a file the reader rejects."""
    cfg, _ = cfg_mod.load(hermes_home="/nonexistent-hermes-home-xyz")
    cfg["members"]["council-generalist"]["description"] = 'has "quotes" and \\ a backslash'
    parsed = tomllib.loads(cfg_mod.render(cfg))
    assert parsed["members"]["council-generalist"]["description"] == \
        'has "quotes" and \\ a backslash'


def test_write_refuses_to_clobber_without_force(tmp_path: Path):
    cfg, _ = cfg_mod.load(hermes_home="/nonexistent-hermes-home-xyz")
    target = tmp_path / cfg_mod.CONFIG_NAME
    cfg_mod.write(cfg, target)
    try:
        cfg_mod.write(cfg, target)
    except SystemExit:
        pass
    else:
        raise AssertionError("write() overwrote an existing config without force")


def test_a_user_edit_is_read_back(tmp_path: Path):
    """The point of the file: what the user writes is what takes effect."""
    target = tmp_path / cfg_mod.CONFIG_NAME
    target.write_text(
        "schema_version = 1\n"
        "[review]\n"
        "threshold = 42.5\n"
        "samples = 2\n"
        'mode = "full"\n'
        "max_rounds = 9\n"
        "[members.council-generalist]\n"
        'role = "reviewer"\n'
        'toolsets = ["file", "terminal"]\n'
        "[members.council-orchestrator]\n"
        'role = "orchestrator"\n'
        'toolsets = ["file"]\n',
        encoding="utf-8",
    )
    cfg, path = cfg_mod.load(hermes_home=str(tmp_path))
    assert path == target
    assert cfg["review"]["threshold"] == 42.5
    assert cfg["review"]["samples"] == 2
    assert cfg["review"]["mode"] == "full"
    assert cfg["members"]["council-generalist"]["toolsets"] == ["file", "terminal"]
    # A key the user did NOT set falls back to the default rather than vanishing.
    assert cfg["members"]["council-generalist"]["title"] == "Council Reviewer"


def test_validation_reports_every_problem_at_once():
    """A user fixing their file should see the whole list, not play whack-a-mole."""
    cfg, _ = cfg_mod.load(hermes_home="/nonexistent-hermes-home-xyz")
    cfg["review"]["threshold"] = "high"
    cfg["review"]["samples"] = 0
    cfg["review"]["mode"] = "yolo"
    problems = cfg_mod.validate(cfg)
    assert len(problems) >= 3, f"expected several problems, got {problems}"
    joined = " ".join(problems)
    for field in ("threshold", "samples", "mode"):
        assert field in joined, f"{field} was not reported: {problems}"


def test_delegation_is_refused_because_the_harness_is_the_only_fanout():
    """A member that could delegate would spawn its own agents and apply none of
    the rubrics — the exact failure the profile design exists to prevent."""
    cfg, _ = cfg_mod.load(hermes_home="/nonexistent-hermes-home-xyz")
    cfg["members"]["council-generalist"]["toolsets"].append("delegation")
    problems = cfg_mod.validate(cfg)
    assert any("delegation" in p for p in problems), (
        f"a delegation toolset was accepted: {problems}")


def test_a_missing_role_is_reported_not_discovered_at_review_time():
    cfg, _ = cfg_mod.load(hermes_home="/nonexistent-hermes-home-xyz")
    del cfg["members"]["council-orchestrator"]
    problems = cfg_mod.validate(cfg)
    assert any("orchestrator" in p for p in problems), (
        f"a council with no orchestrator was accepted: {problems}")


def test_the_config_lives_under_hermes_home_not_in_the_skill():
    """It must survive a skill update, and it must be per-user."""
    path = cfg_mod.config_path(hermes_home="/tmp/some-home")
    assert path == Path("/tmp/some-home") / cfg_mod.CONFIG_NAME
    assert "skills" not in path.parts, (
        "the config must not live inside the skill, which is replaced on update")


def test_an_invalid_config_names_the_file_and_the_problem(tmp_path: Path):
    """A parse error must point at the line, not raise a traceback at a user."""
    target = tmp_path / cfg_mod.CONFIG_NAME
    target.write_text("[review\nthreshold = ", encoding="utf-8")
    try:
        cfg_mod.load(hermes_home=str(tmp_path))
    except SystemExit as exc:
        message = str(exc)
        assert cfg_mod.CONFIG_NAME in message, message
        assert "TOML" in message, message
    else:
        raise AssertionError("a malformed config was accepted")


def test_core_skills_are_static_and_exclude_the_council_skill():
    """A member's CORE skills are named explicitly, never globbed.

    The glob was the problem: it made the set a side effect of adding a file, so
    a new rubric silently reached every bot. The explicit list is a decision, and
    `council` — this skill's own documentation, which lives in skills/ — must
    never be in it, or every bot profile would carry the council's own docs as a
    skill it thinks it must read.
    """
    assert cfg_mod.CORE_SKILLS, "there must be a static core list"
    for role in cfg_mod.REQUIRED_ROLES:
        assert role in cfg_mod.CORE_SKILLS, f"role {role!r} has no core skills"
        assert cfg_mod.CORE_SKILLS[role], f"role {role!r} has an empty core list"
    every = {s for names in cfg_mod.CORE_SKILLS.values() for s in names}
    assert "council" not in every, "the council's own skill is not a bot rubric"


def test_every_dimension_has_its_rubric_in_the_core_list():
    """A dimension and its rubric are one decision, so the two lists must agree.

    This is the silent failure docs/EXTENDING.md warns about: the loop fans out to
    a dimension whose rubric is not in `CORE_SKILLS`, so the reviewer is installed
    WITHOUT it, answers with no criteria, and reports nothing. Nothing else in the
    pipeline notices — the round completes, the merge buckets an empty dimension,
    and the run looks quiet rather than misconfigured.

    The doc used to say the installer globbed `reviewer-*/SKILL.md` and needed no
    edit. It does not: `CORE_SKILLS` is an explicit list on purpose. Following the
    doc as written produced exactly the silent failure above, which is how this
    test came to exist.
    """
    import council_loop as loop_mod  # noqa: PLC0415 - after sys.path is set

    core = set(cfg_mod.CORE_SKILLS["reviewer"])
    missing = sorted(
        spec["rubric"] for spec in loop_mod.DIMENSION_SPEC.values()
        if spec["rubric"] not in core
    )
    assert not missing, (
        f"dimensions whose rubric is not a reviewer core skill: {missing}. "
        "Add them to CORE_SKILLS['reviewer'] in scripts/council_config.py, or the "
        "reviewer is installed without that rubric and reports nothing for it."
    )

    # The reverse direction is a different bug: a core rubric no dimension names is
    # installed into every profile and can never produce a finding the gate reads.
    rubrics = {spec["rubric"] for spec in loop_mod.DIMENSION_SPEC.values()}
    orphaned = sorted(core - rubrics)
    assert not orphaned, f"core skills that no dimension names: {orphaned}"


def test_every_member_declares_core_and_optional_skills():
    """Both halves must be present and render, so the file a user edits shows them."""
    text = cfg_mod.render(cfg_mod.DEFAULTS)
    parsed = tomllib.loads(text)
    for name, member in cfg_mod.DEFAULTS["members"].items():
        assert member.get("core_skills"), f"{name} declares no core_skills"
        assert member.get("skills") is not None, f"{name} declares no skills key"
        assert "core_skills" in parsed["members"][name], (
            f"{name}: core_skills did not survive the round trip")
        assert "skills" in parsed["members"][name], (
            f"{name}: skills did not survive the round trip")


def test_an_empty_core_skill_list_is_rejected():
    """A member with no core skill cannot read its own instructions.

    That failure is silent at install time and shows up as a reviewer that
    reports nothing, so it is refused up front.
    """
    cfg = cfg_mod.render(cfg_mod.DEFAULTS)
    broken = tomllib.loads(cfg)
    broken["members"]["council-generalist"]["core_skills"] = []
    problems = cfg_mod.validate(broken)
    assert any("core_skills" in p for p in problems), problems


def test_a_non_list_skills_value_is_rejected():
    """Both keys are lists of names; a string would silently iterate by character."""
    broken = tomllib.loads(cfg_mod.render(cfg_mod.DEFAULTS))
    broken["members"]["council-generalist"]["skills"] = "web-app-security"
    problems = cfg_mod.validate(broken)
    assert any("skills" in p for p in problems), problems


def test_the_reviewer_declares_the_web_security_skill_on_demand():
    """The security rubric routes to `web-app-security` for web diffs.

    If that routing is not declared, the reviewer is told to load a skill nothing
    guarantees is reachable. Optional means "not installed, loaded by name" — so
    the name has to be in the config for the installer to resolve it.
    """
    reviewer = cfg_mod.DEFAULTS["members"]["council-generalist"]
    assert "web-app-security" in (reviewer.get("skills") or []), (
        "the reviewer's security rubric routes to web-app-security; declare it")
    core = reviewer.get("core_skills") or []
    assert "web-app-security" not in core, (
        "web-app-security is optional and must not be installed into the profile")


def main() -> int:
    import inspect
    import tempfile

    failures = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            if "tmp_path" in inspect.signature(fn).parameters:
                with tempfile.TemporaryDirectory() as tmp:
                    fn(Path(tmp))
            else:
                fn()
            print(f"  ok    {name}")
        except AssertionError as exc:
            failures += 1
            print(f"  FAIL  {name}\n        {exc}")
    print(f"\n  {failures} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
