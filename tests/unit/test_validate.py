#!/usr/bin/env python3
"""The gate's own controls: every rule in `scripts/validate.py` must be seen failing.

A check that has only ever passed is indistinguishable from one that never ran. Each
test below builds the smallest tree that breaks one rule and asserts the gate names it.

    python3 tests/unit/test_validate.py
    python3 -m pytest tests/unit/test_validate.py -q
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
SPEC = importlib.util.spec_from_file_location("validate", REPO / "scripts" / "validate.py")
validate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validate)

CONTRACT = {
    "schema": "skill-contract/v2",
    "description_window": 57,
    "required_frontmatter": ["name", "description", "version", "author", "license", "platforms"],
    "categories": ["alpha", "beta"],
    "support_dirs": ["references", "templates", "assets", "scripts"],
    "hosts": ["hermes"],
    "external_skills": ["github"],
    "scope_fields": ["writes"],
    "allowed_writes": {"project": ["none", "$PROJECT", "$ARTIFACTS", "$SCRATCH"], "declared": ["$HERMES_HOME", "$SYSTEM"]},
    "side_effects": ["none", "systemd", "port", "cron", "background-process"],
    "fhs_fail_prefixes": ["/home"],
    "fhs_note_prefixes": ["/usr"],
    "domain_contract": "CATEGORY.md",
}

SKILL = """---
name: {name}
description: "{desc}"
version: 1.0.0
author: test
license: MIT
platforms: [linux]
side_effects: [none]
{extra}---

# {name}

