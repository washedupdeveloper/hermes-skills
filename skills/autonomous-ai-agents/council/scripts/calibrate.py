"""Fit the framework's free parameters (d*, k, alpha, beta) from measured baselines.

    council calibrate --good <dir> --bad <dir> [--out calibration.json]
    council calibrate --build-eval <dir> --base <dir>

See docs/CALIBRATION.md.
"""
from __future__ import annotations

import argparse
import importlib.util as _shared_util
import json
import os
import random
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# `_shared` by path, like every sibling here -- see its own docstring for why a
# plain import would not be safe.
_SHARED_SPEC = _shared_util.spec_from_file_location(
    "_shared", Path(__file__).resolve().parent / "_shared.py")
assert _SHARED_SPEC is not None and _SHARED_SPEC.loader is not None, "_shared.py"
_shared = _shared_util.module_from_spec(_SHARED_SPEC)
_SHARED_SPEC.loader.exec_module(_shared)

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
PROBES = HERE / "probes.py"

# Below this a density is indistinguishable from zero, and d* there makes the Hill
# curve a step function at x=0.
DENSITY_FLOOR = 0.05   # findings per KLOC

SOURCE_SUFFIXES = _shared.SOURCE_SUFFIXES


# --- measuring --------------------------------------------------------------

def kloc(root: Path) -> float:
    """Thousands of source lines — the denominator for findings density.

    The 0.001 floor is this caller's: a density must be defined even for an empty
    rung of the ladder. The scorer does NOT floor -- see _shared.kloc.
    """
    return _shared.kloc(root, floor=0.001)


def run_probes(root: Path, timeout: int = 900) -> List[Dict[str, Any]]:
    """Run every probe against *root* and return their raw JSON objects.

    Two things this gets right that a naive subprocess call does not:

    * `REVIEW_COUNCIL_DISPATCHED` is set explicitly. `probes.py` refuses a bare
      invocation and prints usage instead of JSON, so without it a calibration called
      as a LIBRARY (not through `council calibrate`) silently measured nothing.
    * A non-JSON answer RAISES rather than returning `[]`. An empty list reads as
      "no probes", which `choose_threshold` then reports as "no labels" — a much less
      useful error than "the probes did not run, here is what they said".
    """
    environment = dict(os.environ)
    environment["REVIEW_COUNCIL_DISPATCHED"] = "1"
    proc = subprocess.run(
        [sys.executable, str(PROBES), "--all", "--repo", str(root)],
        capture_output=True, text=True, timeout=timeout, env=environment,
    )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
        raise RuntimeError(
            f"probes did not return JSON for {root} (exit {proc.returncode}): "
            + " | ".join(tail)) from exc


def probe_density(results: List[Dict[str, Any]], root: Path) -> Dict[str, float]:
    """Findings per KLOC, per probe that actually ran.

    A probe that did not run contributes NO key, rather than 0.0 — treating an
    unrun analyzer as "clean" is the failure mode that makes a missing tool look
    like a passing grade.
    """
    size = kloc(root)
    out: Dict[str, float] = {}
    for r in results:
        if not r.get("ran"):
            continue
        out[r["tool"]] = len(r.get("findings") or []) / size
    return out


# --- seeding defects (for building a graded eval ladder) ---------------------

def _seed_secret(rng: random.Random) -> str:
    body = "".join(rng.choice("0123456789abcdef") for _ in range(32))
    return f'API_KEY = "sk_live_{body}"\n'


def _seed_syntax(rng: random.Random) -> str:
    return "def broken_%d(:\n    return 1\n" % rng.randint(1000, 9999)


def _seed_complexity(rng: random.Random) -> str:
    name = f"tangled_{rng.randint(1000, 9999)}"
    lines = [f"def {name}(x):"]
    lines += [f"    if x == {i}:\n        x += {i}" for i in range(20)]
    lines.append("    return x")
    return "\n".join(lines) + "\n"


def _seed_nix_lint(rng: random.Random) -> str:
    name = f"stale_{rng.randint(1000, 9999)}"
    return (
        f"{{ pkgs ? import <nixpkgs> {{}} }}:\n"
        f"let\n"
        f"  unusedBinding = pkgs.hello;\n"
        f"  {name} = x: y: x;\n"
        f"in\n"
        f"if pkgs.hello != null then pkgs.hello else pkgs.hello\n"
    )


