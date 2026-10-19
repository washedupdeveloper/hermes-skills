#!/usr/bin/env python3
"""council_config.py — the ONE place the council's configuration lives.

Everything a person might want to change after installing lives in a single
`review-council.yaml` in their Hermes home, and nothing else hardcodes it:

  * which members exist, and what each one may do (toolsets, skills, model)
  * the gate threshold, the sample count, the default autonomy mode
  * the analyzers the deterministic half expects

Before this, the same facts lived in three places that could disagree: the
toolsets were hardcoded in install_bots.py, `bots/*/bot.yaml` declared them
again in a file nothing read, and the model/provider were baked into that
unread file as one machine's private values. A user could edit any of them and
see no effect.

Design rules, all of them load-bearing:

  * DEFAULTS carry no machine specifics. No hostname, no home directory, no
    provider, no API key, no model name. A default that only works on the
    author's machine is not a default.
  * The config is READ, never generated-then-frozen. `council init` writes it
    once so it is discoverable and editable; every later run reads it.
  * A missing key falls back to the default, so a config written by an older
    version keeps working.
  * Validation reports every problem at once rather than dying on the first, so
    a user fixing their file sees the whole list.
"""
from __future__ import annotations

import copy
import os
import sys
import tomllib
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

try:
    from hermes_home import resolve as resolve_hermes_home  # type: ignore
except ImportError:  # pragma: no cover - only when loaded without its sibling
    def resolve_hermes_home() -> str:
        return os.environ.get("HERMES_HOME") or str(Path.home() / ".hermes")

# Named for the project, not the skill, so a skill update cannot orphan it.
# TOML, not YAML: the toolchain's interpreter has no PyYAML and `tomllib` is
# stdlib from 3.11 (toolchain is 3.14). docs/CI.md has the stdlib-only rule.
CONFIG_NAME = "review-council.toml"

# Bumped when a key changes meaning. An older config is still READ (a missing key
# falls back), but `council init` offers to add what is new.
SCHEMA_VERSION = 1

# ── the reviewer's rubrics ──────────────────────────────────────────────────
# The namespace the installer prunes stale rubrics from. NOT the install list:
# CORE_SKILLS below is explicit, so a file added here installs nothing.
RUBRIC_GLOB = "reviewer-*"

# A reviewer is a leaf: NO delegation (the harness is the only fan-out) and no
# kanban/cronjob (it does not schedule work).
REVIEWER_TOOLSETS = [
    "file", "terminal", "code_execution", "skills", "web", "todo",
    "memory", "session_search", "clarify",
]

# Also reads the board and scheduler, because planning is its job. No delegation.
ORCHESTRATOR_TOOLSETS = REVIEWER_TOOLSETS + ["kanban", "cronjob"]

# Required, explicit — not globbed, so a new rubric file installs nothing and
# validation can name a missing one. `skills` below is the OPTIONAL half: loaded
# on demand from the mounted library, never installed.
CORE_SKILLS: Dict[str, tuple] = {
    "reviewer": (
        "reviewer-architecture",
        "reviewer-correctness",
        "reviewer-performance",
        "reviewer-readability",
        "reviewer-security",
    ),
    "orchestrator": ("review-council-orchestrator",),
}

DEFAULTS: Dict[str, Any] = {
    "schema_version": SCHEMA_VERSION,
    "review": {
        # A REGRESSION DETECTOR, not an absolute bar: of nine well-regarded repos at
        # --samples 5, one is clean, so no known-good class exists. docs/CALIBRATION.md.
        "threshold": 80.0,
        # Reviewer samples per round: more recall, more time.
        "samples": 5,
        # advisory = report only; semi = fix with confirmation; full = fix and
        # re-review until the gate passes or it stops improving.
        "mode": "advisory",
        "max_rounds": 3,
    },
    "members": {
        "council-generalist": {
            "role": "reviewer",
            "title": "Council Reviewer",
            "description": "Generalist reviewer: every rubric in one profile, sampled N times.",
            "toolsets": list(REVIEWER_TOOLSETS),
            # Installed into the profile: always present, always loaded.
            "core_skills": list(CORE_SKILLS["reviewer"]),
            # Optional: loaded by name from the mounted library, never installed.
            # web-app-security only matters when a diff touches a web project, and
            # the voice is already in SOUL.md, so `caveman` here is the long form.
            "skills": ["web-app-security", "caveman", "caveman-review"],
            "model": None,         # None = inherit the profile's model
            "provider": None,      # None = inherit; never ship a private one
        },
        "council-orchestrator": {
            "role": "orchestrator",
            "title": "Council Orchestrator",
            "description": "Sets one goal per dimension, then judges the round against them.",
            "toolsets": list(ORCHESTRATOR_TOOLSETS),
            "core_skills": list(CORE_SKILLS["orchestrator"]),
            # The voice is in this member's SOUL.md; `caveman` is its long form.
            "skills": ["caveman"],
            "model": None,
            "provider": None,
        },
    },
}