Body.
"""


def frontmatter(name="probe", desc="Use when probing.", extra=""):
    return SKILL.format(name=name, desc=desc, extra=extra)


def fixture(tmp: Path, files: dict[str, str]) -> Path:
    """A repo shaped like this one: contract, categories, skills, README."""
    (tmp / "library").mkdir(parents=True, exist_ok=True)
    (tmp / "library" / "contract.json").write_text(json.dumps(CONTRACT), encoding="utf-8")
    for rel, text in files.items():
        path = tmp / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    return tmp


def check(tmp: Path) -> list[str]:
    return validate.validate(tmp).violations


def test_a_glob_is_not_a_pointer(tmp=None):
    """`scripts/*.sh` names a class of files; it cannot be dereferenced, so it is not cited.

    Documentation has to be able to say "the shell scripts here are executable" without
    the gate demanding a file called `*.sh`.
    """
    with tempfile.TemporaryDirectory() as d:
        body = frontmatter() + "\n`bin/`, `scripts/*.sh` and `tools/*.sh` are legitimately executable.\n"
        root = fixture(Path(d), {"skills/alpha/probe/SKILL.md": body})
        assert not any("dead reference" in v for v in check(root)), check(root)


def test_a_missing_pointer_is_still_caught(tmp=None):
    """The control for the control: a concrete path that does not exist must still fail.

    Without this, `test_a_glob_is_not_a_pointer` would pass just as well if the whole
    pointer rule had stopped firing.
    """
    with tempfile.TemporaryDirectory() as d:
        body = frontmatter() + "\nRead `scripts/nope.py` before starting.\n"
        root = fixture(Path(d), {"skills/alpha/probe/SKILL.md": body})
        assert any("dead reference -> scripts/nope.py" in v for v in check(root)), check(root)


def one(tmp: Path, text: str, name="probe") -> list[str]:
    (tmp / "library").mkdir(parents=True, exist_ok=True)
    (tmp / "library" / "contract.json").write_text(json.dumps(CONTRACT), encoding="utf-8")
    path = tmp / f"skills/alpha/{name}/SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    # `newline=""`: the fixture must be able to hold CRLF, which is what it tests.
    path.write_text(text, encoding="utf-8", newline="")
    return validate.validate(tmp, one=path).violations


# ── per-file rules ──────────────────────────────────────────────────────────

def test_a_valid_skill_passes():
    with tempfile.TemporaryDirectory() as d:
        assert one(Path(d), frontmatter()) == []


def test_a_missing_fence_is_named():
    with tempfile.TemporaryDirectory() as d:
        out = one(Path(d), frontmatter().replace("---\n", "", 1))
        assert any("does not start with a '---'" in v for v in out), out


def test_an_unclosed_fence_is_named():
    with tempfile.TemporaryDirectory() as d:
        out = one(Path(d), frontmatter().replace("\n---\n\n#", "\n\n#", 1))
        assert any("never closed" in v for v in out), out


def test_a_missing_field_is_named():
    with tempfile.TemporaryDirectory() as d:
        out = one(Path(d), frontmatter().replace("license: MIT\n", ""))
        assert any("missing `license`" in v for v in out), out


def test_a_name_that_disagrees_with_its_directory_is_named():
    with tempfile.TemporaryDirectory() as d:
        out = one(Path(d), frontmatter(name="other"))
        assert any("does not match its directory" in v for v in out), out


def test_the_window_boundary_is_inclusive():
    """57 passes, 58 fails: the boundary itself, not just 'over it'."""
    with tempfile.TemporaryDirectory() as d:
        ok = "U" * 57
        assert one(Path(d), frontmatter(desc=ok)) == []
        out = one(Path(d), frontmatter(desc="U" * 58))
        assert any("58 characters" in v for v in out), out


def test_an_empty_description_is_named():
    with tempfile.TemporaryDirectory() as d:
        out = one(Path(d), frontmatter(desc=""))
        assert any("description` is empty" in v for v in out), out


def test_a_frontmatter_line_the_parser_cannot_read_is_named():
    with tempfile.TemporaryDirectory() as d:
        out = one(Path(d), frontmatter().replace("license: MIT", "license MIT"))
        assert any("not parsed as `key: value`" in v for v in out), out


def test_crlf_is_named():
    with tempfile.TemporaryDirectory() as d:
        out = one(Path(d), frontmatter().replace("\n", "\r\n"))
        assert any("CRLF" in v for v in out), out


def test_a_host_prefixed_skill_must_declare_its_target():
    with tempfile.TemporaryDirectory() as d:
        out = one(Path(d), frontmatter(name="hermes-thing"), name="hermes-thing")
        assert any("host-scoped but declares no" in v for v in out), out
        out = one(Path(d), frontmatter(name="hermes-thing", extra="targets: [hermes]\n"),
                  name="hermes-thing")
        assert out == [], out


def test_an_unknown_target_is_named():
    with tempfile.TemporaryDirectory() as d:
        out = one(Path(d), frontmatter(name="other-thing", extra="targets: [acme]\n"),
                  name="other-thing")
        assert any("not in the contract's hosts" in v for v in out), out


# ── tree rules ──────────────────────────────────────────────────────────────

def test_a_duplicate_name_is_named():
    with tempfile.TemporaryDirectory() as d:
        root = fixture(Path(d), {
            "skills/alpha/probe/SKILL.md": frontmatter(),
            "skills/beta/probe/SKILL.md": frontmatter(),
        })
        assert any("duplicate skill name" in v for v in check(root))


def test_a_directory_without_a_skill_md_is_named():
    with tempfile.TemporaryDirectory() as d:
        root = fixture(Path(d), {"skills/alpha/probe/SKILL.md": frontmatter()})
        (root / "skills/alpha/empty").mkdir()
        assert any("holds no SKILL.md" in v for v in check(root))


def test_a_fenced_command_may_name_a_repo_script():
    """A skill documenting this repository cites a path from the repo root.

    `python3 scripts/validate.py` is a true instruction inside a skill that documents
    this library; resolving it only against the skill directory would forbid a skill
    from describing the tool it belongs to.
    """
    with tempfile.TemporaryDirectory() as d:
        body = frontmatter() + "\n```bash\npython3 scripts/validate.py\n```\n"
        root = fixture(Path(d), {"skills/alpha/probe/SKILL.md": body,
                                 "skills/alpha/probe/scripts/helper.py": "# own helper\n",
                                 "scripts/validate.py": "# the gate\n"})
        assert not any("dead path in a fenced command" in v for v in check(root)), check(root)


def test_a_fenced_command_naming_nothing_still_fails():
    """The control for the control: a path that exists nowhere must still be named."""
    with tempfile.TemporaryDirectory() as d:
        body = frontmatter() + "\n```bash\npython3 scripts/gone.py\n```\n"
        root = fixture(Path(d), {"skills/alpha/probe/SKILL.md": body,
                                 "skills/alpha/probe/scripts/helper.py": "# own helper\n",
                                 "scripts/validate.py": "# the gate\n"})
        assert any("dead path in a fenced command" in v for v in check(root)), check(root)


def test_a_category_outside_the_contract_is_named():
    with tempfile.TemporaryDirectory() as d:
        root = fixture(Path(d), {"skills/gamma/probe/SKILL.md": frontmatter()})
        assert any("not in library/contract.json" in v for v in check(root))


def test_a_dead_reference_is_named():
    with tempfile.TemporaryDirectory() as d:
        body = frontmatter() + "\nSee `references/missing.md` for depth.\n"
        root = fixture(Path(d), {"skills/alpha/probe/SKILL.md": body})
        assert any("dead reference -> references/missing.md" in v for v in check(root))


def test_a_prescriptive_path_is_not_a_dead_reference():
    with tempfile.TemporaryDirectory() as d:
        body = frontmatter() + "\nWrite the file (`references/new.md`) first.\n"
        root = fixture(Path(d), {"skills/alpha/probe/SKILL.md": body})
        assert not any("dead reference" in v for v in check(root))


def test_a_pointer_out_of_the_skill_directory_is_named():
    with tempfile.TemporaryDirectory() as d:
        body = frontmatter() + "\nThe detail is in `../other/references/x.md`.\n"
        root = fixture(Path(d), {"skills/alpha/probe/SKILL.md": body})
        assert any("escapes the skill dir" in v for v in check(root))


def test_a_related_skill_outside_the_repo_must_be_in_the_contract():
    with tempfile.TemporaryDirectory() as d:
        body = frontmatter().replace("metadata:", "metadata:")
        body = body.replace("---\n\n#", "related_skills: [nowhere]\n---\n\n#", 1)
        root = fixture(Path(d), {"skills/alpha/probe/SKILL.md": body})
        assert any("`nowhere`, which is neither here" in v for v in check(root))
        body = body.replace("related_skills: [nowhere]", "related_skills: [github]")
        root = fixture(Path(d), {"skills/alpha/probe/SKILL.md": body})
        assert not any("neither here" in v for v in check(root))


def main() -> int:
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ok    {name}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL  {name}\n        {exc}")
    print(f"\n  {len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

# ── the scope contract ───────────────────────────────────────────────────────

DOMAIN = "**Question.** Does the probe work?\n\n**Not here.** nothing\n"


def scope_repo(d: str, front: str, body: str = "Body.\n") -> Path:
    """A one-skill repo whose contract carries the scope keys."""
    extra = front if not front or front.endswith("\n") else front + "\n"
    text = frontmatter(extra=extra).replace("Body.", body)
    return fixture(Path(d), {
        "skills/alpha/probe/SKILL.md": text,
        "skills/alpha/CATEGORY.md": DOMAIN,
    })


def test_scope_contract_requires_writes():
    """A skill that does not say what it writes cannot be reviewed for purity."""
    with tempfile.TemporaryDirectory() as d:
        out = check(scope_repo(d, front=""))
        assert any("missing `writes`" in v for v in out), out


def test_scope_contract_rejects_an_absolute_write_root():
    """A user's own path in `writes` is the thing the contract exists to stop."""
    with tempfile.TemporaryDirectory() as d:
        out = check(scope_repo(d, front="writes: [/home/someone/projects]"))
        assert any("not one of" in v for v in out), out


