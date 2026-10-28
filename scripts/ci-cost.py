#!/usr/bin/env python3
"""Per-job cost for a workflow run, as a markdown table.

The API already returns `started_at` and `completed_at` per job, so "which job ate the time" is a
question with a numeric answer. This exists because it was answered the hard way once: two macOS
jobs vanished from a run, and the only evidence was a 15m01s gap between two timestamps read by
hand, from a check-run listing that showed neither.

Deliberately not a gate. A report that fails a build is a nuisance and gets muted; a gate that
reports is not a gate. The job that renders this never decides anything.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime


def _dt(value):
    """ISO-8601 with a trailing Z, or None for a job that has not finished."""
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def cost_rows(payload):
    """(name, seconds, conclusion) per job, longest first. `None` seconds = still running."""
    rows = []
    for job in payload.get("jobs", []):
        start, end = _dt(job.get("started_at")), _dt(job.get("completed_at"))
        seconds = int((end - start).total_seconds()) if start and end else None
        name = job.get("name") or "(unnamed)"
        conclusion = job.get("conclusion") or "running"
        rows.append((name, seconds, conclusion))
    rows.sort(key=lambda r: -(r[1] if r[1] is not None else -1))
    return rows


def span_seconds(payload):
    """First observed moment to last: the run's wall clock, which the job sum is not.

    A still-running job contributes its START to the last moment. Using only completed jobs made
    the table report a span that ended before the job it was measuring — the run was 91s old and the
    span said 90.
    """
    starts = [d for d in (_dt(j.get("started_at")) for j in payload.get("jobs", [])) if d]
    ends = [d for d in (_dt(j.get("completed_at")) for j in payload.get("jobs", [])) if d]
    if not starts:
        return None
    return int((max(starts + ends) - min(starts)).total_seconds())


def table(payload):
    lines = ["| job | seconds | conclusion |", "|---|---|---|"]
    for name, seconds, conclusion in cost_rows(payload):
        lines.append(f"| {name} | {'—' if seconds is None else seconds} | {conclusion} |")
    span = span_seconds(payload)
    if span is not None:
        lines += ["", f"**Run span:** {span}s from first start to last finish. "
                      "Jobs overlap, so this is not the sum of the column."]
    return "\n".join(lines)


def main(argv):
    path = argv[1] if len(argv) > 1 else "-"
    if path == "-":
        payload = json.loads(sys.stdin.read())
    else:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    print(table(payload))


if __name__ == "__main__":
    main(sys.argv)
