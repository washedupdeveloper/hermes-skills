#!/usr/bin/env python3
"""metrics.py — the interactive half of M8, computed from what the operator records.

`docs/MILESTONES.md` says the interactive metrics "need a signal the ladder cannot
supply: a human acting on a comment, or a PR's comment-resolution state", and that a
number invented for them "would be the kind of unproven claim this repository
refuses". This module keeps that promise in the only way that is honest:

  * it COMPUTES the metrics from records that exist;
  * when the records do not exist it reports `null` and names exactly what to write,
    rather than estimating, extrapolating, or substituting recall for acceptance.

The record is already in the schema. Every finding carries `status`, documented in
`ablate.py` as `open|fixed|wontfix|accepted`; `rejected` is added here because
"accepted" with no counterpart cannot express the false positive that SNR measures on
the ladder. The mapping is the whole design:

    open      not judged yet          -> counted as PENDING, never as a rejection
    accepted  judged real, not fixed  -> accepted, not addressed
    fixed     judged real, fixed      -> accepted and addressed
    wontfix   judged real, declined   -> accepted, not addressed
    rejected  judged not real         -> neither

So `acceptance_rate` is the share of JUDGED findings the reviewer got right, and
`addressed_rate` is the share that changed the code. They differ, which is why both
exist: a reviewer can be right and still not move a developer to act.

Iterations need no operator at all — `outcome.json` already records one score per
round, so `len(scores)` IS the iteration count. That half of M8 was never missing;
the milestone simply assumed all three needed the same signal.

    council metrics <run-dir>...        report one or more runs
    council metrics --repo <repo>       report every run under .review-council/
    council metrics --repo <repo> --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent

#: The claim was judged real, however it was resolved.
ACCEPTED = frozenset({"accepted", "fixed", "wontfix"})
#: The code actually changed.
ADDRESSED = frozenset({"fixed"})
#: The claim was judged not real.
REJECTED = frozenset({"rejected"})
#: Nobody has judged it.
PENDING = frozenset({"open"})
KNOWN = ACCEPTED | REJECTED | PENDING


def load(name: str, path: Path) -> Any:
    """Load a sibling module by path — the pattern every module here uses."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def dimensions() -> List[str]:
    """The dimension list, from the gate's own weights so the two cannot drift."""
    score = load("score_reviews", HERE / "score_reviews.py")
    return list(score.WEIGHTS)


