#!/usr/bin/env python3
"""Build the durable council as a kanban graph: one card per sample, plus a
verifier that merges and gates the round.

    council swarm <repo> [--samples N] [--run-root <dir>]
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import council_config as _council_config

HERE = Path(__file__).resolve().parent
FRAMEWORK = HERE.parent

# Not configurable: a flag pointing the swarm at another profile would let a second
# reviewer roster grow back unreviewed. docs/DECISIONS.md #5.
GENERALIST = "council-generalist"
ORCHESTRATOR = "council-orchestrator"

DEFAULT_SAMPLES = 5


def slugify(text: str) -> str:
    """A stable, filesystem- and CLI-safe identifier.

    The tenant and idempotency key both travel through shells and a SQLite board, so
    anything outside [a-z0-9-] is collapsed rather than escaped — an identifier that
    needs quoting is an identifier that will eventually be quoted wrong.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
    return slug or "repo"


def council_invocation() -> str:
    """How a card should invoke this framework.

    Resolved from THIS script's own location, never hardcoded, so the same repo works
    from a checkout, a nix store path, or a handoff bundle. `council` is NOT assumed
    to be on PATH: the gateway's PATH is the nix profile plus /usr/bin, and this
    framework is not installed into it, so a card saying `council sample` would fail
    on its first line.

    `nix run <root>#council` when the root is a flake, else the interpreter running
    this script plus council_loop.py's own path — both resolving the framework the
    same way the user invoked it.
    """
    root = shlex.quote(str(FRAMEWORK))
    if (FRAMEWORK / "flake.nix").exists() and shutil.which("nix"):
        return f"nix run {root}#council --"
    return f"{shlex.quote(sys.executable)} {shlex.quote(str(HERE / 'council_loop.py'))}"


@dataclass
class CardSpec:
    """One card in the graph. `parents` are KEYS, resolved to ids at creation."""
    key: str
    title: str
    body: str
    assignee: str
    parents: List[str] = field(default_factory=list)
    skills: List[str] = field(default_factory=list)


def resolve_samples(samples: Optional[int], cfg: Dict[str, Any]) -> int:
    """The config sets the default; --samples overrides it, exactly as the loop does."""
    if samples is not None:
        return samples
    return int((cfg.get("review") or {}).get("samples", DEFAULT_SAMPLES))


