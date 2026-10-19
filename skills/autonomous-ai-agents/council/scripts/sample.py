#!/usr/bin/env python3
"""Run ONE generalist sample: the entry point a swarm card calls.

    council sample <repo> --index N --run-root <dir> [--round 1] [--scope ...]

Writes <run-root>/round-<n>/generalist-<index>.json, the same file the loop
writes and merge_generalist_samples reads, so the swarm needs no downstream
special-casing. The prompt is imported from council_loop.py, never restated.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).resolve().parent
LOOP_PATH = HERE / "council_loop.py"

_LOOP = None


def _loop():
    """council_loop, loaded by path.

    By path, not by import: these scripts are the framework tree, run from the Nix
    store and from a bare checkout, and neither is an installed package.
    """
    global _LOOP
    if _LOOP is None:
        spec = importlib.util.spec_from_file_location("council_loop", LOOP_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _LOOP = module
    return _LOOP


def load_probes(loop, repo: Path, round_dir: Path, timeout: int) -> List[Dict[str, Any]]:
    """The round's probe results, running them only if the round has none yet.

    The probes are deterministic, so one run per round is enough and re-running them
    per sample would multiply a minutes-long cost by the sample count. Samples in a
    swarm run concurrently, so two workers may race here on the very first sample of
    a fresh round; the loser's write is redundant, not wrong, because the input is
    the repository and the output is a pure function of it. Making that a lock would
    add a failure mode (a stale lock file in a durable run directory) to remove a
    duplicate that costs time and nothing else.
    """
    cached = round_dir / "probes.json"
    if cached.exists():
        try:
            data = json.loads(cached.read_text(encoding="utf-8"))
            if isinstance(data, list) and data:
                return data
        except (OSError, json.JSONDecodeError):
            pass  # unreadable cache: fall through and re-run rather than fail
    probes = loop.run_probes(repo, timeout=timeout)
    round_dir.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps(probes, indent=2, ensure_ascii=False) + "\n",
                      encoding="utf-8", newline="\n")
    return probes


def load_goals(loop, round_dir: Path, round_no: int) -> Dict[str, Any]:
    """The round's goals, set by the orchestrator card, else the built-in set.

    Fail-open, matching the loop: a round whose goals file is missing or malformed
    still reviews, it just reviews against the default goals rather than failing.
    """
    goals_path = round_dir / "goals.json"
    if goals_path.exists():
        goals = loop.read_goals(goals_path, round_no)
        if goals:
            return goals
    return loop.default_goals(round_no)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sample",
        description="Run ONE generalist reviewer sample and write generalist-N.json. "
                    "The durable swarm's worker entry point (M7).")
    parser.add_argument("repo", help="the repository to review")
    parser.add_argument("--index", type=int, required=True,
                        help="which sample this is (1-based); names the output file")
    parser.add_argument("--run-root", default=None,
                        help="where run dirs live (default: <repo>/.review-council)")
    parser.add_argument("--round", type=int, default=1, dest="round_no")
    parser.add_argument("--scope", default="whole-repo",
                        choices=("diff", "working-tree", "whole-repo"))
    parser.add_argument("--timeout", type=int, default=1800,
                        help="per-turn timeout, seconds")
    args = parser.parse_args(argv)

    repo = Path(args.repo).expanduser().resolve()
    if not repo.is_dir():
        print(f"sample: not a directory: {repo}", file=sys.stderr)
        return 2
    if args.index < 1:
        print("sample: --index must be at least 1", file=sys.stderr)
        return 2

    loop = _loop()
    binary = loop.hermes_bin()
    if binary is None:
        print("sample: `hermes` is not on PATH — it runs the reviewer", file=sys.stderr)
        return 2

    run_root = (Path(args.run_root).expanduser() if args.run_root
                else repo / ".review-council")
    round_dir = run_root / f"round-{args.round_no}"
    round_dir.mkdir(parents=True, exist_ok=True)

    sha = loop.git_sha(repo)
    stacks = loop._gate_module().detect_stacks(repo)
    # The LOOP writes this, and a swarm sample must too: without meta.json,
    # resolve_stacks falls back to ["generic"], which has no expected tools, so every
    # dimension scores beta = 0 and the round reads as "judgement-only". Observed.
    if not (round_dir / "meta.json").exists():
        loop.write_meta(round_dir, repo, args.scope, args.round_no, stacks, sha)
    probes = load_probes(loop, repo, round_dir, args.timeout)
    goals = load_goals(loop, round_dir, args.round_no)

    out_path = round_dir / f"generalist-{args.index}.json"
    prompt = loop.generalist_prompt(repo, args.scope, args.round_no, sha, stacks,
                                    probes, goals, out_path)
    log = round_dir / f"sample-{args.index}.log"

    print(f"sample {args.index}: {repo.name} @ {sha[:12]}, stacks="
          f"{', '.join(stacks) or 'none'}, {len(probes)} probe(s)")
    rc = loop.run_one_generalist_sample(binary, repo, out_path, prompt,
                                        args.timeout, log)

    if rc == 0 and out_path.exists():
        try:
            doc = json.loads(out_path.read_text(encoding="utf-8-sig"))
            findings = len(doc.get("findings") or [])
            print(f"sample {args.index}: wrote {out_path.name} ({findings} finding(s))")
        except (OSError, json.JSONDecodeError):
            print(f"sample {args.index}: wrote {out_path.name} (unparseable)")
    else:
        # Say which failed: the merge sees both, and the board is where it is diagnosed.
        print(f"sample {args.index}: FAILED (rc={rc}, "
              f"file={'present' if out_path.exists() else 'missing'})", file=sys.stderr)
    return rc


if __name__ == "__main__":
    # Not a program: reached through `council <verb>`. See council.py.
    from council import require_dispatch

    require_dispatch("sample")
    raise SystemExit(main())
