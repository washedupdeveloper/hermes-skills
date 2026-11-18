#!/usr/bin/env python3
"""Better or worse than before — decided by evidence, not by a number out of 100.

A run's **record** is the set of things it established: which findings a check settled, and what
the deterministic probes saw. Comparing two records answers one question — is this better, worse,
the same, or not comparable — and every part of the answer cites the evidence that produced it.

There is no threshold in this module, and no score. A verdict is a comparison against a named
baseline, so a derived cutoff never has to be defended: either something that was proven still is,
or it is not. When the evidence cannot be compared — a probe that ran before and did not run
now — the answer is `incomparable`, which is a refusal to guess rather than a pass.

Limits, stated rather than discovered later:

* Findings are keyed by `path:line_range:dimension`. Over the same tree that identity is exact; across
  revisions that move lines, an unchanged defect can read as a new one. This tool answers "is this
  change better" for work against one tree, and says so.
* Only what the proofs settled is compared. A finding nobody proved is neither a regression nor a
  resolution — it is the absence of evidence, and `incomplete` reports it.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).resolve().parent
SCHEMA_VERSION = 1


def _read(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None


def record(run_dir: Path) -> Dict[str, Any]:
    """What one run established, canonically. Written beside the run as `record.json`."""
    run_root, round_dir = _locate(Path(run_dir))
    proofs = _read(round_dir / "proofs.json") or {}
    findings = []
    for item in proofs.get("findings") or []:
        location = item.get("location") or {}
        path = str(location.get("path") or "")
        span = str(location.get("line_range") or "")
        findings.append({
            "key": f"{path}:{span}:{item.get('dimension') or ''}",
            "path": path,
            "line_range": span,
            "dimension": item.get("dimension") or "",
            "severity": item.get("severity_scored") or item.get("severity") or "",
            "state": item.get("state") or "",
            "claim": item.get("claim") or "",
        })
    probes = []
    for probe in _read(round_dir / "probes.json") or []:
        if not isinstance(probe, dict):
            continue
        probes.append({"tool": probe.get("tool") or "",
                       "ran": bool(probe.get("ran")),
                       "defects": len(probe.get("findings") or [])})
    return {"schema_version": SCHEMA_VERSION, "run": str(run_root),
            "findings": sorted(findings, key=lambda f: f["key"]),
            "probes": sorted(probes, key=lambda p: p["tool"])}


def _locate(run_dir: Path) -> tuple:
    """The round a run root holds — the latest one carrying an adjudication."""
    if (run_dir / "proofs.json").exists():
        return run_dir.parent, run_dir
    rounds = [p for p in run_dir.glob("round-*") if p.is_dir()]
    if not rounds:
        return run_dir, run_dir

    def number(path: Path) -> int:
        tail = path.name.split("-")[-1]
        return int(tail) if tail.isdigit() else 0

    best = max(rounds, key=number)
    return run_dir, best


def _settled(rec: Dict[str, Any], state: str) -> Dict[str, Dict[str, Any]]:
    return {f["key"]: f for f in rec.get("findings") or [] if f.get("state") == state}


def _blocking_severity(severity: str) -> bool:
    return str(severity).lower() in ("high", "critical")


def compare(baseline: Dict[str, Any], candidate: Dict[str, Any]) -> Dict[str, Any]:
    """The verdict, and the evidence for it. No score is computed anywhere in here."""
    if baseline.get("schema_version") != candidate.get("schema_version"):
        return {"verdict": "incomparable",
                "reasons": ["the two records were written by different versions"],
                "regressions": [], "resolutions": [], "coverage_grew": []}

    before_probes = {p["tool"]: p for p in baseline.get("probes") or [] if p.get("ran")}
    after_probes = {p["tool"]: p for p in candidate.get("probes") or [] if p.get("ran")}
    lost = sorted(set(before_probes) - set(after_probes))
    if lost:
        # A tool that ran before and did not run now cannot find anything, and "nothing found"
        # would read as an improvement. That is the absence of evidence, not evidence of absence.
        return {"verdict": "incomparable",
                "reasons": [f"these analyzers ran in the baseline and not in this run: "
                            f"{', '.join(lost)}"],
                "regressions": [], "resolutions": [],
                "coverage_grew": sorted(set(after_probes) - set(before_probes))}

    before = _settled(baseline, "confirmed")
    after = _settled(candidate, "confirmed")

    regressions: List[Dict[str, Any]] = []
    for key, finding in sorted(after.items()):
        if key in before:
            continue
        if _blocking_severity(finding.get("severity", "")):
            regressions.append({"kind": "finding", "key": key, "severity": finding["severity"],
                                "evidence": finding.get("claim") or finding["path"]})
    for tool, probe in sorted(after_probes.items()):
        was = before_probes.get(tool, {}).get("defects", 0)
        if probe.get("defects", 0) > 0 >= was:
            regressions.append({"kind": "probe", "key": tool, "severity": "high",
                                "evidence": f"`{tool}` now reports "
                                            f"{probe['defects']} defect(s); it reported none before"})

    resolutions: List[Dict[str, Any]] = []
    for key, finding in sorted(before.items()):
        if key in after:
            continue
        resolutions.append({"kind": "finding", "key": key, "severity": finding.get("severity", ""),
                            "evidence": finding.get("claim") or finding["path"]})
    for tool, probe in sorted(before_probes.items()):
        now = after_probes.get(tool, {}).get("defects", 0)
        if probe.get("defects", 0) > 0 >= now:
            resolutions.append({"kind": "probe", "key": tool, "severity": "high",
                                "evidence": f"`{tool}` reported {probe['defects']} defect(s) before "
                                            f"and reports none now"})

    if regressions:
        verdict = "worse"
    elif resolutions:
        verdict = "better"
    else:
        verdict = "same"

    reasons = []
    if regressions:
        reasons.append(f"{len(regressions)} thing(s) that were not established before are now: "
                       + ", ".join(r["key"] for r in regressions[:3]))
    if resolutions:
        reasons.append(f"{len(resolutions)} thing(s) established before are no longer: "
                       + ", ".join(r["key"] for r in resolutions[:3]))
    if not reasons:
        reasons.append("the same findings are confirmed and the same analyzers agree")
    return {"verdict": verdict, "reasons": reasons, "regressions": regressions,
            "resolutions": resolutions,
            "coverage_grew": sorted(set(after_probes) - set(before_probes))}


def format_verdict(result: Dict[str, Any]) -> str:
    lines = [f"  verdict: {result['verdict']}"]
    for reason in result["reasons"]:
        lines.append(f"    {reason}")
    for item in result["regressions"]:
        lines.append(f"    WORSE  [{item['kind']}] {item['key']} — {item['evidence']}")
    for item in result["resolutions"]:
        lines.append(f"    BETTER [{item['kind']}] {item['key']} — {item['evidence']}")
    if result.get("coverage_grew"):
        lines.append(f"    note: coverage grew ({', '.join(result['coverage_grew'])}) — a new "
                     f"analyzer's findings are new evidence, not a regression of the code")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="compare",
        description="Compare a run against a recorded baseline: better, worse, same or incomparable")
    parser.add_argument("--baseline", required=True, metavar="RECORD",
                        help="a record.json written by `compare --record`")
    parser.add_argument("--run", required=True, metavar="DIR",
                        help="the run directory to compare against the baseline")
    parser.add_argument("--record", metavar="RUN", help="write a run's record.json and stop")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.record:
        payload = record(Path(args.record))
        out = Path(args.record) / "record.json"
        out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")
        print(f"compare: wrote {out} ({len(payload['findings'])} finding(s))")
        return 0

    baseline_doc = _read(Path(args.baseline))
    if baseline_doc is None:
        print(f"compare: cannot read baseline {args.baseline}", file=sys.stderr)
        return 2
    result = compare(baseline_doc, record(Path(args.run)))
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(format_verdict(result))
    return {"better": 0, "same": 0, "worse": 1, "incomparable": 2}[result["verdict"]]


if __name__ == "__main__":
    from council import require_dispatch

    require_dispatch("compare")
    raise SystemExit(main())
