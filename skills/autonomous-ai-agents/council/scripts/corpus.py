"""The labelled corpus a claims-scale threshold needs, and the coverage it has to record.

A corpus here is a set of *adjudicated run directories with known ground truth*. The generator
already exists — `calibrate.build_eval_ladder` materialises a base repo at increasing seeded-defect
levels, ground truth by construction — but it has only ever been fed to `probes.py`. Claims scoring
moves only when the reviewer finds a defect *and* proves it, so the ladder has to be reviewed too,
and every rung has to record whether the reviewer actually found what was seeded.

    council calibrate --plan-corpus <dir> --base <repo> [--levels 0,1,4,16]
    council calibrate --collect-corpus <dir>/corpus.json --runs <dir>
    council calibrate --from-runs <dir>/corpus.json

`--plan-corpus` writes the ladder and the manifest; `--collect-corpus` fills in one entry per rung
that has a run. `--from-runs` then derives the threshold — or refuses.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
SCHEMA_VERSION = 1


def _module(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    assert spec is not None and spec.loader is not None, name
    module = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _seeded_locations(files: Any) -> List[Dict[str, Any]]:
    """Normalise whatever `inject_defects` wrote into [{path, line}] — the ground truth."""
    out: List[Dict[str, Any]] = []
    for entry in files or []:
        if isinstance(entry, str):
            out.append({"path": entry, "line": None})
            continue
        if not isinstance(entry, dict):
            continue
        path = entry.get("path") or entry.get("file") or entry.get("target")
        if not path:
            continue
        out.append({"path": str(path),
                    "line": entry.get("line") or entry.get("lineno"),
                    "kind": entry.get("kind") or entry.get("name")})
    return out


def plan(base: Path, dest: Path, levels=("0", "1", "2", "4", "8", "16"),
         seed: int = 20261006, in_place: bool = False, repeats: int = 1) -> Dict[str, Any]:
    """Materialise the ladder and write `corpus.json` describing every rung.

    *repeats* > 1 lays out one run directory per (rung, repeat) — `level-<N>-run-<k>` — because a
    single draw of a stochastic reviewer is a point, not a distribution. The tree is built once per
    rung and shared by its repeats: they must see identical input, or the variance measured would be
    the ladder's, not the reviewer's.
    """
    calibrate = _module("calibrate")
    numbers = tuple(int(level) for level in levels)
    ladder = calibrate.build_eval_ladder(Path(base), Path(dest), numbers, seed, in_place=in_place)
    rungs = []
    for rung in ladder:
        for repeat in range(1, max(1, repeats) + 1):
            rungs.append({
                "id": f"level-{rung['level']}-run-{repeat}" if repeats > 1 else f"level-{rung['level']}",
                "level": rung["level"],
                "repeat": repeat,
                "label": rung["label"],
                "tree": rung["path"],
                "defects_seeded": rung.get("defects_seeded", 0),
                "seeded": _seeded_locations(rung.get("files")),
                "run": None,
                "score": None,
                "detected": None,
                "certification": None,
                "note": None,
            })
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "scale": "claims",
        "base": str(Path(base)),
        "seed": seed,
        # Recorded so a reader can tell a ladder that varies only defects from one that also
        # varies in size — the second cannot calibrate a score with a coverage term in it.
        "in_place": in_place,
        "repeats": max(1, repeats),
        "rungs": rungs,
    }
    write(Path(dest) / "corpus.json", manifest)
    return manifest


def run_dir_for(runs_root: Path, rung: Dict[str, Any]) -> Path:
    """Where this rung's run lives: its id, so repeats cannot collide."""
    return Path(runs_root) / str(rung.get("id") or f"level-{rung['level']}")


def _line_range(text: Any) -> Optional[Tuple[int, int]]:
    """`"4"` -> (4, 4), `"8-11"` -> (8, 11), anything unreadable -> None."""
    numbers = [int(n) for n in str(text or "").replace("-", " ").split() if n.isdigit()]
    if not numbers:
        return None
    return min(numbers), max(numbers)


