#!/usr/bin/env python3
"""Bucket a round's samples into the per-dimension files the gate reads.

The loop does this in-process. The durable swarm writes its samples from
separate processes, so its round needs assembling before the gate can score
it. Deterministic, no model, no network.

    council merge <run-dir>
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
    global _LOOP
    if _LOOP is None:
        spec = importlib.util.spec_from_file_location("council_loop", LOOP_PATH)
        module = importlib.util.module_from_spec(spec)
        sys.modules["council_loop"] = module
        spec.loader.exec_module(module)
        _LOOP = module
    return _LOOP


def sample_paths(round_dir: Path) -> List[Path]:
    """The generalist samples in a round, in index order.

    Sorted numerically, not lexically: `generalist-10.json` must follow
    `generalist-9.json`, and a lexical sort would put it between 1 and 2.
    """
    found = []
    for path in round_dir.glob("generalist-*.json"):
        try:
            found.append((int(path.stem.split("-")[1]), path))
        except (IndexError, ValueError):
            continue  # not a numbered sample; ignore rather than crash
    return [path for _, path in sorted(found)]


def read_probes(round_dir: Path) -> List[Dict[str, Any]]:
    """The round's probe results, or none.

    Merging does not need them, but the harness seeds tools_run from them (a probe
    that ran IS the tool running), and dropping them would silently halve beta on
    every dimension whose expected tools are builtin. An unreadable cache is treated
    as absent rather than fatal: the merge is still correct without it.
    """
    cached = round_dir / "probes.json"
    if not cached.exists():
        return []
    try:
        data = json.loads(cached.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="merge",
        description="Bucket a round's generalist samples into the per-dimension files "
                    "the gate reads. Deterministic; the durable swarm's assembly step.")
    parser.add_argument("run_dir", help="the round directory (…/round-N)")
    parser.add_argument("--json", action="store_true", help="emit the counts as JSON")
    args = parser.parse_args(argv)

    round_dir = Path(args.run_dir).expanduser()
    if not round_dir.is_dir():
        print(f"merge: not a directory: {round_dir}", file=sys.stderr)
        return 2

    paths = sample_paths(round_dir)
    if not paths:
        print(f"merge: no generalist-*.json in {round_dir} — nothing to assemble. "
              f"The round has not run, or its samples were not written.",
              file=sys.stderr)
        return 2

    loop = _loop()
    counts = loop.merge_generalist_samples(paths, round_dir, read_probes(round_dir))

    if args.json:
        print(json.dumps(counts, indent=2))
        return 0

    print(f"merged {counts['samples']} sample(s) from {len(paths)} file(s)")
    for dim in ("security", "correctness", "readability", "architecture",
                "performance"):
        if (round_dir / f"{dim}.json").exists():
            print(f"  {dim:14s} {counts.get(dim, 0)} finding(s)")
    if counts.get("dropped"):
        print(f"  {counts['dropped']} finding(s) dropped: no usable `dimension` field")
    if counts["samples"] == 0:
        # No dimension files are written, so a total reviewer failure cannot score as a
        # clean 100. Say so rather than printing an empty merge that reads like success.
        print("merge: no sample was readable — no dimension files written, so the "
              "gate will report the round as an error (exit 2).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    # Not a program: reached through `council <verb>`. See council.py.
    from council import require_dispatch

    require_dispatch("merge")
    raise SystemExit(main())
