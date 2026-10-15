#!/usr/bin/env python3
"""Replay fixed inputs through the real scoring pipeline and diff pinned values.

    council golden --check     # exit 1 on drift
    council golden --update    # re-pin, deliberately

No model, no network, no toolchain: a difference is a regression in this
repository, never noise.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
GOLDEN = REPO / "tests" / "golden"
EXPECT = GOLDEN / "expect.json"
TARGET = GOLDEN / "target"

# All pinned arithmetic is deterministic float work on the same inputs, so an
# exact match is the honest tolerance. It is not 0 because summation order in the
# aggregate is an implementation detail we do not want to freeze.
TOLERANCE = 1e-6


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    # `spec_from_file_location` returns None only when it cannot classify the path
    # as a loadable source module, and `loader` is None for a non-source spec. Both
    # mean a broken checkout rather than a condition worth tolerating at runtime, so
    # state it as a precondition and let the assertion name the file.
    assert spec is not None and spec.loader is not None, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Cached so the modules are loaded ONCE per process. That matters beyond speed:
# tests/test_golden.py proves this suite detects a deliberate regression by
# mutating a weight table, and a mutation only reaches compute() if compute() and
# the test are looking at the same module object.
_SCORER = None
_LOOP = None


def _scorer():
    global _SCORER
    if _SCORER is None:
        _SCORER = _load("score_reviews", HERE / "score_reviews.py")
    return _SCORER


def _loop():
    global _LOOP
    if _LOOP is None:
        _LOOP = _load("council_loop", HERE / "council_loop.py")
    return _LOOP


# --- input hashing ----------------------------------------------------------

def hash_inputs() -> Dict[str, str]:
    """sha256 of every fixture input, so a fixture edit is visible as such.

    Without this, changing a fixture and re-pinning is indistinguishable in a diff
    from a scoring regression that was "fixed" by re-pinning.
    """
    out: Dict[str, str] = {}
    for path in sorted(GOLDEN.rglob("*")):
        if not path.is_file() or path.name == EXPECT.name:
            continue
        # Bytecode caches are not fixture INPUTS. They appear only because a test
        # imported a module inside the fixture tree, and hashing one made this suite
        # non-deterministic: the first run created `__pycache__/tool.cpython-3*.pyc`,
        # the next `--update` pinned it, and from then on `--check` failed on a tree
        # nobody had edited — while `--update`, whose whole contract is to be inert
        # when nothing changed, silently rewrote a tracked fixture.
        if "__pycache__" in path.parts or path.suffix in (".pyc", ".pyo"):
            continue
        rel = path.relative_to(GOLDEN).as_posix()
        out[rel] = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    return out


# --- the two layers ---------------------------------------------------------

def _round_result(name: str, scorer) -> Dict[str, Any]:
    run_dir = GOLDEN / "rounds" / name
    result = scorer.evaluate(run_dir, scorer.calibrated_threshold(), repo=TARGET)
    per_dim = {
        entry["dimension"]: {
            "llm": round(entry["llm"], 6),
            "det": round(entry["det"], 6),
            "beta": round(entry["beta"], 6),
            "score": round(entry["score"], 6),
        }
        for entry in result.get("per_dimension") or []
    }
    return {
        "status": result.get("status"),
        "aggregate": round(float(result.get("aggregate") or 0.0), 6),
        "blocking": len(result.get("blocking") or []),
        "stacks": list(result.get("stacks") or []),
        "size_kloc": round(float(result.get("size_kloc") or 0.0), 6),
        "per_dimension": per_dim,
    }


def _merge_result(name: str, loop, scorer) -> Dict[str, Any]:
    src = GOLDEN / "merges" / name
    samples = sorted(p for p in src.glob("*.json") if p.name != "probes.json")
    probes = json.loads((src / "probes.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        counts = loop.merge_generalist_samples(samples, out, probes)
        # A dimension absent from the merge is recorded as None, so the value type
        # has to admit it — that is the whole point of the mapping.
        merged: Dict[str, Any] = {}
        for dim in scorer.WEIGHTS:
            path = out / f"{dim}.json"
            if not path.exists():
                merged[dim] = None
                continue
            review = json.loads(path.read_text(encoding="utf-8"))
            _det, beta, _missing = scorer.deterministic_score(
                review, dim, stacks=["nix"])
            merged[dim] = {
                "findings": len(review.get("findings") or []),
                "score": round(float(review.get("score") or 0.0), 6),
                "beta": round(beta, 6),
                "tools_run": sorted(
                    str(t.get("cmd") or t.get("tool") or "") for t in
                    (review.get("tools_run") or [])),
            }
    return {
        "samples": counts.get("samples"),
        "dropped": counts.get("dropped"),
        "per_dimension": merged,
    }


def compute() -> Dict[str, Any]:
    """Recompute the whole pinned payload from the fixtures."""
    scorer = _scorer()
    loop = _loop()
    rounds = {name: _round_result(name, scorer)
              for name in sorted(p.name for p in (GOLDEN / "rounds").iterdir()
                                 if p.is_dir())}
    merges = {name: _merge_result(name, loop, scorer)
              for name in sorted(p.name for p in (GOLDEN / "merges").iterdir()
                                 if p.is_dir())}
    return {
        "note": ("Pinned by scripts/golden.py. Every number here is recomputed from "
                 "tests/golden/ by `--check`. Do not edit by hand: run `--update`, "
                 "read the diff, and say why in the commit."),
        "threshold": round(scorer.calibrated_threshold(), 6),
        "tolerance": TOLERANCE,
        "inputs": hash_inputs(),
        "rounds": rounds,
        "merges": merges,
    }


# --- comparison -------------------------------------------------------------

def _diff(expected: Any, actual: Any, path: str = "") -> List[str]:
    """Every difference, as readable lines. Recursive so a nested change names
    its own path rather than dumping two whole blobs."""
    out: List[str] = []
    if isinstance(expected, dict) and isinstance(actual, dict):
        for key in sorted(set(expected) | set(actual)):
            if key not in actual:
                out.append(f"  - {path}{key}: MISSING (expected {expected[key]!r})")
            elif key not in expected:
                out.append(f"  + {path}{key}: NEW ({actual[key]!r})")
            else:
                out += _diff(expected[key], actual[key], f"{path}{key}.")
        return out
    if isinstance(expected, list) and isinstance(actual, list):
        if expected != actual:
            out.append(f"  ~ {path[:-1]}: {expected!r} -> {actual!r}")
        return out
    if isinstance(expected, float) and isinstance(actual, float):
        if abs(expected - actual) > TOLERANCE:
            out.append(f"  ~ {path[:-1]}: {expected} -> {actual} "
                       f"(delta {actual - expected:+.6f})")
        return out
    if expected != actual:
        out.append(f"  ~ {path[:-1]}: {expected!r} -> {actual!r}")
    return out


def check(quiet: bool = False) -> int:
    if not EXPECT.exists():
        print(f"golden: {EXPECT} is missing — run `golden.py --update` once")
        return 2
    expected = json.loads(EXPECT.read_text(encoding="utf-8"))
    actual = compute()
    differences = _diff(expected, actual)
    if not differences:
        if not quiet:
            rounds = actual["rounds"]
            print(f"golden: {len(rounds)} round(s) and {len(actual['merges'])} merge(s) "
                  f"reproduce exactly")
            for name, payload in rounds.items():
                print(f"  {name:9s} aggregate={payload['aggregate']:8.4f} "
                      f"status={payload['status']} blocking={payload['blocking']}")
                for dim, d in sorted(payload["per_dimension"].items()):
                    print(f"    {dim:14s} llm={d['llm']:7.2f} det={d['det']:7.2f} "
                          f"beta={d['beta']:.3f} score={d['score']:7.2f}")
        return 0
    print("golden: REGRESSION — the scoring pipeline no longer reproduces:")
    for line in differences:
        print(line)
    print("\nIf the change is intended, re-pin with `golden.py --update` and say why "
          "in the commit message. If it is not, you have just found the bug this "
          "suite exists for.")
    return 1


def update() -> int:
    actual = compute()
    previous = None
    if EXPECT.exists():
        try:
            previous = json.loads(EXPECT.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            previous = None
    differences = _diff(previous, actual) if previous else []
    if previous and not differences:
        print("golden: nothing changed — refusing to rewrite expect.json")
        return 0
    EXPECT.write_text(json.dumps(actual, indent=2, sort_keys=True) + "\n",
                      encoding="utf-8", newline="\n")
    if previous:
        print("golden: re-pinned. Changes:")
        for line in differences:
            print(line)
    else:
        print(f"golden: wrote {EXPECT.relative_to(REPO)} "
              f"({len(actual['rounds'])} round(s), {len(actual['merges'])} merge(s))")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="golden",
        description="Golden end-to-end regression suite: replay fixed inputs through "
                    "the real scoring pipeline and diff against pinned values.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true",
                       help="recompute and compare (exit 1 on drift)")
    group.add_argument("--update", action="store_true",
                       help="re-pin expect.json, printing every change")
    parser.add_argument("--quiet", action="store_true", help="print nothing on success")
    args = parser.parse_args(argv)
    return update() if args.update else check(quiet=args.quiet)


if __name__ == "__main__":
    # Not a program: reached through `council <verb>`. See council.py.
    from council import require_dispatch

    require_dispatch("golden")
    raise SystemExit(main())