# A user may add members; removing one of these breaks the harness, so validation
# says so rather than failing later.
REQUIRED_ROLES = ("reviewer", "orchestrator")


def config_path(hermes_home: Optional[str] = None) -> Path:
    """Where the user's config lives. Under HERMES_HOME, never in the skill."""
    root = Path(hermes_home or resolve_hermes_home())
    return root / CONFIG_NAME


def _merge(base: Any, override: Any) -> Any:
    """Deep merge, override wins. Lists REPLACE (a user who trims a toolset
    means it), dicts merge key by key."""
    if isinstance(base, dict) and isinstance(override, dict):
        out = dict(base)
        for key, value in override.items():
            out[key] = _merge(base.get(key), value) if key in base else value
        return out
    return override


def load(hermes_home: Optional[str] = None) -> Tuple[Dict[str, Any], Optional[Path]]:
    """The effective config: DEFAULTS deep-merged with the user's file.

    Returns (config, path-or-None-when-absent). Never raises on a missing file:
    a fresh machine has no config and must still work.
    """
    path = config_path(hermes_home)
    if not path.is_file():
        # deepcopy, not dict(): a shallow copy shares the nested member dicts and
        # their lists with DEFAULTS, so one caller's mutation corrupted the module
        # default and surfaced as an unrelated test failing later.
        return copy.deepcopy(DEFAULTS), None
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        # tomllib's message names the line and column, which is what an editor needs.
        raise SystemExit(f"{CONFIG_NAME}: {path} is not valid TOML: {exc}")
    except OSError as exc:
        raise SystemExit(f"{CONFIG_NAME}: cannot read {path}: {exc}")
    if not isinstance(raw, dict):
        raise SystemExit(f"{CONFIG_NAME}: {path} must contain a table at the top level.")
    return _merge(DEFAULTS, raw), path


def validate(cfg: Dict[str, Any]) -> List[str]:
    """Every problem, not the first. Empty list means usable."""
    problems: List[str] = []

    review = cfg.get("review")
    if not isinstance(review, dict):
        problems.append("review: must be a mapping")
        review = {}
    threshold = review.get("threshold")
    if not isinstance(threshold, (int, float)) or isinstance(threshold, bool):
        problems.append(f"review.threshold: must be a number, got {threshold!r}")
    elif not 0 <= threshold <= 100:
        problems.append(f"review.threshold: must be 0-100, got {threshold}")
    samples = review.get("samples")
    if not isinstance(samples, int) or isinstance(samples, bool) or samples < 1:
        problems.append(f"review.samples: must be an integer >= 1, got {samples!r}")
    if review.get("mode") not in ("advisory", "semi", "full"):
        problems.append(
            f"review.mode: must be advisory, semi or full, got {review.get('mode')!r}")

    members = cfg.get("members")
    if not isinstance(members, dict) or not members:
        problems.append("members: must be a non-empty mapping of profile name -> member")
        return problems

    roles = set()
    for name, member in members.items():
        where = f"members.{name}"
        if not isinstance(member, dict):
            problems.append(f"{where}: must be a mapping")
            continue
        role = member.get("role")
        if role not in ("reviewer", "orchestrator"):
            problems.append(f"{where}.role: must be reviewer or orchestrator, got {role!r}")
        else:
            roles.add(role)
        toolsets = member.get("toolsets")
        if not isinstance(toolsets, list) or not all(isinstance(t, str) for t in toolsets):
            problems.append(f"{where}.toolsets: must be a list of strings")
        # A member with delegation would spawn agents that apply no rubric.
        # docs/DECISIONS.md #1.
        if isinstance(toolsets, list) and "delegation" in toolsets:
            problems.append(
                f"{where}.toolsets: must not include 'delegation' -- the harness is "
                f"the only fan-out, so a member that delegates would bypass the rubrics")
        for key in ("model", "provider"):
            value = member.get(key)
            if value is not None and not isinstance(value, str):
                problems.append(f"{where}.{key}: must be a string or null, got {value!r}")
        for key in ("core_skills", "skills"):
            value = member.get(key)
            if value is None:
                continue
            if not isinstance(value, list) or not all(isinstance(s, str) for s in value):
                problems.append(f"{where}.{key}: must be a list of strings")
        core = member.get("core_skills")
        if isinstance(core, list) and not core:
            problems.append(
                f"{where}.core_skills: must not be empty -- a member with no core "
                f"skill cannot read its own instructions")

    for role in REQUIRED_ROLES:
        if role not in roles:
            problems.append(
                f"members: no member has role {role!r}; a review cannot run without one")

    return problems


def _toml_string(value: str) -> str:
    """A TOML basic string. Escapes what TOML requires, so a description with a
    quote or a backslash round-trips instead of producing an unparseable file."""
    out = value.replace("\\", "\\\\").replace('"', '\\"')
    out = out.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    return f'"{out}"'