def build_plan(repo: Path, samples: int = DEFAULT_SAMPLES, round_no: int = 1,
               run_root: Optional[Path] = None,
               goal: Optional[str] = None) -> List[CardSpec]:
    """The card graph for one round, in creation order. Pure: no I/O, no shell."""
    repo = repo.resolve()
    run_root = (run_root or (repo / ".review-council")).resolve()
    run_dir = run_root / f"round-{round_no}"
    invocation = council_invocation()
    goal_line = goal or f"Review {repo.name} (round {round_no})"

    cards: List[CardSpec] = [
        CardSpec(
            key="root",
            title=f"Swarm root: {goal_line}",
            body=(
                f"This is the round's anchor and shared blackboard.\n\n"
                f"Target: {repo}\nRound: {round_no}\nRun directory: {run_dir}\n\n"
                f"Set this round's goals: write {run_dir}/goals.json in the harness's "
                f"goal shape (one entry per dimension, each with objective, acceptance "
                f"and focus). If you cannot, say so plainly — the round falls back to "
                f"the built-in goals and still reviews."
            ),
            assignee=ORCHESTRATOR,
        ),
    ]

    for i in range(1, samples + 1):
        cards.append(CardSpec(
            key=f"worker{i}",
            title=f"sample {i}/{samples}",
            body=(
                f"Run this command and report the file it wrote:\n\n"
                f"    {invocation} sample {repo} --index {i} "
                f"--run-root {run_root} --round {round_no}\n\n"
                f"Do NOT review the code yourself and do NOT write the JSON by hand — "
                f"that command performs the review and writes generalist-{i}.json. If "
                f"it fails, report the exit code and its stderr; the gate reports a "
                f"missing sample, and inventing one would corrupt the round."
            ),
            assignee=GENERALIST,
            parents=["root"],
        ))

    cards.append(CardSpec(
        key="verifier",
        title="Verify: assemble, then run the deterministic gate",
        body=(
            f"Two deterministic commands, in order, reported VERBATIM:\n\n"
            f"    {invocation} merge {run_dir}\n"
            f"    {invocation} gate {run_dir}\n\n"
            f"`merge` buckets the samples into the per-dimension files the gate reads; "
            f"without it the gate finds no reviewer output at all and exits 2, because "
            f"each sample was written by a different card. Then report the exit code, "
            f"the aggregate, the threshold, and beta per dimension. Do NOT score the "
            f"code yourself, do NOT adjust the numbers, and do NOT summarise the "
            f"reviewers' prose as if it were the verdict — a score you compute is not "
            f"the score the framework enforces. If the gate exits non-zero, report the "
            f"reason it gives. Complete with metadata "
            f'{{"gate": "pass"}} only when the gate exits 0.'
        ),
        assignee=ORCHESTRATOR,
        parents=[f"worker{i}" for i in range(1, samples + 1)],
    ))

    cards.append(CardSpec(
        key="synthesizer",
        title="Synthesize: the control message",
        body=(
            f"Write the round's control message from the gate's verdict for {run_dir}: "
            f"outcome, reason, the per-dimension scores and the blocking findings. Take "
            f"every number from the gate's output, not from your own reading."
        ),
        assignee=ORCHESTRATOR,
        parents=["verifier"],
    ))
    return cards


def _render(spec: CardSpec, body_dir: Path) -> List[str]:
    """The `hermes kanban create` argv for one card, before parents/dedup are added."""
    argv = [
        "hermes", "kanban", "create", spec.title,
        "--body-file", str(body_dir / f"{spec.key}.md"),
        "--assignee", spec.assignee,
    ]
    for skill in spec.skills:
        argv += ["--skill", skill]
    return argv


