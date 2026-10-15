#!/usr/bin/env python3
"""kb_council.py - ingest review-council runs into the knowledge base.

The council writes machine-readable results under
`<project>/.review-council/<timestamp>/`:

    outcome.json        the loop's own verdict: outcome, reason, scores,
                        threshold, met_minimum, next_steps, repo, mode
    next-steps.md       the handover plan
    round-N/<dim>.json  one per reviewer: security, correctness, readability,
                        architecture, performance (score, tools_run, findings)
    round-N/meta.json   target_sha, mode, round, stacks

This turns each run into a `work/` page so the supervisor board shows it, and so
findings can be referenced like any other knowledge.

**The score is never recomputed here.** `score_reviews.py` is the single writer of
the aggregate, and it is the gate. Re-deriving it would be a second implementation
that can disagree with the one that actually gated the merge - so this reads the
council's recorded outcome and reports exactly that. If a run has no outcome.json,
there is no verdict and none is invented.

Usage:
    kb_council.py <project-dir> [--vault <root>] [--all] [--dry-run]

Without --all only the newest run is ingested. Existing generated pages are
rewritten in place; authored work items are never touched.
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import kb_reindex as kb  # noqa: E402

RUN_DIR_NAME = ".review-council"
DIMENSIONS = ("security", "correctness", "readability", "architecture", "performance")
SEVERITY_ORDER = ("critical", "high", "medium", "low", "info")


def load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None


def find_runs(project: Path) -> list[Path]:
    base = project / RUN_DIR_NAME
    if not base.is_dir():
        return []
    runs = [d for d in sorted(base.iterdir()) if d.is_dir()]
    return [r for r in runs if (r / "outcome.json").is_file() or any(r.glob("round-*"))]


def latest_round(run_root: Path) -> Path | None:
    rounds = []
    for d in run_root.glob("round-*"):
        try:
            rounds.append((int(d.name.split("-", 1)[1]), d))
        except (IndexError, ValueError):
            continue
    return max(rounds)[1] if rounds else None


def collect_dimensions(round_dir: Path | None) -> dict:
    """Per-dimension score and finding counts, read verbatim from the reviewers."""
    out: dict[str, dict] = {}
    if not round_dir:
        return out
    for dim in DIMENSIONS:
        data = load_json(round_dir / f"{dim}.json")
        if not isinstance(data, dict):
            continue
        findings = data.get("findings") or []
        counts = {sev: 0 for sev in SEVERITY_ORDER}
        open_counts = {sev: 0 for sev in SEVERITY_ORDER}
        for f in findings:
            if not isinstance(f, dict):
                continue
            sev = str(f.get("severity") or "info").lower()
            if sev in counts:
                counts[sev] += 1
                if str(f.get("status") or "open").lower() == "open":
                    open_counts[sev] += 1
        tools = data.get("tools_run") or []
        out[dim] = {
            "score": data.get("score"),
            "schema_valid": bool(data.get("schema_valid")),
            "findings": len(findings),
            "open": sum(open_counts.values()),
            "open_by_severity": {k: v for k, v in open_counts.items() if v},
            "tools_ran": sum(1 for t in tools if isinstance(t, dict) and t.get("ran")),
            "tools_total": len(tools),
        }
    return out


def build_page(project: Path, run_root: Path, vault: Path) -> tuple[str, str]:
    """(slug, file content) for one council run."""
    outcome = load_json(run_root / "outcome.json") or {}
    rnd = latest_round(run_root)
    dims = collect_dimensions(rnd)
    meta = load_json(rnd / "meta.json") if rnd else None

    project_name = project.name
    run_id = run_root.name
    today = datetime.date.today().isoformat()
    # Always project-relative: an absolute path hardcodes this machine, breaks on the
    # host the board is read from, and leaks a local layout into a shared vault.
    try:
        rel_run = run_root.relative_to(project).as_posix()
    except ValueError:
        rel_run = f"{RUN_DIR_NAME}/{run_id}"
    rel_next = f"{rel_run}/next-steps.md"

    verdict = str(outcome.get("outcome") or "unknown")
    met = bool(outcome.get("met_minimum"))
    threshold = outcome.get("threshold")
    scores = outcome.get("scores") or []
    aggregate = scores[-1] if scores else None

    # Board state: a satisfied run is done; an unmet or escalated one is open work.
    if verdict == "satisfied" or met:
        status = "done"
    elif verdict in ("escalated", "error"):
        status = "blocked"
    else:
        status = "active"

    open_blocking = sum(d.get("open", 0) for d in dims.values())
    slug = f"council-{kb.norm_key(project_name)}-{kb.norm_key(run_id)}"

    fm = {
        "title": f"council: {project_name} — {run_id}",
        "created": today,
        "updated": today,
        "type": "work",
        "tags": ["council", "hermes", "workflow"],
        "sources": [f"council:{project_name}/{run_id}"],
        "confidence": "high",
        "status": status,
        "priority": "P1" if not met else "P3",
        "owner": "council",
        "topic": "council",
        "generated": "true",
        "project": project_name,
        "run_id": run_id,
        "verdict": verdict,
        "met_minimum": str(met).lower(),
        "threshold": threshold if threshold is not None else "",
        "aggregate": aggregate if aggregate is not None else "",
        "rounds": len(scores),
        "open_findings": open_blocking,
        "target_sha": str((meta or {}).get("target_sha") or ""),
        "stacks": ", ".join((meta or {}).get("stacks") or []),
        "next_steps": rel_next,
    }
    if status == "blocked":
        fm["blocked_by"] = [f"council verdict: {verdict}"]

    body = [f"A review-council run on **{project_name}** — `{rel_run}` relative to the "
            f"project root.\n"]
    body.append("\n> Generated by `kb_council.py` from the council's own `outcome.json`. "
                "The score is the council's, not recomputed here. Do not hand-edit; "
                "re-run the ingester instead.\n")
    body.append(f"\n**Verdict:** `{verdict}`"
                + (f" — aggregate **{aggregate}** vs minimum **{threshold}**"
                   if aggregate is not None and threshold is not None else "")
                + ("  (minimum met)" if met else "  (**minimum NOT met**)") + "\n")
    if outcome.get("reason"):
        body.append(f"\n**Why it stopped:** {outcome['reason']}\n")
    body.append(f"\n**Mode:** `{outcome.get('mode', '-')}`  ·  "
                f"**rounds:** {len(scores)}  ·  "
                f"**target:** `{fm['target_sha'][:12] or '-'}`\n")

    if dims:
        body.append("\n## Dimensions\n\n")
        body.append("| dimension | score | open | total | tools ran |\n|---|---|---|---|---|\n")
        for dim in DIMENSIONS:
            d = dims.get(dim)
            if not d:
                body.append(f"| {dim} | *(no reviewer output)* | | | |\n")
                continue
            body.append(f"| {dim} | {d['score'] if d['score'] is not None else '-'} | "
                        f"{d['open']} | {d['findings']} | "
                        f"{d['tools_ran']}/{d['tools_total']} |\n")

    missing = [d for d in DIMENSIONS if d not in dims]
    if missing:
        body.append(f"\n> Incomplete council: no output for {', '.join(missing)}. "
                    "A partial council cannot certify a pass.\n")

    if fm["next_steps"]:
        body.append(f"\n**Handover plan:** `{rel_next}` (relative to the project root)\n")

    body.append("\nRelated: [[hermes-review-orchestration]], "
                "[[deterministic-review-scoring]], [[multi-agent-review-pitfalls]].\n")
    return slug, kb.render_frontmatter(fm) + "".join(body)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("project", help="the reviewed project's directory")
    ap.add_argument("--vault", default=None, help="vault root (default: resolve as usual)")
    ap.add_argument("--all", action="store_true", help="ingest every run, not just the newest")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    project = Path(a.project).expanduser()
    if not project.is_dir():
        print(f"kb_council: not a directory: {project}", file=sys.stderr)
        return 1
    vault = Path(a.vault).expanduser() if a.vault else kb.resolve_root()
    if not vault.is_dir():
        print(f"kb_council: vault not found: {vault}", file=sys.stderr)
        return 1

    runs = find_runs(project)
    if not runs:
        print(f"kb_council: no council runs under {project / RUN_DIR_NAME}", file=sys.stderr)
        return 1
    if not a.all:
        runs = runs[-1:]

    written = 0
    for run_root in runs:
        slug, content = build_page(project, run_root, vault)
        dest = vault / kb.WORK_DIR / f"{slug}.md"
        if a.dry_run:
            print(f"kb_council DRY RUN: {dest.relative_to(vault).as_posix()}")
            print(content.split("---\n", 2)[1][:600])
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        kb.write_if_changed(dest, content)
        written += 1
        print(f"kb_council: {dest.relative_to(vault).as_posix()}")

    if not a.dry_run:
        print(f"kb_council: {written} run(s) ingested. "
              "Run kb_reindex.py to refresh the board.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