SEEDERS = {
    "secret": (_seed_secret, ".py"),
    "syntax": (_seed_syntax, ".py"),
    "complexity": (_seed_complexity, ".py"),
    "nix-lint": (_seed_nix_lint, ".nix"),
}


def seed_defects(root: Path, count: int, rng: random.Random,
                 kinds: Optional[List[str]] = None) -> List[str]:
    """Write *count* defective files into *root*. Deterministic for a given rng."""
    kinds = kinds or list(SEEDERS)
    src = root / "src"
    src.mkdir(parents=True, exist_ok=True)
    written: List[str] = []
    for i in range(count):
        kind = kinds[i % len(kinds)]
        maker, suffix = SEEDERS[kind]
        path = src / f"seeded_{kind}_{i}{suffix}"
        # newline="\n" so the corpus is byte-identical everywhere: write_text emits
        # CRLF on Windows, and the probes would then measure a different corpus.
        path.write_text(maker(rng), encoding="utf-8", newline="\n")
        written.append(str(path.relative_to(root)))
    return written


def build_eval_ladder(base: Path, dest: Path, levels: Tuple[int, ...],
                      seed: int = 20261006) -> List[Dict[str, Any]]:
    """Materialise *base* at several defect levels, as a labeled eval set.

    Level 0 is the known-good control — the base copied untouched. Each higher
    level seeds a known number of defects, so the ground truth is known by
    construction rather than by inspection.
    """
    dest.mkdir(parents=True, exist_ok=True)
    manifest: List[Dict[str, Any]] = []
    for level in levels:
        target = dest / f"level-{level}"
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(
            base, target,
            ignore=shutil.ignore_patterns(".git", ".review-council", "__pycache__",
                                          "result", "result-*", "node_modules"),
        )
        rng = random.Random(seed + level)
        written = seed_defects(target, level, rng) if level else []
        manifest.append({
            "level": level,
            "path": str(target),
            "label": "good" if level == 0 else "bad",
            "defects_seeded": level,
            "files": written,
        })
    return manifest


# --- calibrating ------------------------------------------------------------

def derive_d_star(good: Dict[str, float], bad: Dict[str, float]) -> Dict[str, Dict[str, Any]]:
    """d* per tool = the density seen on the known-good baseline (§7 step 2).

    With `raw = d*` the Hill curve returns 50 by construction, so a tool sitting
    at known-good density lands mid-scale and known-bad lands below it.
    """
    out: Dict[str, Dict[str, Any]] = {}
    for tool in sorted(set(good) | set(bad)):
        g = good.get(tool)
        b = bad.get(tool)
        if g is None:
            continue
        out[tool] = {
            "d_star": round(max(g, DENSITY_FLOOR), 4),
            "good_density": round(g, 4),
            "bad_density": round(b, 4) if b is not None else None,
            "floored": g < DENSITY_FLOOR,
        }
    return out


def hill(density: float, d_star: float, k: float = 1.2) -> float:
    """100 / (1 + (raw/d*)^k) — the §7 formula, with the calibrated d*."""
    if density <= 0:
        return 100.0
    return 100.0 / (1.0 + (density / max(d_star, 1e-9)) ** k)


def score_from_densities(dens: Dict[str, float],
                         d_star: Dict[str, Dict[str, float]],
                         k: float = 1.2) -> Optional[float]:
    """Geometric mean of per-tool Hill scores. None when nothing ran."""
    scores = [hill(d, d_star[t]["d_star"], k) for t, d in dens.items() if t in d_star]
    if not scores:
        return None
    product = 1.0
    for s in scores:
        product *= max(s, 1e-6)
    return product ** (1.0 / len(scores))