def test_scope_contract_rejects_a_user_path_in_a_fenced_command():
    """The control for the control: `/usr` is only reported, `/home` fails."""
    with tempfile.TemporaryDirectory() as d:
        out = check(scope_repo(d, front="writes: [none]",
                               body="```bash\ncp x /home/someone/y\n```\n"))
        assert any("hardcodes /home" in v for v in out), out


def test_scope_contract_allows_a_reported_system_path():
    """A systemd unit's PATH is the system being described, not the reader's space."""
    with tempfile.TemporaryDirectory() as d:
        out = check(scope_repo(d, front="writes: [none]",
                               body="```\nEnvironment=PATH=/usr/bin:/bin\n```\n"))
        assert not any("hardcodes" in v or "writes to" in v for v in out), out


def test_a_declared_root_without_a_heads_up_is_caught():
    """Writing outside the project is allowed, but only if the reader is told."""
    with tempfile.TemporaryDirectory() as d:
        out = check(scope_repo(d, front="writes: [$HERMES_HOME]",
                               body=': "${SKILL_PROJECT:=.}"\n\nBody.\n'))
        assert any("never tells the reader" in v for v in out), out


def test_a_declared_root_with_a_heads_up_passes():
    """The control for the control: the same skill, announced, is clean."""
    with tempfile.TemporaryDirectory() as d:
        out = check(scope_repo(d, front="writes: [$HERMES_HOME]\nleaves: one config file",
                               body=': "${SKILL_PROJECT:=.}"\n\n'
                                    '**Heads-up.** This writes one file under your Hermes home.\n'))
        assert not any("never tells the reader" in v for v in out), out


def test_an_unknown_side_effect_is_named():
    """A free-form token would let a skill hide a systemd unit behind a typo."""
    with tempfile.TemporaryDirectory() as d:
        out = check(scope_repo(d, front="writes: [none]\nside_effects: [daemon-thing]"))
        assert any("not in [" in v for v in out), out
