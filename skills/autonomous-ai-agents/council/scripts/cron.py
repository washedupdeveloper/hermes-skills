#!/usr/bin/env python3
"""cron.py — schedule an unattended review with Hermes cron (M7).

M7 asked for "cron for unattended scheduled reviews (`cron.*`), noting
`cron.allow_agent_scheduling: false`". The note matters: a council run must not be able
to schedule itself, so this verb is the only path to a schedule and a reviewer never has
it. That is deliberate — an agent that can schedule its own follow-up reviews can also
schedule them forever.

Like `council goal`, this prints the command rather than acting. A schedule is a standing
commitment that outlives the session that made it, so it is something a person opts into
with `--install`, not something a command does on their behalf while they are reading its
output.

    council cron <repo>                       print the command (default: daily 09:00)
    council cron <repo> --schedule "0 9 * * 1"  every Monday
    council cron <repo> --install             create the job
    council cron <repo> --json

The prompt tells the agent to RUN the council and report the gate's numbers verbatim.
It does not ask for an opinion: a cron job whose agent reviews the code itself would
produce a second, unaudited reviewer, and its score would not be the score the framework
enforces.
"""
from __future__ import annotations

import argparse
import json
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

#: Daily at 09:00. A review is a diff-shaped job, so daily is a sane default; a team
#: that wants per-push runs should wire the forge, not a timer.
DEFAULT_SCHEDULE = "0 9 * * *"
DEFAULT_DELIVER = "local"


def job_name(repo: Path) -> str:
    return f"council: {repo.name}"


def prompt_for(repo: Path, samples: Optional[int]) -> str:
    """The instruction the cron agent receives. Self-contained: a fresh session."""
    sample_flag = f" --samples {samples}" if samples else ""
    return (
        f"Run an unattended code review of {repo} and report its verdict.\n\n"
        f"Run exactly this command and report its output verbatim:\n\n"
        f"    council review {repo}{sample_flag}\n\n"
        f"Do NOT review the code yourself, and do NOT summarise the reviewers' prose as "
        f"if it were the verdict. The command writes outcome.json and next-steps.md into "
        f"the run directory; report the verdict, the aggregate, the threshold and beta "
        f"per dimension from that file. If the command fails, report its exit code and "
        f"stderr and stop — a missing run is a real answer, an invented one is not."
    )


def build(repo: Path, schedule: str = DEFAULT_SCHEDULE, deliver: str = DEFAULT_DELIVER,
          samples: Optional[int] = None, name: Optional[str] = None) -> Dict[str, Any]:
    """The plan, as data. Pure: no subprocess, no filesystem write."""
    argv = [
        "hermes", "cron", "create",
        "--name", name or job_name(repo),
        "--deliver", deliver,
        "--workdir", str(repo),
        schedule,
        prompt_for(repo, samples),
    ]
    return {
        "repo": str(repo),
        "name": name or job_name(repo),
        "schedule": schedule,
        "deliver": deliver,
        "samples": samples,
        "argv": argv,
        "command": " ".join(shlex.quote(a) for a in argv),
    }


def render(plan: Dict[str, Any]) -> List[str]:
    # A one-line command is unreadable once the prompt is in it, and the prompt has to
    # be in it — the job must be self-contained. Backslash continuations keep it both
    # copy-pasteable and legible.
    argv = plan["argv"]
    head, schedule, prompt = argv[:-2], argv[-2], argv[-1]
    lines = [
        f"  repo      {plan['repo']}",
        f"  name      {plan['name']}",
        f"  schedule  {plan['schedule']}",
        f"  deliver   {plan['deliver']}",
        "",
        "  Create it with:",
        "",
        "    " + " ".join(shlex.quote(a) for a in head) + " \\",
        f"      {shlex.quote(schedule)} \\",
        f"      {shlex.quote(prompt)}",
        "",
        "  Then confirm it exists, and that it is the job you meant:",
        "",
        "    hermes cron list",
        f"    hermes cron run {shlex.quote(plan['name'])}    # fire it once, now",
        "",
        "  `council cron` does not install on its own: a schedule outlives the session",
        "  that made it. Pass --install to create it, or paste the command above.",
        "",
        "  A reviewer never has this verb. `cron.allow_agent_scheduling` is false, so an",
        "  agent cannot schedule its own follow-up reviews — only a person can.",
    ]
    return lines


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="council cron",
        description="Print (or install) a Hermes cron job that runs an unattended "
                    "review and reports the gate's verdict.")
    parser.add_argument("repo", help="the repository to review")
    parser.add_argument("--schedule", default=DEFAULT_SCHEDULE,
                        help=f"a cron expression or interval (default: {DEFAULT_SCHEDULE!r})")
    parser.add_argument("--deliver", default=DEFAULT_DELIVER,
                        help=f"where the report goes (default: {DEFAULT_DELIVER!r})")
    parser.add_argument("--samples", type=int, default=None,
                        help="reviewer samples per round (default: the council's own)")
    parser.add_argument("--name", default=None, help="job name (default: 'council: <repo>')")
    parser.add_argument("--install", action="store_true",
                        help="create the job instead of printing the command")
    parser.add_argument("--json", action="store_true", help="the plan as JSON")
    args = parser.parse_args(argv)

    repo = Path(args.repo).expanduser().resolve()
    if not repo.is_dir():
        print(f"cron: not a directory: {repo}", file=sys.stderr)
        return 2
    if args.samples is not None and args.samples < 1:
        print("cron: --samples must be at least 1", file=sys.stderr)
        return 2

    plan = build(repo, args.schedule, args.deliver, args.samples, args.name)

    if args.install:
        if not shutil.which("hermes"):
            print("cron: `hermes` is not on PATH, and it owns the schedule. "
                  "Install Hermes, or run the printed command where it is.",
                  file=sys.stderr)
            return 2
        proc = subprocess.run(plan["argv"], capture_output=True, text=True)
        if proc.returncode != 0:
            print(f"cron: creating the job failed:\n{proc.stderr.strip()}", file=sys.stderr)
            return 1
        print(f"  created {plan['name']!r} on {plan['schedule']!r}")
        if proc.stdout.strip():
            print(f"  {proc.stdout.strip()}")
        # Verify rather than assume: a job that did not register looks identical to
        # one that did until the first tick never happens.
        listed = subprocess.run(["hermes", "cron", "list"],
                                capture_output=True, text=True)
        if listed.returncode == 0 and plan["name"] not in listed.stdout:
            print("cron: the job was accepted but does not appear in `hermes cron "
                  "list`. Check `hermes cron list` before relying on it.", file=sys.stderr)
            return 1
        return 0

    if args.json:
        print(json.dumps(plan, indent=2, ensure_ascii=False))
        return 0
    for line in render(plan):
        print(line)
    return 0


if __name__ == "__main__":
    # Not a program: reached through `council <verb>`. See council.py.
    from council import require_dispatch

    require_dispatch("cron")
    sys.exit(main())