def findings_in(run_dir: Path, dims: Sequence[str]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Every finding in a run directory, and the files that were unreadable.

    A run directory holds one `<dimension>.json` per reviewer file. A missing one is
    not an error — a run can be partial — but an unreadable one is reported, because
    silently skipping it would understate the denominator.
    """
    found: List[Dict[str, Any]] = []
    problems: List[str] = []
    for dim in dims:
        path = run_dir / f"{dim}.json"
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            problems.append(f"{path}: {exc}")
            continue
        for finding in payload.get("findings") or []:
            if isinstance(finding, dict):
                found.append(finding)
    return found, problems


def iterations_in(run_dir: Path) -> Optional[int]:
    """Rounds the loop ran, from `outcome.json`.

    `scores` carries one entry per round, so its length is the iteration count. None
    when there is no outcome file: a run that never terminated has no iteration count
    to report, and 0 would read as "one round".
    """
    path = run_dir / "outcome.json"
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    scores = payload.get("scores")
    if isinstance(scores, list):
        return len(scores)
    return None


def summarise(run_dirs: Iterable[Path], dims: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """The metrics, computed. `None` wherever the data does not exist."""
    dims = list(dims or dimensions())
    runs: List[Dict[str, Any]] = []
    problems: List[str] = []

    total = accepted = addressed = rejected = pending = 0
    unknown: Dict[str, int] = {}

    for run_dir in run_dirs:
        findings, bad = findings_in(run_dir, dims)
        problems.extend(bad)
        for finding in findings:
            status = str(finding.get("status") or "").strip().lower()
            if status not in KNOWN:
                # A typo must not be counted as a rejection, and must not vanish.
                unknown[status or "(empty)"] = unknown.get(status or "(empty)", 0) + 1
                pending += 1
                continue
            total += 1
            if status in ACCEPTED:
                accepted += 1
            if status in ADDRESSED:
                addressed += 1
            if status in REJECTED:
                rejected += 1
            if status in PENDING:
                pending += 1
        runs.append({
            "run": str(run_dir),
            "findings": len(findings),
            "judged": sum(1 for f in findings
                          if str(f.get("status") or "").strip().lower() in ACCEPTED | REJECTED),
            "iterations": iterations_in(run_dir),
        })

    judged = total - pending
    iteration_values = [r["iterations"] for r in runs if r["iterations"] is not None]

    missing: List[str] = []
    if total == 0:
        missing.append(
            "no findings in any run: the run directories hold no <dimension>.json "
            "reviewer files, so there is nothing to judge. `council merge` writes them "
            "from a round's samples.")
    elif judged == 0:
        missing.append(
            "no finding has been judged: every status is `open` (or unknown). Set "
            "`status` on each finding to `accepted`, `fixed`, `wontfix` or `rejected` "
            "in the run's <dimension>.json, from the developer's response or the "
            "forge's comment-resolution state.")
    if not iteration_values:
        missing.append(
            "no `outcome.json` in any run, so there is no iteration count. A run that "
            "terminated writes one; `council review` produces it.")

    result: Dict[str, Any] = {
        "runs": len(runs),
        "findings": total,
        "judged": judged,
        "accepted": accepted,
        "addressed": addressed,
        "rejected": rejected,
        "pending": pending,
        "coverage": (judged / total) if total else None,
        # null, never 0.0: no data is not a zero rate, and the two read identically in
        # a table.
        "acceptance_rate": (accepted / judged) if judged else None,
        "addressed_rate": (addressed / judged) if judged else None,
        "iterations": {
            "runs": len(iteration_values),
            "mean": (sum(iteration_values) / len(iteration_values)) if iteration_values else None,
            "per_run": iteration_values,
        },
        "per_run": runs,
        "missing": missing,
    }
    if unknown:
        result["unknown_statuses"] = unknown
        problems.append(
            "unknown status value(s): "
            + ", ".join(f"`{k}` x{v}" for k, v in sorted(unknown.items()))
            + f" — expected one of {', '.join(sorted(KNOWN))}")
    if problems:
        result["problems"] = problems
    return result


def render(result: Dict[str, Any]) -> List[str]:
    """A table a human reads, with `no data` spelled out rather than a dash."""
    def pct(value: Optional[float]) -> str:
        return "no data" if value is None else f"{value * 100:.1f}%"

    def num(value: Optional[float]) -> str:
        return "no data" if value is None else f"{value:.2f}"

    lines = [
        f"  runs            {result['runs']}",
        f"  findings        {result['findings']}",
        f"  judged          {result['judged']}"
        + (f"  (coverage {pct(result['coverage'])})" if result["coverage"] is not None else ""),
        "",
        f"  accepted        {result['accepted']}",
        f"  addressed       {result['addressed']}",
        f"  rejected        {result['rejected']}",
        f"  pending         {result['pending']}",
        "",
        f"  acceptance rate {pct(result['acceptance_rate'])}",
        f"  addressed rate  {pct(result['addressed_rate'])}",
        f"  iterations/run  {num(result['iterations']['mean'])}"
        + (f"  over {result['iterations']['runs']} run(s)"
           if result["iterations"]["runs"] else ""),
    ]
    for note in result.get("missing") or []:
        lines += ["", f"  MISSING  {note}"]
    for problem in result.get("problems") or []:
        lines += ["", f"  WARNING  {problem}"]
    return lines


def run_dirs_from(repo: Path) -> List[Path]:
    root = repo / ".review-council"
    if not root.is_dir():
        return []
    return sorted((p for p in root.iterdir() if p.is_dir()), reverse=True)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="council metrics",
        description="The interactive metrics: acceptance rate, addressed rate, and "
                    "iterations per run. Computed from the `status` field on each "
                    "finding, so it reports `no data` until someone judges them.")
    parser.add_argument("runs", nargs="*", metavar="RUN_DIR",
                        help="run directories (default: every run under --repo)")
    parser.add_argument("--repo", metavar="PATH", default=None,
                        help="report every run under <repo>/.review-council/")
    parser.add_argument("--json", action="store_true", help="the numbers as JSON")
    args = parser.parse_args(argv)

    dirs: List[Path] = []
    if args.runs:
        dirs = [Path(p).expanduser().resolve() for p in args.runs]
        bad = [d for d in dirs if not d.is_dir()]
        if bad:
            print(f"metrics: not a directory: {bad[0]}", file=sys.stderr)
            return 2
    elif args.repo:
        repo = Path(args.repo).expanduser().resolve()
        if not repo.is_dir():
            print(f"metrics: not a directory: {repo}", file=sys.stderr)
            return 2
        dirs = run_dirs_from(repo)
        if not dirs:
            print(f"metrics: no runs under {repo / '.review-council'}", file=sys.stderr)
            return 2
    else:
        parser.print_help()
        return 2

    result = summarise(dirs)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        for line in render(result):
            print(line)
    # Exit 0 with no data: that is a valid answer when the input is the operator's, and
    # non-zero would read as tool failure. Unknown statuses DO fail -- a record mistake.
    return 1 if result.get("unknown_statuses") else 0


if __name__ == "__main__":
    # Not a program: reached through `council <verb>`. See council.py.
    from council import require_dispatch

    require_dispatch("metrics")
    sys.exit(main())
