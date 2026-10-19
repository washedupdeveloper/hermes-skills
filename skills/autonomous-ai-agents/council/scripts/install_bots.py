#!/usr/bin/env python3
"""install_bots.py — install/refresh the review-council bots as Hermes profiles."""

from __future__ import annotations

import importlib.util as _shared_util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, NoReturn, Optional

import council_config as cfg_mod
from hermes_home import resolve as resolve_hermes_home

# `_shared` by path, like every sibling here -- see its own docstring for why a
# plain import would not be safe.
_SHARED_SPEC = _shared_util.spec_from_file_location(
    "_shared", Path(__file__).resolve().parent / "_shared.py")
assert _SHARED_SPEC is not None and _SHARED_SPEC.loader is not None, "_shared.py"
_shared = _shared_util.module_from_spec(_SHARED_SPEC)
_SHARED_SPEC.loader.exec_module(_shared)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

# Every capability comes from the user's config (cfg_mod.CONFIG_NAME), never a
# constant here; `bots/*/bot.yaml` is not read at all. See council_config.py.

# The three trees this install reads and writes; the profile root is resolved in main.
BOTS_DIR: Path
RUBRICS_DIR: Path
PROFILES_DIR: Path


def die(message: str) -> NoReturn:
    print(message, file=sys.stderr)
    sys.exit(1)


def pick_dir(*candidates: Path) -> Optional[Path]:
    """The first candidate that is a directory."""
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return None


def run_checked(args: List[str], env: Optional[dict] = None) -> None:
    """Stdout is dropped, stderr is not; a non-zero status aborts like `set -e`."""
    proc = subprocess.run(args, env=env, stdout=subprocess.DEVNULL)
    if proc.returncode != 0:
        sys.exit(proc.returncode)


def copy_file(src: Path, dst: Path) -> None:
    """Copy src over dst, tolerating a read-only dst.

    The framework ships from the Nix store, where every file is mode 0444, and
    `shutil.copy` preserves the SOURCE mode. So the first install leaves a
    read-only file in the profile and `shutil.copy` — which opens the
    destination `wb` — then fails with EACCES on every later install. That made
    `council setup bots` a once-only verb: the second run died with
    "Permission denied" on a file the first run had just written.

    Unlink first (the destination directory is ours and writable), then
    normalize the mode so the NEXT install can overwrite it too.
    """
    try:
        if dst.exists() or dst.is_symlink():
            dst.unlink()
        shutil.copy(src, dst)
        dst.chmod(0o644)
    except OSError as exc:
        die(f"council setup bots: cannot copy {src}: {exc}")


def library_paths(raw: Optional[str] = None) -> List[Path]:
    """The mounted skill libraries as real paths. Empty when none is configured.

    *raw* lets a caller that already resolved `library_dirs()` pass it in — that
    value costs a `hermes config get` subprocess, and calling it twice per member
    was pure waste.
    """
    try:
        entries = json.loads(raw if raw is not None else (library_dirs() or "[]"))
    except (json.JSONDecodeError, TypeError):
        return []
    out: List[Path] = []
    for entry in (entries if isinstance(entries, list) else []):
        path = Path(str(entry)).expanduser()
        if path.is_dir():
            out.append(path)
    return out


def resolves(skill: str, libraries: List[Path]) -> bool:
    """Whether an OPTIONAL skill can be loaded by name.

    Two ways it can: it is a rubric in this repo (so the profile has it anyway),
    or it is somewhere in a mounted library. Neither means it is installed here —
    an optional skill is loaded on demand, not copied.
    """
    if (RUBRICS_DIR / skill / "SKILL.md").is_file():
        return True
    for root in libraries:
        for candidate in root.rglob(skill):
            if candidate.is_dir() and (candidate / "SKILL.md").is_file():
                return True
    return False


def hermes_output(args: List[str]) -> str:
    """A `hermes ...` command's stdout, or empty when it cannot run; stderr dropped."""
    return _shared.hermes_run(args)[1]


def library_dirs() -> str:
    """The default profile's skills.external_dirs, newlines and CRs stripped."""
    out = hermes_output(["hermes", "config", "get", "skills.external_dirs", "--json"])
    return out.replace("\r", "").replace("\n", "")


def toolset_count(toolsets: List[str]) -> int:
    return len(toolsets)


def _set_profile_config(profile_dir: Path, key: str, value: str) -> None:
    env = dict(os.environ, HERMES_HOME=str(profile_dir))
    run_checked(["hermes", "config", "set", key, value], env=env)