def _seeded_with_spans(seeded: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Every seeded defect as a line RANGE, backfilling manifests that recorded only a start.

    The in-place seed writes a block: `def parse_payload_1(payload):` then `return eval(payload)`.
    Recording only the first line made a reviewer that cited the eval line at 20 look like it had
    missed a defect seeded at 19 — three passes in a row. The span comes from the same template
    that planted the text, so the record cannot drift from the tree.
    """
    out = []
    for defect in seeded:
        item = dict(defect)
        line = item.get("line")
        if line is not None and not item.get("line_end") and item.get("kind"):
            try:
                span = _module("calibrate").inserted_span(str(item["kind"]))
            except Exception:  # noqa: BLE001 - an unknown kind is not an error here
                span = 1
            item["line_end"] = int(line) + max(1, int(span)) - 1
        out.append(item)
    return out


def _match(seeded: List[Dict[str, Any]], confirmed: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Which seeded defects a confirmed claim points at — by path AND line overlap.

    Path alone is too generous to be called detection: a reviewer that reports an unrelated issue
    in the same file scored as having found the planted defect.

    Overlap, not containment: a seeded defect is a block of lines, and a reviewer citing the
    offending line inside it has found it. Requiring the claim to contain the block's FIRST line
    reported a real detection as a blind spot.
    """
    found = []
    for defect in _seeded_with_spans(seeded):
        want = str(defect.get("path") or "")
        line = defect.get("line")
        end = defect.get("line_end") or line
        hit = None
        why = "no confirmed claim at this path"
        for record in confirmed:
            location = record.get("location") or {}
            path = str(location.get("path") or "")
            if not (path and (path.endswith(want) or want.endswith(path))):
                continue
            if line is None:
                hit, why = record, "path only (the seed records no line)"
                break
            assert line is not None
            assert end is not None
            span = _line_range(location.get("line_range"))
            if span is None:
                why = "a claim names the file but no line"
                continue
            if int(line) <= span[1] and span[0] <= int(end):
                hit, why = record, "line"
                break
            why = f"the closest claim spans {span[0]}-{span[1]}, the defect {line}-{end}"
        found.append({"path": want, "line": line, "line_end": end, "matched": hit is not None,
                      "why": why, "id": (hit or {}).get("id"),
                      "state": (hit or {}).get("state")})
    return found


def _default_runner(rung: Dict[str, Any], runs_root: Path) -> Tuple[int, Path, str]:
    """Run one sample through the CLI and return (rc, artefact path, log text)."""
    import subprocess  # noqa: PLC0415 - only needed when actually sampling

    run_dir = run_dir_for(runs_root, rung)
    run_dir.mkdir(parents=True, exist_ok=True)
    log_path = Path(runs_root) / f"sample-{rung.get('id')}.log"
    argv = [sys.executable, str(HERE / "council.py"), "sample", str(rung["tree"]),
            "--index", "1", "--run-root", str(run_dir), "--scope", "whole-repo"]
    env = dict(os.environ, REVIEW_COUNCIL_DISPATCHED="1")
    try:
        completed = subprocess.run(argv, capture_output=True, text=True, timeout=1800,
                                   env=env)
        text = (completed.stdout or "") + (completed.stderr or "")
        rc = completed.returncode
    except subprocess.TimeoutExpired as exc:
        text = f"timed out after {exc.timeout}s"
        rc = 124
    log_path.write_text(text, encoding="utf-8", newline="\n")
    return rc, run_dir / "round-1" / "generalist-1.json", text


def _informative(round_dir: Path) -> Tuple[bool, str]:
    """Did this sample examine anything at all?

    A reviewer that ran no tool and reported no finding has said nothing about the tree. The gate
    cannot see the difference — it scores "nothing found" as 100.00 — so the corpus has to say it,
    or a blank sample becomes the best rung in the corpus.

    Reported findings count, not proven ones: a reviewer that raised five issues and proved none
    has examined the tree and failed to settle its claims. That is a different result, and one the
    proofs already report.
    """
    artefact = Path(round_dir) / "generalist-1.json"
    findings = 0
    tools = 0
    if artefact.exists():
        try:
            document = json.loads(artefact.read_text(encoding="utf-8-sig"))
            findings = len(document.get("findings") or [])
            tools = len(document.get("tools_run") or [])
        except (OSError, json.JSONDecodeError):
            findings = tools = 0
    # Deterministic probes are examination too: a round where ten of them ran has looked at the
    # tree even when the reviewer wrote nothing. Whether it looked at the RIGHT thing is the
    # coverage-gap question, which belongs to the gate and not here.
    probes_ran = 0
    probes = Path(round_dir) / "probes.json"
    if probes.exists():
        try:
            payload = json.loads(probes.read_text(encoding="utf-8-sig"))
            items = payload if isinstance(payload, list) else (payload.get("probes") or [])
            probes_ran = sum(1 for p in items if isinstance(p, dict) and p.get("ran"))
        except (OSError, json.JSONDecodeError):
            probes_ran = 0
    if findings or tools or probes_ran:
        return True, ""
    return False, ("uninformative: no tool ran, no probe ran and no finding was reported, so the "
                   "sample examined nothing")


def verdicts(manifest: Dict[str, Any]) -> Dict[str, Any]:
    """Did every clean rung certify, and every defective rung fail to?

    The reproducible question. Measured on twelve runs, the aggregate moved 10 points between
    identical passes, so a threshold inside that band decides by luck; the blocking set did not
    move at all. This reports the verdict each rung actually reached and whether the two classes
    are separated by it — which is the only thing a gate may claim.
    """
    rows = []
    for rung in manifest.get("rungs") or []:
        cert = rung.get("certification")
        label = str(rung.get("label") or "")
        expected = "certified" if label == "good" else "not certified"
        got = "certified" if cert == "certified" else ("not certified" if cert else "unrun")
        rows.append({"id": rung.get("id"), "level": rung.get("level"), "label": label,
                     "score": rung.get("score"), "certification": cert,
                     "expected": expected, "got": got, "ok": got == expected})
    wrong = [r["id"] for r in rows if r.get("got") != "unrun" and not r["ok"]]
    unrun = [r["id"] for r in rows if r.get("got") == "unrun"]
    return {"rungs": rows, "separates": not wrong and not unrun, "wrong": wrong,
            "unrun": unrun}


def format_verdicts(report: Dict[str, Any]) -> str:
    lines = []
    for row in report["rungs"]:
        mark = "ok  " if row["ok"] else ("----" if row["got"] == "unrun" else "FAIL")
        score = f"{row['score']:.2f}" if isinstance(row["score"], (int, float)) else "  —  "
        lines.append(f"  {mark} {row['id']:20s} {row['label']:5s} {score:>7s}  "
                     f"{row['got']:13s} (expected {row['expected']})")
    if report["separates"]:
        lines.append("  verdicts separate every rung")
    else:
        if report["wrong"]:
            lines.append(f"  verdicts WRONG for: {', '.join(report['wrong'])}")
        if report["unrun"]:
            lines.append(f"  rungs with no verdict: {', '.join(report['unrun'])}")
    return "\n".join(lines)


def sample_corpus(manifest_path: Path, runs_root: Path, retries: int = 3,
                  runner: Optional[Any] = None, pause: float = 0.0) -> Dict[str, Any]:
    """Sample every rung, retrying a failed run, and record every attempt in the manifest.

    The provider outage that cost three samples lived only in a shell loop outside this tool: the
    corpus could not say whether a rung was never attempted or attempted three times and refused.
    Retrying here makes that a property of the corpus. A retry is only for a MISSING or unparseable
    artefact — a run that wrote valid JSON and then exited nonzero keeps its sample, because the
    artefact is the evidence and the exit code is not.
    """
    failures = _module("failures")
    manifest = read(manifest_path)
    runner = runner or _default_runner
    assert runner is not None
    for rung in manifest["rungs"]:
        attempts: List[Dict[str, Any]] = []
        for attempt in range(1, max(1, retries) + 1):
            rc, out_path, log_text = runner(rung, Path(runs_root))
            exists = bool(out_path and Path(out_path).exists())
            parsed = False
            if exists:
                try:
                    document = json.loads(Path(out_path).read_text(encoding="utf-8-sig"))
                    parsed = isinstance(document, dict) and "findings" in document
                except (OSError, json.JSONDecodeError):
                    parsed = False
            attempts.append(failures.attempt_record(rc, exists, parsed, log_text))
            if parsed:
                break
            if attempt < retries:
                time.sleep(pause)
        rung["attempts"] = attempts
        ok = any(a.get("artefact") == "parsed" for a in attempts)
        rung["run"] = str(run_dir_for(Path(runs_root), rung)) if ok else None
        rung["note"] = None if ok else failures.summarise(attempts)
    write(Path(manifest_path), manifest)
    return manifest


def _undetected_note(round_dir: Path) -> str:
    """Why a seeded defect was not counted.

    "The reviewer proved nothing" and "the proof could not run" are different findings
    about different things — the reviewer, or the environment it ran in. Reporting the
    first when the second is true sends a maintainer to tune the reviewer while the
    repair is to adjudicate inside the toolchain.
    """
    try:
        payload = json.loads((Path(round_dir) / "proofs.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    summary = payload.get("summary") if isinstance(payload, dict) else None
    unrunnable = int((summary or {}).get("unrunnable") or 0)
    if unrunnable:
        return (f"undetected: {unrunnable} proof(s) could not run in this environment — "
                "adjudicate inside the toolchain, or the claims scale reads them as clean")
    return "undetected: the reviewer proved none of the seeded defects"


def collect(manifest_path: Path, runs_root: Path, threshold: float = 0.0) -> Dict[str, Any]:
    """Score every rung that has a run, and record what the reviewer actually proved.

    Adjudication is run first when a round has reviews but no `proofs.json`; without it there is
    nothing to adjudicate *from* and the rung is recorded as unrun rather than as clean.
    """
    manifest = read(manifest_path)
    adjudicate = _module("adjudicate")
    score = _module("score_reviews")
    merge = _module("merge")

    for rung in manifest["rungs"]:
        run_dir = run_dir_for(runs_root, rung)
        rung["run"] = str(run_dir) if run_dir.exists() else None
        if not run_dir.exists():
            # `sample_corpus` records why it gave up; without that, a rung that was attempted
            # three times and refused looked identical to one nobody ever ran.
            rung["note"] = _module("failures").summarise(rung.get("attempts") or [])
            continue
        _, round_dir = adjudicate.locate(run_dir)
        # The gate reads <dimension>.json. A run that only wrote generalist samples has to be
        # merged first — scoring it unmerged returns an error payload, which is not a score.
        if not (round_dir / "security.json").exists():
            try:
                merge.merge_round(round_dir)
            except Exception as exc:  # noqa: BLE001 - a rung that cannot be assembled says so
                rung["note"] = f"merge failed: {type(exc).__name__}: {exc}"
                continue
        if not (round_dir / "proofs.json").exists():
            try:
                adjudicate.adjudicate_round(round_dir, Path(rung["tree"]))
            except Exception as exc:  # noqa: BLE001 - a rung that cannot be scored says so
                rung["note"] = f"adjudication failed: {type(exc).__name__}: {exc}"
                continue
        result = score.evaluate(round_dir, threshold, repo=Path(rung["tree"]))
        if "certification" not in result:
            # `evaluate` returns {"error": ...} when it cannot read the round at all. Say so
            # instead of dying on a KeyError that hides which rung was unreadable.
            rung["note"] = f"could not be scored: {result.get('error') or result}"
            continue
        # A score is only comparable to a threshold derived on the same scale. Measured on a tree
        # with one README: the corpus declared `claims`, no claims calibration file existed, the
        # gate silently scored on the deterministic scale and returned 100.00 — a perfect rung that
        # measured nothing the corpus was measuring.
        declared = manifest.get("scale")
        if declared and result.get("score_source") != declared:
            rung["score"] = None
            rung["score_source"] = result.get("score_source")
            rung["note"] = (f"scored on the `{result.get('score_source')}` scale while the corpus "
                            f"declares `{declared}`; a threshold from one scale does not apply to "
                            f"the other")
            continue
        records: List[Dict[str, Any]] = []
        proofs_path = round_dir / "proofs.json"
        if proofs_path.exists():
            payload = json.loads(proofs_path.read_text(encoding="utf-8-sig"))
            records = payload.get("findings") or []
        confirmed = [r for r in records if r.get("state") == "confirmed"]
        # `unprovable` means the probes saw a defect and the reviewer settled nothing. The gate
        # still reports an aggregate in that case — measured at 100.00 on a tree where a probe
        # flagged something and the reviewer wrote nothing — and that number is a fiction: it is
        # the score of not having answered. It does not enter the corpus.
        if result.get("certification") == "unprovable":
            rung["score"] = None
            rung["certification"] = "unprovable"
            rung["score_source"] = result.get("score_source")
            rung["confirmed"] = len(confirmed)
            rung["detected"] = sum(1 for m in _match(rung.get("seeded") or [], confirmed)
                                   if m["matched"])
            rung["note"] = (f"unprovable: {result.get('coverage_gap') or 'the run settled nothing'}"
                            " — its aggregate is the score of not having answered")
            continue
        # A sample that ran no tool and proved nothing is not a clean tree — it is a sample that
        # examined nothing, and the gate scores "nothing found" as 100.00. Measured on a tree with
        # a single README: zero findings, zero tools, a perfect score, and the corpus would have
        # counted it as a good rung. Found by trying to sample an unsampleable tree.
        inform = _informative(round_dir)
        matches = _match(rung.get("seeded") or [], confirmed)
        if not inform[0]:
            rung["score"] = None
            rung["certification"] = None
            rung["confirmed"] = len(confirmed)
            rung["detected"] = sum(1 for m in matches if m["matched"])
            rung["matches"] = matches
            rung["note"] = inform[1]
            continue
        rung["score"] = result["aggregate"]
        rung["certification"] = result["certification"]
        rung["score_source"] = result.get("score_source")
        rung["confirmed"] = len(confirmed)
        rung["detected"] = sum(1 for m in matches if m["matched"])
        rung["matches"] = matches
        if rung.get("defects_seeded") and not rung["detected"]:
            rung["note"] = _undetected_note(_round_with_proofs(run_dir_for(runs_root, rung)))
        else:
            rung["note"] = None
    write(Path(manifest_path), manifest)
    return manifest


def read(path: Path) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path: Path, manifest: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")


def _round_with_proofs(run_dir: Path) -> Path:
    """The round inside a run root that holds the adjudication — the latest one that does.

    The same rule `adjudicate.locate` applies: a run root holds `round-N/`, and only the latest
    round with a `proofs.json` is the pass under measurement.
    """
    if (run_dir / "proofs.json").exists():
        return run_dir
    rounds = [p for p in run_dir.glob("round-*") if (p / "proofs.json").exists()]
    if not rounds:
        return run_dir

    def _number(path: Path) -> int:
        tail = path.name.split("-")[-1]
        return int(tail) if tail.isdigit() else 0

    return max(rounds, key=_number)


def _pass_records(round_dir: Path) -> List[Dict[str, Any]]:
    """The adjudication records for one pass, or [] when that pass produced none."""
    path = _round_with_proofs(Path(round_dir)) / "proofs.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8-sig")).get("findings") or []
    except (OSError, json.JSONDecodeError):
        return []


def _location(record: Dict[str, Any]) -> str:
    loc = record.get("location") or {}
    return f"{loc.get('path')}:{loc.get('line_range') or ''}"


def agreement(manifest: Dict[str, Any]) -> Dict[str, Any]:
    """How reproducible is a pass? Measured per rung across its repeats.

    Three questions, because the first corpus showed three different instabilities and only one of
    them was what I had assumed:

    * **agreement** — how many passes reported the same location (3/3 stable, 2/3 majority, 1/3
      one-off). Unstable findings are what make a score unrepeatable.
    * **severity** — the same location labelled differently by different passes. Measured on the
      nine-run corpus: one committed credential came back critical, critical, then medium.
    * **blind spots** — a seeded defect no pass reports. That is not noise; it is a gap that will
      never close by repeating the same run.
    """
    levels: Dict[int, List[Dict[str, Any]]] = {}
    for rung in manifest.get("rungs") or []:
        levels.setdefault(int(rung["level"]), []).append(rung)

    report = []
    for level in sorted(levels):
        rungs = sorted(levels[level], key=lambda r: r.get("repeat") or 0)
        passes = [_pass_records(Path(r["run"]) if r.get("run") else Path("/nonexistent"))
                  for r in rungs]
        passes = [p for p in passes if p]
        if not passes:
            report.append({"level": level, "passes": 0, "note": "no run"})
            continue

        counts: Dict[str, int] = {}
        severities: Dict[str, set] = {}
        for records in passes:
            seen = set()
            for record in records:
                # Confirmed only: an unsettled claim's severity is the reviewer's opinion, and it
                # is not an input to the score. Measuring it made a proven credential look like it
                # flipped to `low` because a *different, unproven* claim at the same line was
                # labelled low.
                if record.get("state") != "confirmed":
                    continue
                key = _location(record)
                if key in seen:
                    continue
                seen.add(key)
                counts[key] = counts.get(key, 0) + 1
                # Measure the severity the GATE uses, not the one the reviewer asserted. An
                # uncorroborated `critical` is scored as `high`, so a pass calling it critical and
                # another calling it high are the same verdict — reporting that as a flip would
                # send someone looking for a disagreement that cannot change any outcome.
                severities.setdefault(key, set()).add(
                    str(record.get("severity_scored") or record.get("severity") or "?"))

        total = len(passes)
        stable = sorted(k for k, n in counts.items() if n == total)
        majority = sorted(k for k, n in counts.items() if 1 < n < total)
        one_off = sorted(k for k, n in counts.items() if n == 1)
        disagreed = {k: sorted(v) for k, v in severities.items() if len(v) > 1}

        seeded = []
        for item in rungs[0].get("seeded") or []:
            hits = 0
            for records in passes:
                confirmed = [r for r in records if r.get("state") == "confirmed"]
                if _match([item], confirmed)[0]["matched"]:
                    hits += 1
            seeded.append({"path": item.get("path"), "line": item.get("line"),
                           "found_in": hits})

        report.append({
            "level": level,
            "passes": total,
            "confirmed_per_pass": [sum(1 for r in p if r.get("state") == "confirmed")
                                   for p in passes],
            "stable": stable, "majority": majority, "one_off": one_off,
            "severity_disagreements": disagreed,
            "seeded": seeded,
            "blind_spots": [s["path"] for s in seeded if s["found_in"] == 0],
        })
    return {"levels": report}


def format_agreement(report: Dict[str, Any]) -> str:
    lines = []
    for level in report["levels"]:
        if not level.get("passes"):
            lines.append(f"level {level['level']:>2}: no run")
            continue
        sev = level["severity_disagreements"]
        lines.append(
            f"level {level['level']:>2}: {level['passes']} passes · "
            f"confirmed {level['confirmed_per_pass']} · "
            f"stable {len(level['stable'])} · majority {len(level['majority'])} · "
            f"one-off {len(level['one_off'])} · severity disagreements {len(sev)}")
        for where, values in list(sev.items())[:4]:
            lines.append(f"    severity flips at {where}: {'/'.join(values)}")
        for spot in level["blind_spots"]:
            lines.append(f"    BLIND SPOT: {spot} — no pass reported it")
    return "\n".join(lines)


def summary(manifest: Dict[str, Any]) -> str:
    lines = [f"corpus: {len(manifest['rungs'])} rung(s), scale={manifest.get('scale')}"]
    for rung in manifest["rungs"]:
        score = "—" if rung.get("score") is None else f"{rung['score']:.2f}"
        detected = "" if (not rung.get("defects_seeded") or rung.get("score") is None) else \
            f" detected {rung.get('detected')}/{rung['defects_seeded']}"
        note = f"  [{rung['note']}]" if rung.get("note") else ""
        lines.append(f"  level {rung['level']:>2}  {rung['label']:<4} score {score:>7}"
                     f"{detected}{note}")
    return "\n".join(lines)