def sweep_threshold(points: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Precision / recall / F1 / Youden's J at every candidate threshold.

    "bad" is the positive class: the calibration question is "does this
    threshold catch defective code without crying wolf on clean code".
    """
    scored = [p for p in points if p.get("score") is not None]
    if not scored:
        return []
    n_bad = sum(1 for p in scored if p["label"] == "bad")
    n_good = sum(1 for p in scored if p["label"] == "good")
    if not n_bad or not n_good:
        return []

    candidates = sorted({round(p["score"], 3) for p in scored})
    rows: List[Dict[str, Any]] = []
    for t in candidates:
        tp = sum(1 for p in scored if p["score"] < t and p["label"] == "bad")
        fp = sum(1 for p in scored if p["score"] < t and p["label"] == "good")
        fn = n_bad - tp
        tn = n_good - fp
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / n_bad if n_bad else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
        j = (recall + (tn / n_good) - 1.0) if n_good else 0.0   # Youden's J
        rows.append({
            "threshold": t, "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": round(precision, 4), "recall": round(recall, 4),
            "f1": round(f1, 4), "youden_j": round(j, 4),
        })
    return rows


def choose_threshold(points: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The max-margin threshold separating good from bad, derived from LABELS.

    For a 1-D threshold classifier the perfectly-separating interval is
    `(best_bad, worst_good]` — every threshold in it classifies every labelled
    point correctly. The midpoint maximizes the margin to both classes, which is
    what generalises to unseen repos.

    This deliberately does NOT read the plateau off `sweep_threshold`: that
    sweep only evaluates thresholds AT observed scores, so it cannot see the
    interior of the gap at all. Reading it that way makes the plateau an
    artifact of how a candidate happened to round (a score of 79.8399 becomes a
    candidate 79.84 and thereby appears on the "bad" side of itself), and
    collapses to a single point whenever no observed score lands in the gap.
    """
    scored = [p for p in points if p.get("score") is not None]
    bad = [p["score"] for p in scored if p.get("label") == "bad"]
    good = [p["score"] for p in scored if p.get("label") == "good"]
    if not bad or not good:
        return None

    best_bad = max(bad)
    worst_good = min(good)
    n_bad, n_good = len(bad), len(good)

    if best_bad >= worst_good:
        # Classes overlap: report the minimum-misclassification point, not a clean cut.
        candidates = sorted(set(bad + good))
        def errors(t: float) -> Tuple[int, int]:
            return (sum(1 for s in bad if s >= t), sum(1 for s in good if s < t))
        best = min(candidates, key=lambda t: sum(errors(t)))
        tp = sum(1 for s in bad if s < best)
        fp = sum(1 for s in good if s < best)
        return {
            "threshold": round(best, 4), "tp": tp, "fp": fp,
            "fn": n_bad - tp, "tn": n_good - fp,
            "precision": round(tp / (tp + fp), 4) if (tp + fp) else 0.0,
            "recall": round(tp / n_bad, 4),
            "f1": 0.0, "youden_j": 0.0,
            "separable": False,
            "note": "classes overlap; this threshold minimizes misclassification",
        }

    midpoint = round((best_bad + worst_good) / 2.0, 4)
    tp, fp = n_bad, 0          # perfect separation by construction
    return {
        "threshold": midpoint, "tp": tp, "fp": fp, "fn": 0, "tn": n_good,
        "precision": 1.0, "recall": 1.0, "f1": 1.0, "youden_j": 1.0,
        "separable": True,
        "plateau": [round(best_bad, 4), round(worst_good, 4)],
        "margin": round((worst_good - best_bad) / 2.0, 4),
    }


def recalibrate(measured: List[Dict[str, Any]], k: float = 1.2) -> Dict[str, Any]:
    """Re-derive d*, the sweep and the threshold from ALREADY-measured points.

    Measurement is the expensive half (every probe against every rung), so it is
    separated from the arithmetic: k, the tie-break rule or the score model can
    be re-tuned without re-running the toolchain.
    """
    clean = [m for m in measured if m.get("label") == "good"]
    dirty = [m for m in measured if m.get("label") != "good"]

    good_union: Dict[str, float] = {}
    for m in clean:
        for tool, d in (m.get("density") or {}).items():
            good_union[tool] = max(good_union.get(tool, 0.0), d)
    bad_union: Dict[str, float] = {}
    for m in dirty:
        for tool, d in (m.get("density") or {}).items():
            bad_union[tool] = max(bad_union.get(tool, 0.0), d)

    d_star = derive_d_star(good_union, bad_union)
    points = [{
        "label": m.get("label"), "level": m.get("level"), "path": m.get("path"),
        "defects": m.get("defects_seeded"), "kloc": m.get("kloc"),
        "score": score_from_densities(m.get("density") or {}, d_star, k),
    } for m in measured]

    sweep = sweep_threshold(points)
    return {
        "method": "research/deterministic-quality-tooling.md §7",
        "halflife_k": k,
        "d_star": d_star,
        "points": points,
        # Kept so the output is itself re-tunable: measurement is the expensive half.
        "measured": measured,
        "sweep": sweep,
        "recommended_threshold": choose_threshold(points),
    }


def calibrate(good: Path, bad: Path, seed: int = 20261006) -> Dict[str, Any]:
    """Full §7 calibration from a known-good and a known-bad baseline."""
    good_dens = probe_density(run_probes(good), good)
    bad_dens = probe_density(run_probes(bad), bad)
    d_star = derive_d_star(good_dens, bad_dens)

    good_score = score_from_densities(good_dens, d_star)
    bad_score = score_from_densities(bad_dens, d_star)

    # Annotated: `defects` is 0 in one entry and None in the other, so an unannotated
    # literal infers a type narrower than sweep_threshold accepts.
    points: List[Dict[str, Any]] = [
        {"label": "good", "path": str(good), "defects": 0, "score": good_score,
         "kloc": round(kloc(good), 4)},
        {"label": "bad", "path": str(bad), "defects": None, "score": bad_score,
         "kloc": round(kloc(bad), 4)},
    ]
    return {
        "method": "research/deterministic-quality-tooling.md §7",
        "seed": seed,
        "baselines": {"good": str(good), "bad": str(bad)},
        "halflife_k": 1.2,
        "d_star": d_star,
        "measured": {"good_score": good_score, "bad_score": bad_score},
        "points": points,
        "sweep": sweep_threshold(points),
        "recommended_threshold": choose_threshold(points),
    }


def calibrate_many(good: List[Path], bad: Path, seed: int = 20261006) -> Dict[str, Any]:
    """§7 calibration against SEVERAL known-good baselines.

    One known-good repo makes the threshold's upper edge that repo's own score, so a
    second clean repo that is merely less tidy fails the gate. Each good repo
    contributes its **own** labelled point, so the threshold has to clear all of them.

    `d*` is anchored on the **worst** density seen per tool across the good set, not the
    best. `d*` is the density at which a tool scores 50, so anchoring on the tidiest
    repo would mark every other clean repo as failing — the opposite of what a
    known-good baseline is for. A tool absent from one repo contributes nothing, so a
    repo that simply does not use a tool cannot raise its floor for the others.
    """
    if not good:
        raise ValueError("calibrate_many needs at least one known-good baseline")

    good_dens: List[Tuple[Path, Dict[str, float]]] = [
        (path, probe_density(run_probes(path), path)) for path in good
    ]
    worst: Dict[str, float] = {}
    for _path, dens in good_dens:
        for tool, value in dens.items():
            worst[tool] = max(worst.get(tool, 0.0), value)

    bad_dens = probe_density(run_probes(bad), bad)
    d_star = derive_d_star(worst, bad_dens)

    points: List[Dict[str, Any]] = []
    good_scores: List[Dict[str, Any]] = []
    for path, dens in good_dens:
        score = score_from_densities(dens, d_star)
        points.append({"label": "good", "path": str(path), "defects": 0,
                       "score": score, "kloc": round(kloc(path), 4)})
        good_scores.append({"path": str(path), "score": score})

    bad_score = score_from_densities(bad_dens, d_star)
    points.append({"label": "bad", "path": str(bad), "defects": None,
                   "score": bad_score, "kloc": round(kloc(bad), 4)})

    return {
        "method": "research/deterministic-quality-tooling.md §7",
        "seed": seed,
        "baselines": {"good": [str(p) for p in good], "bad": str(bad)},
        "halflife_k": 1.2,
        "d_star": d_star,
        "measured": {"good_scores": good_scores, "bad_score": bad_score},
        "points": points,
        "sweep": sweep_threshold(points),
        "recommended_threshold": choose_threshold(points),
    }


def calibrate_ladder(ladder: List[Dict[str, Any]], k: float = 1.2) -> Dict[str, Any]:
    """Calibrate against a graded eval ladder (defect levels 0..N).

    Richer than a two-point scan: the sweep gets a real spread of scores, so the
    recommended threshold is chosen from a curve rather than from the midpoint
    between two numbers.
    """
    measured: List[Dict[str, Any]] = []
    clean_densities: List[Dict[str, float]] = []
    dirty_densities: List[Dict[str, float]] = []

    for entry in ladder:
        root = Path(entry["path"])
        dens = probe_density(run_probes(root), root)
        if entry["level"] == 0:
            clean_densities.append(dens)
        else:
            dirty_densities.append(dens)
        measured.append({**entry, "density": dens, "kloc": round(kloc(root), 4)})

    # d* from the WORST density seen on clean code, per tool: set too low, it flags
    # healthy code.
    good_union: Dict[str, float] = {}
    for dens in clean_densities:
        for tool, d in dens.items():
            good_union[tool] = max(good_union.get(tool, 0.0), d)
    bad_union: Dict[str, float] = {}
    for dens in dirty_densities:
        for tool, d in dens.items():
            bad_union[tool] = max(bad_union.get(tool, 0.0), d)

    d_star = derive_d_star(good_union, bad_union)

    points: List[Dict[str, Any]] = []
    for m in measured:
        points.append({
            "label": m["label"],
            "level": m["level"],
            "path": m["path"],
            "defects": m["defects_seeded"],
            "kloc": m["kloc"],
            "score": score_from_densities(m["density"], d_star, k),
        })

    sweep = sweep_threshold(points)
    return {
        "method": "research/deterministic-quality-tooling.md §7",
        "halflife_k": k,
        "d_star": d_star,
        "points": points,
        # Raw per-rung measurements, so recalibrate() can re-tune k without re-probing.
        "measured": measured,
        "sweep": sweep,
        "recommended_threshold": choose_threshold(points),
    }


# --- CLI --------------------------------------------------------------------

def _read_manifest(path: str) -> Optional[Dict[str, Any]]:
    """Read a manifest this verb wrote earlier.

    `--ladder` and `--recalibrate` both consume a file `calibrate` produced, so a
    missing or malformed one names the flag that makes it instead of raising a
    bare traceback at the user.
    """
    p = Path(path)
    if not p.is_file():
        print(f"calibrate: no such manifest: {p}", file=sys.stderr)
        return None
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"calibrate: {p} is not valid JSON: {exc}", file=sys.stderr)
        return None
    if not isinstance(doc, dict):
        print(f"calibrate: {p} is not a manifest object", file=sys.stderr)
        return None
    return doc