def _create_cards(cards: List[CardSpec], run_root: Path, tenant: str,
                  created_by: str,
                  idempotency_key: Optional[str]) -> List[Dict[str, Any]]:
    """Create the graph, resolving parent KEYS to the ids the board returns.

    Sequential in topological order because a parent's id does not exist until its
    card does. The board is the durable store; this is a thin client over it.
    """
    body_dir = run_root / ".swarm"
    body_dir.mkdir(parents=True, exist_ok=True)
    ids: Dict[str, str] = {}
    created: List[Dict[str, Any]] = []

    for index, spec in enumerate(cards):
        (body_dir / f"{spec.key}.md").write_text(spec.body + "\n",
                                                 encoding="utf-8", newline="\n")
        argv = _render(spec, body_dir)
        argv += ["--tenant", tenant, "--created-by", created_by]
        for parent_key in spec.parents:
            argv += ["--parent", ids[parent_key]]
        # Root only: re-running the same repo and round is the same round, so a
        # reclaimed dispatch cannot fork a duplicate. Children are created once, after it.
        if index == 0 and idempotency_key:
            argv += ["--idempotency-key", idempotency_key]
        argv += ["--json"]

        proc = subprocess.run(argv, capture_output=True, text=True)
        if proc.returncode != 0:
            print(f"swarm: creating card '{spec.key}' failed:\n{proc.stderr.strip()}",
                  file=sys.stderr)
            return created
        try:
            payload = json.loads(proc.stdout)
            task_id = str(payload.get("id") or payload.get("task_id") or "")
        except (json.JSONDecodeError, AttributeError):
            task_id = ""
        if not task_id:
            print(f"swarm: card '{spec.key}' returned no id:\n{proc.stdout.strip()}",
                  file=sys.stderr)
            return created
        ids[spec.key] = task_id
        created.append({"key": spec.key, "id": task_id, "assignee": spec.assignee,
                        "parents": [ids[p] for p in spec.parents]})
    return created


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="swarm",
        description="Build the DURABLE council as a kanban graph (M7). The loop "
                    "spawns a subprocess and dies with it; the swarm is a durable "
                    "board the gateway's dispatcher can reclaim.")
    parser.add_argument("repo", nargs="?", default=".",
                        help="the repository to review (default: cwd)")
    parser.add_argument("--samples", type=int, default=None,
                        help="worker cards, one per sample (default: [review].samples "
                             f"from the config, else {DEFAULT_SAMPLES})")
    parser.add_argument("--round", type=int, default=1, dest="round_no",
                        help="round number, part of the dedup key (default: 1)")
    parser.add_argument("--run-root", default=None,
                        help="where the run directory lives (default: <repo>/.review-council)")
    parser.add_argument("--goal", default=None,
                        help="the swarm's goal line (default: derived from repo + round)")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the plan without creating any cards")
    parser.add_argument("--json", action="store_true",
                        help="emit the created ids (or the plan, with --dry-run) as JSON")
    args = parser.parse_args(argv)

    repo = Path(args.repo).expanduser()
    if not repo.is_dir():
        print(f"swarm: not a directory: {repo}", file=sys.stderr)
        return 2
    cfg, _ = _council_config.load()
    args.samples = resolve_samples(args.samples, cfg)
    if args.samples < 1:
        print("swarm: --samples must be at least 1", file=sys.stderr)
        return 2

    run_root = (Path(args.run_root).expanduser() if args.run_root
                else repo.resolve() / ".review-council")
    cards = build_plan(repo, args.samples, args.round_no, run_root, args.goal)
    slug = slugify(repo.resolve().name)
    # No git revision in the key: a plain directory is a legitimate target.
    idempotency_key = f"{slug}-r{args.round_no}"

    if args.dry_run:
        body_dir = run_root / ".swarm"
        print(f"# {len(cards)} card(s), tenant={slug}, dedup={idempotency_key}")
        print(f"# framework invocation: {council_invocation()}")
        for spec in cards:
            print()
            print(f"# --- {spec.key}  ({spec.assignee}"
                  + (f", after {', '.join(spec.parents)}" if spec.parents else "") + ")")
            print(f"# body -> {body_dir / (spec.key + '.md')}")
            print(" ".join(shlex.quote(a) for a in _render(spec, body_dir)))
        if args.json:
            print()
            print(json.dumps([{"key": c.key, "title": c.title, "assignee": c.assignee,
                               "parents": c.parents, "body": c.body} for c in cards],
                             indent=2))
        return 0

    if shutil.which("hermes") is None:
        print("swarm: `hermes` is not on PATH — it owns the durable board, so this "
              "cannot run without it. Use --dry-run to see the plan.", file=sys.stderr)
        return 2

    created = _create_cards(cards, run_root, slug, ORCHESTRATOR, idempotency_key)
    if args.json:
        print(json.dumps(created, indent=2))
    if len(created) != len(cards):
        print(f"swarm: created {len(created)}/{len(cards)} card(s); the board is "
              f"durable, so re-running resumes rather than duplicating.",
              file=sys.stderr)
        return 1
    print(f"Swarm root:   {created[0]['id']}")
    print(f"Workers:      "
          f"{', '.join(c['id'] for c in created if c['key'].startswith('worker'))}")
    print(f"Verifier:     {next(c['id'] for c in created if c['key'] == 'verifier')}")
    print(f"Synthesizer:  {next(c['id'] for c in created if c['key'] == 'synthesizer')}")
    print(f"\nThe gateway's dispatcher claims these. Watch with:\n"
          f"    hermes kanban tail {created[0]['id']}")
    return 0


if __name__ == "__main__":
    # Not a program: reached through `council <verb>`. See council.py.
    from council import require_dispatch

    require_dispatch("swarm")
    raise SystemExit(main())