def install_member(name: str, member: Dict[str, Any], rubrics: List[str]) -> None:
    """Create the profile when missing, then refresh it from the CONFIG.

    Every capability is read, never assumed: a member with no `toolsets` gets an
    empty set rather than a remembered default, so what the config says is what
    the profile runs.
    """
    target = PROFILES_DIR / name
    role = member.get("role", "reviewer")
    if not target.is_dir():
        run_checked(["hermes", "profile", "create", name, "--clone", "--no-alias",
                     "--description",
                     member.get("description") or f"review-council {role}"])
        print(f"  created  {name}")

    # SOUL.md is optional: only a member that ships one gets it refreshed.
    soul = BOTS_DIR / name / "SOUL.md"
    if soul.is_file():
        copy_file(soul, target / "SOUL.md")
    profile_yaml = BOTS_DIR / name / "profile.yaml"
    if profile_yaml.is_file():
        copy_file(profile_yaml, target / "profile.yaml")

    # CORE: required, installed. From the config, not a glob; a config written before
    # `core_skills` existed falls back to the shipped set.
    core = member.get("core_skills")
    if not core:
        if role == "reviewer":
            core = list(rubrics)
        else:
            # Rubric is `review-council-orchestrator`, member `council-orchestrator`: the
            # fallback glob has to be a SUFFIX match.
            core = sorted(p.name for p in RUBRICS_DIR.glob(f"*{name}")
                          if p.is_dir() and (p / "SKILL.md").is_file())
    missing = [s for s in core if not (RUBRICS_DIR / s / "SKILL.md").is_file()]
    if missing:
        die(f"council setup bots: {name} requires {missing}, not found under "
            f"{RUBRICS_DIR}. Refusing: a member that runs without its core skills "
            f"reviews with no rubric and reports nothing.")
    wanted = list(core)

    for skill_dir in wanted:
        (target / "skills" / skill_dir).mkdir(parents=True, exist_ok=True)
        copy_file(RUBRICS_DIR / skill_dir / "SKILL.md",
                  target / "skills" / skill_dir / "SKILL.md")

    # Prune only the SHIPPED rubric namespace, never a glob over the profile's skills/
    # tree: `--clone` filled that with every bundled skill, and a stale rubric is
    # worse than an absent one -- the merge silently drops its findings.
    shipped = set(rubrics) | {s for names in cfg_mod.CORE_SKILLS.values() for s in names}
    for stale_name in sorted(shipped):
        if stale_name in wanted:
            continue
        stale = target / "skills" / stale_name
        if stale.is_dir():
            shutil.rmtree(stale)
            print(f"  pruned   {stale_name}  (not in core_skills)")

    _set_profile_config(target, "platform_toolsets.cli",
                        json.dumps(member.get("toolsets") or []))
    # Applied ONLY when named: unset means "inherit", so a `hermes -p <name> model`
    # choice is never overwritten.
    if member.get("model"):
        _set_profile_config(target, "model.name", str(member["model"]))
    if member.get("provider"):
        _set_profile_config(target, "model.provider", str(member["provider"]))

    # The library mount is read from the default profile, so it stays machine-agnostic.
    library = library_dirs()
    if library and library != "[]":
        _set_profile_config(target, "skills.external_dirs", library)
        print(f"  mounted  {name}  ->  {library}")

    # OPTIONAL: loaded by name from the mounted library, never installed. Unresolved is
    # a warning, not fatal -- smaller than a review that refuses to start.
    optional = [s for s in (member.get("skills") or []) if s]
    if optional:
        libs = library_paths(library)
        found = [s for s in optional if resolves(s, libs)]
        absent = [s for s in optional if s not in found]
        if found:
            print(f"  on demand {name}  ->  {', '.join(found)}")
        if absent:
            print(f"  WARN     {name}  ->  optional {', '.join(absent)} not found in "
                  f"the mounted library; the member cannot load them")

    model = member.get("model") or "inherit"
    print(f"  ok       {name}  ({role}, {toolset_count(member.get('toolsets') or [])} "
          f"toolsets, {len(wanted)} skill(s), model {model})")


def main() -> int:
    """Install every member the config declares. No options: this verb ACTS."""
    global BOTS_DIR, RUBRICS_DIR, PROFILES_DIR

    cfg, path = cfg_mod.load()
    problems = cfg_mod.validate(cfg)
    if problems:
        print(f"council setup bots: your {cfg_mod.CONFIG_NAME} has problems:",
              file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print(f"  ({path or cfg_mod.config_path()})", file=sys.stderr)
        return 2
    if path is None:
        print(f"council setup bots: no {cfg_mod.CONFIG_NAME} yet, so the shipped "
              "defaults are used.")
        print("  Run `council setup` (guided) to write one you can edit.")

    home = os.environ.get("HERMES_PROFILES_DIR")
    PROFILES_DIR = Path(home if home else f"{resolve_hermes_home()}/profiles")

    bots = pick_dir(ROOT / "bots", ROOT / "assets" / "bots")
    if bots is None:
        die(f"council setup bots: no bot definitions found under {ROOT} "
            "(looked for bots/, assets/bots/)")
    BOTS_DIR = bots

    rubrics = cfg_mod.rubrics_dir(ROOT)
    if not rubrics.is_dir():
        die(f"council setup bots: no rubric skills found under {ROOT} "
            "(looked for skills/, assets/rubrics/)")
    RUBRICS_DIR = rubrics
    available = cfg_mod.reviewer_rubrics(ROOT)

    if shutil.which("hermes") is None:
        die("hermes not found on PATH")

    print(f"Installing review-council members into: {PROFILES_DIR}")
    if path:
        print(f"  from {path}")
    print()

    for name, member in (cfg.get("members") or {}).items():
        install_member(name, member, available)

    print()
    print("Members installed. ONE STEP LEFT: credentials.")
    print()
    print("Hermes keeps provider credentials PER PROFILE and does not share them, so the")
    print("council cannot reach a provider until every member has them:")
    print()
    for name in (cfg.get("members") or {}):
        print(f"  hermes -p {name} setup")
    print()
    review = cfg.get("review") or {}
    print("Then review something:")
    print(f"  council review <repo> --mode {review.get('mode', 'advisory')} --max-rounds 1")
    print()
    print(f"  --samples N trades recall for wall-clock (config default: "
          f"{review.get('samples', 5)}).")
    print("  The reviewer is driven by the council, not invoked by hand.")
    print(f"  Change anything in {path or cfg_mod.CONFIG_NAME} and re-run this verb.")
    return 0


if __name__ == "__main__":
    # Not a program: reached through `council <verb>`. See council.py.
    from council import require_dispatch

    require_dispatch("setup bots")
    sys.exit(main())