def render(cfg: Dict[str, Any]) -> str:
    """The config as TOML text, for `council setup` to write.

    Hand-rendered rather than dumped, because the comments are the point: this is
    the file a person opens to change something, and every field says what it
    does. `write()` round-trips the result through `tomllib` before it lands — a
    config writer that emits what its own reader cannot parse is the worst
    possible failure for a first-run path.
    """
    review = cfg.get("review", {})
    lines = [
        "# review-council configuration",
        "#",
        "# Edit this file, then run `council setup bots` to apply it.",
        "# Nothing here is machine-specific: an empty string means \"inherit\".",
        "",
        f"schema_version = {cfg.get('schema_version', SCHEMA_VERSION)}",
        "",
        "[review]",
        "# The gate. A run must score at least this to be SATISFIED.",
        "# Lower is stricter. A REGRESSION DETECTOR, not an absolute bar: of nine",
        "# well-regarded repos reviewed at --samples 5, one is clean, so there is no",
        "# known-good class to calibrate against. --baseline auto compares a repo",
        "# against its own previous run. docs/CALIBRATION.md.",
        f"threshold = {review.get('threshold')}",
        "# Reviewer samples per round. More samples find more, and cost more time.",
        f"samples = {review.get('samples')}",
        "# advisory = report and stop (cheapest, the default)",
        "# semi     = fix, asking before each change",
        "# full     = fix and re-review until the gate passes or it stops improving",
        f"mode = {_toml_string(str(review.get('mode')))}",
        f"max_rounds = {review.get('max_rounds')}",
    ]
    for name, member in (cfg.get("members") or {}).items():
        lines.append("")
        lines.append("# A member of the council. Becomes a Hermes profile.")
        lines.append(f"[members.{name}]")
        lines.append(f"role = {_toml_string(str(member.get('role')))}")
        if member.get("title"):
            lines.append(f"title = {_toml_string(str(member['title']))}")
        if member.get("description"):
            lines.append(f"description = {_toml_string(str(member['description']))}")
        lines.append("# Empty means inherit whatever the profile already uses.")
        lines.append(f"model = {_toml_string(str(member.get('model') or ''))}")
        lines.append(f"provider = {_toml_string(str(member.get('provider') or ''))}")
        lines.append("# The capabilities this member may use. `delegation` is refused:")
        lines.append("# the harness is the only fan-out.")
        toolsets = ", ".join(_toml_string(str(t)) for t in (member.get("toolsets") or []))
        lines.append(f"toolsets = [{toolsets}]")
        core = member.get("core_skills")
        if core is None:
            core = CORE_SKILLS.get(str(member.get("role")), ())
        core_s = ", ".join(_toml_string(str(s)) for s in core)
        lines.append("# REQUIRED and static: installed into the profile, so the member")
        lines.append("# always has them. A name here that is not in the repo is a hard")
        lines.append("# error -- the member would run without instructions it needs.")
        lines.append(f"core_skills = [{core_s}]")
        skills = ", ".join(_toml_string(str(s)) for s in (member.get("skills") or []))
        lines.append("# OPTIONAL: loaded on demand from the mounted skill library, and")
        lines.append("# never installed into the profile. A name that does not resolve")
        lines.append("# is a warning, not an error -- the member just cannot load it.")
        lines.append(f"skills = [{skills}]")
    lines.append("")
    return "\n".join(lines)


def write(cfg: Dict[str, Any], path: Optional[Path] = None,
          force: bool = False) -> Path:
    """Write the config. Refuses to clobber an existing one unless forced."""
    target = path or config_path()
    if target.exists() and not force:
        raise SystemExit(f"{target} already exists; pass force=True to overwrite")
    target.parent.mkdir(parents=True, exist_ok=True)
    text = render(cfg)
    # Round-trip before writing: every later verb would fail on a config we wrote
    # and cannot read back.
    try:
        tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:  # pragma: no cover - a bug, not input
        raise SystemExit(f"internal error: rendered config is not valid TOML: {exc}")
    target.write_text(text, encoding="utf-8", newline="\n")
    return target


def rubrics_dir(framework_root: Path) -> Path:
    """Where the rubrics live: the shipped tree, or a checkout."""
    for candidate in (framework_root / "skills", framework_root / "assets" / "rubrics"):
        if candidate.is_dir():
            return candidate
    return framework_root / "skills"


def reviewer_rubrics(framework_root: Path) -> List[str]:
    """The rubric skill names, globbed so a new one needs no edit here."""
    directory = rubrics_dir(framework_root)
    if not directory.is_dir():
        return []
    return sorted(p.name for p in directory.glob(RUBRIC_GLOB)
                  if p.is_dir() and (p / "SKILL.md").is_file())
