"""The council CLI. Every verb is a module beside this file.

Reach it through the flake (`nix run .#council -- <verb>`), the container image,
or directly when neither is available — the skill ships this file:

    python3 <skill_dir>/scripts/council.py <verb>

The individual modules are implementation. Running one by hand is refused; this
is the entry point, and the only thing that sets the dispatch variable.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

try:
    import toolchain  # type: ignore
except ImportError:  # pragma: no cover
    toolchain = None  # type: ignore

# name -> (module, audience, takes arguments, one-line description)
#   audience "user" ships in the app; "dev" is the devshell only.
#   takes arguments false means the verb ACTS, so --help is answered here rather
#   than passed through -- a --help that installs something is a trap.
VERBS: Dict[str, Tuple[str, str, bool, str]] = {
    "review": ("council_loop.py", "user", True, "drive a review to a verdict (the loop)"),
    "gate": ("score_reviews.py", "user", True, "the deterministic gate: score a run directory"),
    "doctor": ("doctor.py", "user", True, "which analyzers ran, and the beta they yield"),
    "probes": ("probes.py", "user", True, "the built-in deterministic probes"),
    "swarm": ("swarm.py", "user", True, "the durable council: build a kanban graph"),
    "sample": ("sample.py", "user", True, "run ONE reviewer sample"),
    "merge": ("merge.py", "user", True, "bucket a round's samples into the per-dimension files"),
    "calibrate": ("calibrate.py", "dev", True, "recalibrate the threshold and curves"),
    "ablate": ("ablate.py", "dev", True, "the four-arm ablation behind M8.5"),
    "golden": ("golden.py", "dev", True, "replay fixed inputs and diff against pinned values"),
    "baseline": ("baseline.py", "user", True, "report the baseline, or what changed since it"),
    "metrics": ("metrics.py", "user", True, "acceptance, addressed and iterations from judged findings"),
    "goal": ("goal.py", "user", True, "express a run as a native Hermes /goal + quality gate"),
    "cron": ("cron.py", "user", True, "print or install a scheduled unattended review"),
    "pr": ("pr.py", "user", True, "post a run's verdict to a GitHub pull request"),
    "version": ("version.py", "dev", True, "check or bump the release version (docs/VERSIONING.md)"),
    "corpus": ("inject_defects.py", "dev", True, "build a defect corpus with independent truth"),
}

SETUP: Dict[str, Tuple[str, str]] = {
    "init": ("init.py", "guided first-run setup: writes the config, then installs"),
    "skill": ("sync_to_skill.py", "install the council skill into the Hermes skill library"),
    "bots": ("install_bots.py", "install the reviewer and orchestrator profiles"),
    "toolchain": ("toolchain.py", "print or activate the pinned toolchain"),
    "dispatcher": ("install_dispatcher.py", "run the kanban dispatcher as a systemd user service"),
}


def audience() -> str:
    """Which verb surface this process should expose."""
    return os.environ.get("REVIEW_COUNCIL_AUDIENCE", "user")


def visible() -> Dict[str, Tuple[str, str, bool, str]]:
    return {name: spec for name, spec in VERBS.items()
            if audience() == "dev" or spec[1] == "user"}


def verbs_json() -> str:
    """The whole table as JSON, for the flake's checks.

    One table: the flake used to carry its own copy and the two drifted, so a verb
    could exist in the CLI and be missing from the checks that prove it ships.
    """
    rows = [
        {"verb": name, "script": spec[0], "audience": spec[1],
         "probe": spec[2], "what": spec[3]}
        for name, spec in VERBS.items()
    ]
    rows += [
        {"verb": f"setup {name}", "script": script, "audience": "user",
         "probe": False, "what": what}
        for name, (script, what) in SETUP.items()
    ]
    return json.dumps(rows, indent=2)


def _line(label: str, what: str) -> str:
    return f"  {label:<18} {what}"


# ── The dispatch rule ────────────────────────────────────────────────────────
#
# A module under scripts/ is not a program. It is reached through this CLI, which
# is what puts the pinned toolchain on PATH, sets the audience, and knows which
# verb maps to which module. Running one directly skips all three, and several of
# them act rather than report: `setup bots` writes into HERMES_HOME, `setup skill`
# prunes the skill deployment, `corpus` plants defects in a repository it is pointed at,
# and `review`, `sample` and `ablate` spend real agent turns over the network.
#
# So a module refuses a direct invocation unless this variable is set, and this
# file sets it. Child processes inherit it, which is how the harness still runs
# probes.py and score_reviews.py as subprocesses.
#
# WHAT THIS IS NOT: a security boundary. It stops an ACCIDENTAL `python3
# scripts/x.py` -- someone exploring the tree -- and it says what to run instead.
# It does not stop a caller who sets the variable, and nothing in this repository
# could: an agent with a terminal can set it too. The boundary is the sandbox and
# the filesystem, not this check. Do not describe it as more than it is.
DISPATCH_VAR = "REVIEW_COUNCIL_DISPATCHED"


def require_dispatch(verb: str) -> None:
    """Refuse a bare `python3 scripts/<module>.py`, and name the real entry point.

    A guard against accident, not against intent -- see DISPATCH_VAR above.

    Called from a module's `__main__` block, never at import: the test suite loads
    these files as libraries and calls `main()` directly, which is not a hand-run
    and must keep working.
    """
    if os.environ.get(DISPATCH_VAR) == "1":
        return
    sys.exit(
        f"{verb}: this is a module of the council CLI, not a program.\n"
        f"  run it as:  council {verb} --help\n"
        f"  or:         nix run .#council -- {verb} --help\n"
        f"Nothing under scripts/ is meant to be run by hand."
    )


def usage() -> None:
    print("review-council")
    print()
    print("USAGE")
    print("  council <verb> [args...]")
    print("  council <repo> [flags]     shorthand for: council review <repo>")
    print()
    print("VERBS")
    for name, spec in visible().items():
        print(_line(name, spec[3]))
    print(_line("inventory", "the pinned tool set as JSON"))
    print()
    print("SETUP (once per machine)")
    for name, (_, what) in SETUP.items():
        print(_line(f"setup {name}", what))
    print()
    print("Run 'council <verb> --help' for that verb's own options.")


def _exec(script: str, args: List[str]) -> int:
    target = HERE / script
    if not target.exists():
        print(f"council: {script} is missing from {HERE}", file=sys.stderr)
        return 2
    # The module's `__main__` refuses to run without this. Set here and nowhere
    # else, so the CLI is the only way in; child processes inherit it.
    os.environ[DISPATCH_VAR] = "1"
    os.execv(sys.executable, [sys.executable, str(target)] + args)
    return 0


def _run(script: str, args: List[str]) -> int:
    """Run a module and WAIT, for a first-run verb that does two things in order.

    `_exec` replaces this process, which is right for a single verb and impossible
    for a sequence. Same environment contract, so the child's guard still passes.
    """
    target = HERE / script
    if not target.exists():
        print(f"council: {script} is missing from {HERE}", file=sys.stderr)
        return 2
    env = dict(os.environ, **{DISPATCH_VAR: "1"})
    try:
        return subprocess.run([sys.executable, str(target)] + args, env=env).returncode
    except OSError as exc:
        print(f"council: cannot run {script}: {exc}", file=sys.stderr)
        return 2


def _setup(args: List[str]) -> int:
    name = args[0] if args else ""
    if name in ("-h", "--help"):
        print("council setup -- once per machine")
        for sub, (_, what) in SETUP.items():
            print(_line(f"setup {sub}", what))
        return 0
    if not name or name.startswith("-"):
        # Bare `council setup`, or `council setup --yes`, is the first-run path: a
        # newcomer should not have to know which sub-verb installs what. It runs
        # the GUIDED setup, which asks the few questions that are theirs, writes
        # one editable config, and then installs both halves in order (the skill
        # first — it is the half that needs no Hermes profile to exist yet, and
        # the half that carries the framework a machine without nix or docker
        # runs). Flags are passed through to it.
        return _exec(SETUP["init"][0], args if name else [])
    if name not in SETUP:
        print(f"council setup: expected one of: {' '.join(SETUP)}", file=sys.stderr)
        return 2
    script, what = SETUP[name]
    rest = args[1:]
    if rest and rest[0] in ("-h", "--help"):
        print(f"council setup {name} — {what}")
        print("This verb acts rather than taking options; see docs/NIX.md.")
        return 0
    return _exec(script, rest)


def main(argv: List[str]) -> int:
    if not argv or argv[0] in ("-h", "--help", "help"):
        usage()
        return 0

    verb, rest = argv[0], argv[1:]

    if verb == "--verbs-json":
        print(verbs_json())
        return 0

    if verb == "inventory":
        print(json.dumps(toolchain.inventory() if toolchain else {}))
        return 0

    if verb == "setup":
        return _setup(rest)

    spec = visible().get(verb)
    if spec:
        return _exec(spec[0], rest)

    # A flag, or a path that exists, means review -- the shorthand.
    if verb.startswith("-") or Path(verb).exists():
        return _exec("council_loop.py", argv)

    print(f"council: not a verb, and no such path: {verb}", file=sys.stderr)
    print("Run 'council --help' to list the verbs.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
