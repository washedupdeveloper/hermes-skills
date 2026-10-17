#!/usr/bin/env python3
"""init.py — the guided first-run setup.

`council init` walks a new user through the handful of choices that are theirs
to make, writes them to one editable file, and installs. It is deliberately the
shape of a good shell installer: a short banner, every question carrying a
default you accept by pressing Enter, a summary of what will happen before
anything happens, and a next-steps block at the end.

Three properties it must have, because it is the first thing a stranger runs:

  * It never hangs. With no terminal it takes every default and says so, so
    `docker run` and CI cannot wedge on a prompt.
  * It never installs without saying what. The summary comes first and `--yes`
    only skips the questions, not the report.
  * It is safe to re-run. Existing values become the defaults, so the second
    run is "change one thing", not "answer everything again".
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import council_config as cfg_mod  # noqa: E402

ROOT = HERE.parent


def _tty() -> bool:
    """Can we actually ask a human? A piped or detached stdin cannot."""
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False


def _ask(prompt: str, default: str, assume_yes: bool) -> str:
    """One question. Enter accepts the default; EOF accepts it too, rather than
    raising -- a closed stdin is not an error, it is a non-answer."""
    if assume_yes or not _tty():
        return default
    sys.stdout.write(f"  {prompt} [{default}]: ")
    sys.stdout.flush()
    try:
        answer = input().strip()
    except (EOFError, KeyboardInterrupt):
        sys.stdout.write("\n")
        return default
    return answer or default


def _ask_choice(prompt: str, choices: List[str], default: str,
                assume_yes: bool) -> str:
    """A closed question: the answer must be one of the choices."""
    if assume_yes or not _tty():
        return default
    joined = "/".join(choices)
    while True:
        answer = _ask(f"{prompt} ({joined})", default, assume_yes).strip().lower()
        if answer in choices:
            return answer
        sys.stdout.write(f"    {answer!r} is not one of {joined}\n")


def _banner(text: str) -> None:
    print()
    print(text)
    print("-" * len(text))


def _detect() -> Dict[str, Any]:
    """What we can learn without asking. Everything optional."""
    found: Dict[str, Any] = {}
    try:
        import hermes  # type: ignore  # the sibling module, not the product
        found["hermes_bin"] = hermes.launcher()
        found["hermes_version"] = hermes.version() if found["hermes_bin"] else None
        found["hermes_verdict"] = hermes.report().get("verdict")
    except Exception:  # noqa: BLE001 - detection must never break setup
        found["hermes_bin"] = None
    found["rubrics"] = cfg_mod.reviewer_rubrics(ROOT)
    return found


def main(argv: Optional[List[str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    assume_yes = "--yes" in argv or "-y" in argv
    no_install = "--no-install" in argv
    for arg in argv:
        if arg in ("-h", "--help"):
            print("council init — guided first-run setup")
            print()
            print("  --yes         accept every default, ask nothing")
            print("  --no-install  write the config and stop; do not install")
            print()
            print("Writes review-council.yaml to your Hermes home, then installs")
            print("the skill and the profiles. Safe to re-run.")
            return 0
        if arg.startswith("-") and arg not in ("--yes", "-y", "--no-install"):
            print(f"council init: unknown argument: {arg}", file=sys.stderr)
            return 2

    found = _detect()
    existing, existing_path = cfg_mod.load()
    interactive = _tty() and not assume_yes

    _banner("review-council — setup")
    print("  A council of review agents that scores your repository against")
    print("  pinned analyzers and reports cited findings.")
    print()
    if existing_path:
        print(f"  Found an existing config: {existing_path}")
        print("  Its values are the defaults below; press Enter to keep them.")
    else:
        print(f"  No config yet. One will be written to {cfg_mod.config_path()}")
    if not interactive:
        print()
        print("  No terminal to ask on, so every default is used.")
        print("  Edit the config afterwards to change anything.")

    # ── Hermes ────────────────────────────────────────────────────────────────
    _banner("1. Hermes")
    if found.get("hermes_bin"):
        print(f"  launcher : {found['hermes_bin']}")
        print(f"  version  : {found.get('hermes_version') or '?'}")
        verdict = found.get("hermes_verdict")
        if verdict and verdict != "ready":
            print(f"  verdict  : {verdict} — `council doctor` explains what is missing")
    else:
        print("  No `hermes` launcher found on PATH.")
        print("  A review needs one. Install Hermes, or set HERMES_BIN to it.")
        print("  Setup can continue; nothing can review until it exists.")

    # ── the gate ──────────────────────────────────────────────────────────────
    _banner("2. The gate")
    review = existing.get("review", {})
    print("  A run is SATISFIED when it scores at least this. Lower is stricter.")
    print("  The shipped value is PROVISIONAL — a policy choice inside a measured")
    print("  equivalence band (80.63, 89.23), not a calibrated point. Recalibrate on")
    print("  yours with `council calibrate` (dev).")
    raw = _ask("threshold", str(review.get("threshold", 87.1141)), assume_yes)
    try:
        threshold = float(raw)
    except ValueError:
        print(f"    {raw!r} is not a number; keeping {review.get('threshold')}")
        threshold = float(review.get("threshold", 87.1141))

    # ── the run ───────────────────────────────────────────────────────────────
    _banner("3. How a run behaves")
    print("  Samples are independent reviewer passes. More finds more, and costs")
    print("  proportionally more time.")
    raw = _ask("samples", str(review.get("samples", 5)), assume_yes)
    try:
        samples = max(1, int(raw))
    except ValueError:
        samples = int(review.get("samples", 5))
    mode = _ask_choice(
        "mode", ["advisory", "semi", "full"],
        str(review.get("mode", "advisory")), assume_yes)
    if mode == "advisory":
        print("    advisory: report findings and stop. Cheapest, and the default.")

    # ── the members ───────────────────────────────────────────────────────────
    _banner("4. The members")
    print("  Each member becomes a Hermes profile. A review needs one reviewer")
    print("  and one orchestrator. `model`/`provider` left empty means the")
    print("  profile keeps whatever it already uses.")
    members: Dict[str, Any] = {}
    for name, member in (existing.get("members") or {}).items():
        entry = dict(member)
        print()
        print(f"  {name}  ({member.get('role')})")
        raw = _ask("model (blank = inherit)", str(member.get("model") or ""), assume_yes)
        entry["model"] = raw.strip() or None
        raw = _ask("provider (blank = inherit)", str(member.get("provider") or ""),
                   assume_yes)
        entry["provider"] = raw.strip() or None
        if member.get("role") == "reviewer":
            print(f"    rubrics: {len(found['rubrics'])} "
                  f"({', '.join(found['rubrics']) or 'none found'})")
        members[name] = entry

    # ── the summary ───────────────────────────────────────────────────────────
    cfg = {
        "schema_version": cfg_mod.SCHEMA_VERSION,
        "review": {
            "threshold": threshold,
            "samples": samples,
            "mode": mode,
            "max_rounds": review.get("max_rounds", 3),
        },
        "members": members,
    }
    problems = cfg_mod.validate(cfg)

    _banner("About to")
    target = cfg_mod.config_path()
    print(f"  write    {target}")
    print(f"  gate     {threshold}   samples {samples}   mode {mode}")
    for name, member in members.items():
        model = member.get("model") or "inherit"
        print(f"  member   {name} ({member.get('role')}, model {model})")
    if not no_install:
        print("  install  the council skill, then the profiles")
    print()
    if problems:
        print("  PROBLEMS with this configuration:")
        for problem in problems:
            print(f"    - {problem}")
        print("  Fix them and re-run. Nothing was written.")
        return 2

    if interactive:
        answer = _ask("proceed? (yes/no)", "yes", assume_yes).strip().lower()
        if answer not in ("y", "yes"):
            print("  Nothing written.")
            return 0

    # ── write ─────────────────────────────────────────────────────────────────
    _banner("Writing")
    try:
        written = cfg_mod.write(cfg, target, force=True)
    except OSError as exc:
        print(f"  cannot write {target}: {exc}", file=sys.stderr)
        return 1
    print(f"  wrote {written}")
    print("  Edit it any time; `council setup bots` applies your changes.")

    if no_install:
        print()
        print("  --no-install: stopping here.")
        print("  Next: council setup")
        return 0

    # ── install ───────────────────────────────────────────────────────────────
    _banner("Installing")
    from council import _run  # the CLI's own runner: same env contract

    rc = _run("sync_to_skill.py", [])
    if rc != 0:
        print("  the skill did not install; stopping before the profiles.")
        return rc
    rc = _run("install_bots.py", [])
    if rc != 0:
        print("  the profiles did not install.")
        return rc

    # ── next steps ────────────────────────────────────────────────────────────
    _banner("Next")
    print("  1. Credentials. Hermes keeps them PER PROFILE and shares none, so")
    print("     each member needs its own:")
    for name in members:
        print(f"       hermes -p {name} setup")
    print()
    print("  2. Check the machine:")
    print("       council doctor --repo <your-repo>")
    print()
    print("  3. Review something:")
    print("       council review <your-repo> --mode advisory --max-rounds 1")
    print()
    print("  4. In an agent session, /council does the same thing and reads")
    print(f"     {cfg_mod.CONFIG_NAME} for how.")
    print()
    print(f"  Change anything in {target} and re-run `council setup bots`.")
    return 0


if __name__ == "__main__":
    from council import require_dispatch

    require_dispatch("setup init")
    sys.exit(main())
