#!/usr/bin/env python3
"""goal.py — express a council run as a native Hermes `/goal`.

Hermes ships `/goal`: a standing objective that survives across turns, judged
after each one, with two features that matter here:

  * a **completion contract** — `outcome`, `verification`, `constraints`,
    `boundaries`, `stop_when` — which tightens both the continuation prompt and
    the judge;
  * a **quality gate** — a deterministic shell command that must exit 0 before
    the goal can be judged done at all. Gates run BEFORE the judge, and a red
    gate skips the judge entirely, feeding its exit code and output tail back as
    the next turn's prompt.

The council already has both halves: a deterministic gate that exits non-zero
when a run is not satisfied, and a verdict that is a number rather than an
opinion. So the council's autonomous mode does not need a bespoke loop in this
repository — it is a `/goal` whose quality gate is the council's own gate. That
is strictly better than re-implementing it: the gate is mechanical, so the
decision to stop is not an LLM's opinion, and `/goal status`, `/goal pause`,
`/subgoal`, `/goal wait` and the turn budget all work without this repository
writing any of it.

This verb prints the contract and the gate command, ready to paste. It does NOT
set the goal itself: `/goal` is a session command, and only the session the
agent is in can own one. `--json` is for a caller that wants the fields.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import council_config as cfg_mod  # noqa: E402

ROOT = HERE.parent


def _council_command() -> str:
    """How to invoke the council from a /goal gate.

    A quality gate is a shell command run by Hermes, so it must resolve without
    this session's environment. Prefer a `council` on PATH (the nix app, the
    container, an installed launcher); fall back to this interpreter plus the
    CLI beside us, which is the only form guaranteed to exist when the council
    was reached as a skill.
    """
    from shutil import which

    found = which("council")
    if found:
        return found
    return f"{sys.executable} {HERE / 'council.py'}"


def contract(repo: Path, threshold: float, gate_cmd: str) -> Dict[str, Any]:
    """The five contract fields, filled from what the council actually does.

    Every field is a statement the council can back: the threshold is the one it
    gates on, the verification is a command that really exits non-zero when the
    bar is not met, and `stop_when` names the two conditions under which the
    council itself hands back to a human rather than iterating.
    """
    return {
        "outcome": (
            f"{repo} scores at or above the council's gate ({threshold:g}) with no "
            f"open high or critical finding."
        ),
        "verification": f"`{gate_cmd}` exits 0",
        "constraints": (
            "Do not lower the threshold, do not weaken or remove an analyzer, do not "
            "delete or skip a test to make it pass, and do not edit .review-council/ "
            "by hand — the gate reads it."
        ),
        "boundaries": str(repo),
        "stop_when": (
            "A finding cannot be fixed without changing intended behaviour, or a "
            "round produces no score improvement — then report and stop."
        ),
    }


def render(repo: Path, cfg: Dict[str, Any], gate_cmd: str,
           goal_cmd: str) -> List[str]:
    threshold = float((cfg.get("review") or {}).get("threshold", 87.1141))
    fields = contract(repo, threshold, gate_cmd)
    review = cfg.get("review") or {}

    out: List[str] = []
    out.append("# The council, as a native Hermes /goal")
    out.append("#")
    out.append("# Paste this into a Hermes session. Nothing here is council-specific:")
    out.append("# /goal, its completion contract and its quality gates are Hermes")
    out.append("# features, so /goal status, /goal pause, /subgoal and the turn budget")
    out.append("# all work on it.")
    out.append("")
    out.append(f"/goal Raise {repo} to the council's bar")
    out.append("")
    for key in ("outcome", "verification", "constraints", "boundaries", "stop_when"):
        label = {"verification": "verify", "stop_when": "stop when"}.get(key, key)
        out.append(f"{label}: {fields[key]}")
    out.append("")
    out.append("# The quality gate. Gates run BEFORE the judge, and a red gate skips")
    out.append("# the judge entirely — so the decision to stop is this command's exit")
    out.append("# code, not a model's opinion.")
    out.append(f"/goal gate add {gate_cmd}")
    out.append("")
    out.append("# Work the loop. Each turn should either fix something or re-review:")
    out.append(f"#   council review {repo} --mode full --samples "
               f"{review.get('samples', 5)}")
    out.append("#")
    out.append("# `council gate --latest` scores the newest run, so the gate needs no")
    out.append("# run directory you would have to know.")
    return out


def main(argv: Optional[List[str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    as_json = "--json" in argv
    repo_arg: Optional[str] = None
    for arg in argv:
        if arg in ("-h", "--help"):
            print("council goal — express a run as a native Hermes /goal")
            print()
            print("  council goal <repo>          print the contract and the gate command")
            print("  council goal <repo> --json   the same fields, machine-readable")
            print()
            print("Paste the output into a Hermes session. /goal is a session command,")
            print("so this verb cannot set it for you — it prints what to set.")
            return 0
        if arg == "--json":
            continue
        if arg.startswith("-"):
            print(f"council goal: unknown argument: {arg}", file=sys.stderr)
            return 2
        repo_arg = arg

    if not repo_arg:
        print("council goal: give the repository to aim at "
              "(council goal <repo>)", file=sys.stderr)
        return 2
    repo = Path(repo_arg).expanduser().resolve()
    if not repo.is_dir():
        print(f"council goal: not a directory: {repo}", file=sys.stderr)
        return 2

    cfg, _path = cfg_mod.load()
    problems = cfg_mod.validate(cfg)
    if problems:
        # The threshold is what the contract promises, so a broken config must
        # not silently produce a contract that names a different bar.
        print("council goal: your review-council.yaml has problems:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 2

    threshold = float((cfg.get("review") or {}).get("threshold", 87.1141))
    gate_cmd = f"{_council_command()} gate --latest --repo {repo}"
    goal_cmd = f"Raise {repo} to the council's bar"

    if as_json:
        print(json.dumps({
            "goal": goal_cmd,
            "contract": contract(repo, threshold, gate_cmd),
            "gate": gate_cmd,
            "threshold": threshold,
        }, indent=2, ensure_ascii=False))
        return 0

    for line in render(repo, cfg, gate_cmd, goal_cmd):
        print(line)
    return 0


if __name__ == "__main__":
    # Not a program: reached through `council <verb>`. See council.py.
    from council import require_dispatch

    require_dispatch("goal")
    sys.exit(main())