def _scorer() -> Any:
    """The gate's own scorer, loaded by path like every sibling module.

    Loaded lazily so `calibrate --build-eval` does not pay for importing the scorer.
    """
    spec = _shared_util.spec_from_file_location("score_reviews", HERE / "score_reviews.py")
    if spec is None or spec.loader is None:
        raise ImportError("score_reviews.py")
    module = _shared_util.module_from_spec(spec)
    sys.modules["score_reviews"] = module
    spec.loader.exec_module(module)
    return module


def profile_of(round_dir: Path, threshold: float) -> Dict[str, float]:
    """The per-dimension scores the gate produces for a round directory."""
    scorer = _scorer()
    result = scorer.evaluate(round_dir, threshold)
    return {d["dimension"]: float(d["score"]) for d in result["per_dimension"]}


def weight_sensitivity(scores: Dict[str, float], threshold: float,
                       weights: Optional[Dict[str, float]] = None,
                       max_factor: float = 3.0) -> Dict[str, Any]:
    """How far the aggregate moves when one aggregate weight does.

    M8 records `alpha_t` as uncalibrated, with the rule "reweight only with evidence".
    This measures the leverage before anyone goes looking for that evidence: for each
    dimension, sweep its weight from 0 to `max_factor` x its shipped value, scale the
    others so the weights still sum to 1, and recompute the aggregate with the gate's
    own `renormalized_aggregate`.

    The ceiling on any weight effect is the SPREAD across dimension scores — a weighted
    mean of equal values cannot move at all — so that is reported beside the sweep. If
    no single weight change flips a verdict, `alpha_t` is not load-bearing on this
    input, and calibrating it would buy nothing there.
    """
    scorer = _scorer()
    weights = dict(weights or scorer.WEIGHTS)
    present = {d: weights[d] for d in scores if d in weights}
    pairs = [{"dimension": d, "score": s} for d, s in scores.items() if d in weights]
    base = scorer.renormalized_aggregate(present, pairs)

    def at(dim: str, factor: float) -> float:
        target = weights[dim] * factor
        others = {d: w for d, w in weights.items() if d != dim}
        total = sum(others.values()) or 1.0
        remaining = max(1.0 - target, 0.0)
        swept = {d: (w / total) * remaining for d, w in others.items()}
        swept[dim] = target
        return scorer.renormalized_aggregate(
            {d: swept[d] for d in scores if d in swept},
            [{"dimension": d, "score": s} for d, s in scores.items() if d in swept])

    rows: List[Dict[str, Any]] = []
    for dim in weights:
        if dim not in scores:
            continue
        lo, hi = at(dim, 0.0), at(dim, max_factor)
        rows.append({
            "dimension": dim,
            "weight": round(weights[dim], 4),
            "aggregate_at_0": round(lo, 4),
            "aggregate_at_max": round(hi, 4),
            "range": round(abs(hi - lo), 4),
            "flips_verdict": (lo >= threshold) != (hi >= threshold),
        })

    return {
        "threshold": round(threshold, 4),
        "weights": {d: round(w, 4) for d, w in weights.items()},
        "aggregate": round(base, 4),
        "verdict": "satisfied" if base >= threshold else "not_satisfied",
        "spread_across_dimensions": round(
            max(scores.values()) - min(scores.values()), 4) if scores else 0.0,
        "margin_to_threshold": round(base - threshold, 4),
        "max_single_weight_move": round(max((r["range"] for r in rows), default=0.0), 4),
        "any_verdict_flips": any(r["flips_verdict"] for r in rows),
        "per_dimension": rows,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="calibrate.py",
        description="Calibrate d*, k and the pass threshold from labelled baselines (M8).",
    )
    parser.add_argument("--good", action="append",
                        help="Known-good revision to baseline-scan (repeatable: each "
                             "adds a labelled point, and d* anchors on the worst "
                             "density seen across all of them)")
    parser.add_argument("--bad", help="Known-bad revision to baseline-scan")
    parser.add_argument("--build-eval", metavar="DEST",
                        help="Build a graded eval ladder at DEST from --base")
    parser.add_argument("--ladder", metavar="MANIFEST",
                        help="Calibrate against a ladder manifest from --build-eval")
    parser.add_argument("--recalibrate", metavar="MANIFEST",
                        help="Re-derive d*, the sweep and the threshold from a "
                             "calibration manifest's own measured points, without "
                             "re-running the probes")
    parser.add_argument("--base", help="Base repo the ladder is copied from")
    parser.add_argument("--levels", default="0,1,2,4,8,16",
                        help="Defect counts per rung (default 0,1,2,4,8,16)")
    parser.add_argument("--seed", type=int, default=20261006)
    parser.add_argument("--k", type=float, default=1.2, help="Hill steepness")
    parser.add_argument("--out", default=None, help="Write the manifest here")
    parser.add_argument("--sensitivity", metavar="ROUND_DIR",
                        help="Measure how far the aggregate moves when one alpha_t "
                             "weight does, for the round directory given")
    args = parser.parse_args(argv)

    if args.sensitivity:
        round_dir = Path(args.sensitivity).expanduser().resolve()
        if not round_dir.is_dir():
            print(f"calibrate: not a directory: {round_dir}", file=sys.stderr)
            return 2
        scorer = _scorer()
        threshold = scorer.calibrated_threshold()
        scores = profile_of(round_dir, threshold)
        if not scores:
            print(f"calibrate: {round_dir} holds no <dimension>.json reviewer files",
                  file=sys.stderr)
            return 2
        result = {"round": str(round_dir), **weight_sensitivity(scores, threshold)}
    elif args.build_eval:
        if not args.base:
            print("calibrate: --build-eval needs --base", file=sys.stderr)
            return 2
        levels = tuple(int(x) for x in args.levels.split(","))
        ladder = build_eval_ladder(Path(args.base), Path(args.build_eval), levels, args.seed)
        result = {"ladder": ladder}
    elif args.ladder or args.recalibrate:
        source = args.ladder or args.recalibrate
        doc = _read_manifest(source)
        if doc is None:
            return 2
        want = "ladder" if args.ladder else "measured"
        if want not in doc:
            print(
                f"calibrate: {source} has no {want!r} — "
                + ("make it with --build-eval" if want == "ladder"
                   else "it must be a calibration manifest, not a ladder"),
                file=sys.stderr,
            )
            return 2
        result = (
            calibrate_ladder(doc["ladder"], args.k)
            if args.ladder
            else recalibrate(doc["measured"], args.k)
        )
    elif args.good and args.bad:
        result = (
            calibrate_many([Path(p) for p in args.good], Path(args.bad), args.seed)
            if len(args.good) > 1
            else calibrate(Path(args.good[0]), Path(args.bad), args.seed)
        )
    else:
        parser.print_help()
        return 2

    text = json.dumps(result, indent=2, ensure_ascii=False)
    if args.out:
        # newline="\n": write_text translates to os.linesep, so on Windows the same
        # calibration produced different bytes. This manifest is a determinism anchor.
        Path(args.out).write_text(text + "\n", encoding="utf-8", newline="\n")
        print(f"calibration written to {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    # Not a program: reached through `council <verb>`. See council.py.
    from council import require_dispatch

    require_dispatch("calibrate")
    sys.exit(main())
