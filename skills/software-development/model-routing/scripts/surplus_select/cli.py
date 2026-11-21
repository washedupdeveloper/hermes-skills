"""Command line surface.

Four verbs, each one plane:

  status     read the snapshot and budget, change nothing
  calibrate  read Hermes state databases, write budget.yaml
  refresh    read the provider, write snapshot.json
  plan       read snapshot + budget + change, write report.json and report.html

Nothing here decides anything; the pure modules do. This file only resolves
paths, parses arguments and prints.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import baseline as baseline_mod
from . import benchmarks as benchmarks_mod
from . import calibration, providers, report, routing, snapshot as snapshot_mod
from .benchmarks import BenchmarkCache
from .calibration import Budget
from .model import Decision, Snapshot
from .portfolio import Portfolio, choose

DEFAULT_HOME = Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes")).expanduser()
DEFAULT_STATE = DEFAULT_HOME / "cache" / "surplus-select"

SOURCES = [
    {
        "title": "Surplus Intelligence — live model market",
        "url": "https://www.surplusintelligence.ai/markets?discount=90&ctx=128000&inputs=text",
    },
    {"title": "BenchLM — coding leaderboard", "url": "https://benchlm.ai/coding"},
    {"title": "Vals AI — SWE-bench Verified", "url": "https://www.vals.ai/benchmarks/swebench"},
    {
        "title": "LLM Benchmark — HLE-Diamond",
        "url": "https://llmbenchmark.ai/benchmarks/aa-hle-diamond",
    },
    {
        "title": "LLM Benchmark — FrontierMath",
        "url": "https://llmbenchmark.ai/benchmarks/epoch-frontiermath",
    },
]


def _state_path(home: Path, profile: str) -> Path:
    if profile in ("", "default"):
        return home / "state.db"
    return home / "profiles" / profile / "state.db"


def _role_for_profile(name: str) -> str | None:
    lowered = name.lower()
    if lowered in ("default", "builder"):
        return "builder"
    if "council" in lowered or "review" in lowered:
        return "reviewer"
    if "runner" in lowered:
        return "runner"
    if "judge" in lowered or "architect" in lowered:
        return "judge"
    return None


def _combine(roles: list[calibration.RoleCalibration]) -> calibration.RoleCalibration:
    first = roles[0]
    total = first.monthly_total
    sessions = first.sessions
    for role in roles[1:]:
        total = total + role.monthly_total
        sessions += role.sessions

    def pick(values: list) -> object:
        return max(values, key=lambda tokens: tokens.total())

    return calibration.RoleCalibration(
        role=first.role,
        monthly_total=total,
        per_session=snapshot_percentiles(pick([r.per_session.p50 for r in roles]), pick([r.per_session.p90 for r in roles])),
        per_call=snapshot_percentiles(pick([r.per_call.p50 for r in roles]), pick([r.per_call.p90 for r in roles])),
        sessions=sessions,
        window_days=first.window_days,
        source="; ".join(role.source for role in roles),
        uncalibrated=all(role.uncalibrated for role in roles),
    )


def snapshot_percentiles(p50, p90):
    from .model import Percentiles

    return Percentiles(p50=p50, p90=p90)


def cmd_calibrate(args: argparse.Namespace) -> int:
    home = Path(args.hermes_home).expanduser()
    if args.profiles:
        names = list(args.profiles)
    else:
        names = ["default"]
        profiles_dir = home / "profiles"
        if profiles_dir.is_dir():
            names += sorted(
                child.name
                for child in profiles_dir.iterdir()
                if (child / "state.db").is_file()
            )
    measured: dict[str, list[calibration.RoleCalibration]] = {}
    for name in names:
        role = _role_for_profile(name)
        if role is None:
            print(f"skip {name}: no role mapping", file=sys.stderr)
            continue
        path = _state_path(home, name)
        try:
            item = calibration.measure(role, path, window_days=args.window)
        except calibration.CalibrationError as exc:
            print(f"skip {name}: {exc}", file=sys.stderr)
            continue
        measured.setdefault(role, []).append(item)
        print(
            f"{role:<9} {name:<22} sessions={item.sessions:<5} "
            f"input={item.monthly_total.input / 1e6:>8.1f}M output={item.monthly_total.output / 1e6:>7.1f}M "
            f"p50={item.per_session.p50.input / 1e3:>7.1f}k"
        )
    if not measured:
        print("error: no state database produced a measurement", file=sys.stderr)
        return 1
    combined = [_combine(items) for items in measured.values()]
    for role in ("builder", "reviewer", "runner", "judge"):
        if role not in measured:
            combined.append(calibration._uncalibrated(role, args.window, "not calibrated"))
    budget = calibration.build_budget(combined, window_days=args.window)
    out = Path(args.out).expanduser()
    calibration.save_budget(budget, out)
    print(f"wrote {out} ({len(combined)} roles, window {args.window}d)")
    return 0


def cmd_refresh(args: argparse.Namespace) -> int:
    provider = providers.provider_for(args.url)
    catalog = provider.fetch_catalog()
    if args.models:
        requested = [item.strip() for item in args.models.split(",") if item.strip()]
    else:
        cache = benchmarks_mod.load(args.benchmarks)
        requested = [model for model in cache.models if model in catalog]
    wanted = [model for model in requested if model in catalog]
    missing = [model for model in requested if model not in catalog]
    if missing:
        print(f"not in this catalog: {', '.join(missing[:5])}", file=sys.stderr)
    if not wanted:
        print("error: nothing to refresh; pass --models or a benchmark cache that matches", file=sys.stderr)
        return 1
    snap = provider.refresh(wanted)
    snapshot_mod.save(snap, args.out)
    priced = sum(1 for model in snap.models.values() if model.best)
    print(
        f"wrote {args.out}: {len(snap.models)} models, {priced} with a live offer, "
        f"provider {snap.provider}, {snap.freshness()}"
    )
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    snap = snapshot_mod.load(args.snapshot)
    print(f"provider   {snap.provider}  {snap.base_url}")
    print(f"fetched    {snap.fetched_at.isoformat()}  ({snap.age_hours():.1f}h, {snap.freshness()})")
    print(f"digest     {snapshot_mod.digest(snap)}")
    print(f"models     {len(snap.models)}  priced {sum(1 for model in snap.models.values() if model.best)}")
    print(f"caps       {snap.capabilities}")
    if Path(args.budget).is_file():
        budget = calibration.load_budget(args.budget)
        print(f"budget     {budget.calibrated_at}  window {budget.window_days}d")
        for name, role in sorted(budget.roles.items()):
            flag = " (illustrative)" if role.uncalibrated else ""
            print(
                f"  {name:<9} sessions={role.sessions:<4} "
                f"input={role.monthly_total.input / 1e6:.1f}M output={role.monthly_total.output / 1e6:.1f}M{flag}"
            )
    else:
        print(f"budget     none at {args.budget}")
    return 0


def _resolve_routing(change: Path) -> routing.RoutingMap:
    routing_file = change / "routing.yaml"
    if routing_file.is_file():
        return routing.load_routing(routing_file)
    return routing.draft_routing(change)


def cmd_plan(args: argparse.Namespace) -> int:
    change = Path(args.change).expanduser()
    if not change.is_dir():
        print(f"error: no change directory at {change}", file=sys.stderr)
        return 1
    snap = snapshot_mod.load(args.snapshot)
    if not snap.allows_ranking() and not args.accept_stale:
        print(
            f"error: snapshot is {snap.age_hours():.1f}h old; refresh it or pass --accept-stale",
            file=sys.stderr,
        )
        return 1
    budget = calibration.load_budget(args.budget) if Path(args.budget).is_file() else calibration.default_budget()
    cache = benchmarks_mod.load(args.benchmarks)

    resolved = baseline_mod.resolve(args.baseline, args.baseline_env, Path(args.profile_config))
    portfolio = choose(cache, snap, resolved.model)
    routing_map = _resolve_routing(change)
    if not routing_map.tasks:
        print(f"error: no tasks in {change / 'tasks.md'}", file=sys.stderr)
        return 1

    judge = portfolio.get("judge")
    decisions: list[Decision] = [
        routing.route(task, resolved.model, judge=judge.model_id if judge else None)
        for task in routing_map.tasks.values()
    ]
    payload = report.build(
        snapshot=snap,
        budget=budget,
        portfolio=portfolio,
        routing=routing_map,
        decisions=decisions,
        cache=cache,
        baseline=resolved.model,
        baseline_source=resolved.source,
        sources=SOURCES,
    )
    out = Path(args.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "report.json"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not args.no_html:
        (out / "report.html").write_text(report.render_html(payload), encoding="utf-8")

    print(f"baseline   {resolved.model}  ({resolved.source})")
    print(f"snapshot   {snap.freshness()}  {snap.age_hours():.1f}h  {snapshot_mod.digest(snap)}")
    print("portfolio")
    for role in portfolio.roles:
        print(f"  {role.name:<9} {role.model_id:<32} coding {role.coding or 0:>5.1f}  {report._price(role.realised)}")
    print(f"cost       ${payload['costs']['total']:,.2f}/mo (7-day realised, {budget.window_days}d window)")
    print("tasks")
    for decision in decisions:
        flag = "  NEEDS SCOPING" if decision.needs_scoping else ""
        print(f"  {decision.task_id:<6} {decision.model:<32} {decision.tier}{flag}")
    print(f"wrote      {json_path}")
    if not args.no_html:
        print(f"wrote      {out / 'report.html'}")
    return 0


def _add_paths(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--snapshot", default=str(DEFAULT_STATE / "snapshot.json"))
    parser.add_argument("--budget", default=str(DEFAULT_STATE / "budget.yaml"))
    parser.add_argument("--benchmarks", default=str(benchmarks_mod.DEFAULT_PATH))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="surplus-select",
        description="Route coding tasks to a priced model portfolio.",
    )
    parser.add_argument("--snapshot", default=str(DEFAULT_STATE / "snapshot.json"))
    parser.add_argument("--budget", default=str(DEFAULT_STATE / "budget.yaml"))
    parser.add_argument("--benchmarks", default=str(benchmarks_mod.DEFAULT_PATH))
    sub = parser.add_subparsers(dest="command", required=True)

    status = sub.add_parser("status", help="show the snapshot and budget")
    _add_paths(status)
    status.set_defaults(func=cmd_status)

    calibrate = sub.add_parser("calibrate", help="measure Hermes usage into budget.yaml")
    calibrate.add_argument("--profiles", nargs="*", default=None)
    calibrate.add_argument("--window", type=int, default=30)
    calibrate.add_argument("--hermes-home", default=str(DEFAULT_HOME))
    calibrate.add_argument("--out", required=True)
    calibrate.set_defaults(func=cmd_calibrate)

    refresh = sub.add_parser("refresh", help="fetch the provider into snapshot.json")
    _add_paths(refresh)
    refresh.add_argument("--url", default="https://api.surplusintelligence.ai/v1")
    refresh.add_argument("--models", default="")
    refresh.add_argument("--out", required=True)
    refresh.set_defaults(func=cmd_refresh)

    plan = sub.add_parser("plan", help="route one change and write the report")
    _add_paths(plan)
    plan.add_argument("--change", required=True)
    plan.add_argument("--baseline", default=None)
    plan.add_argument("--profile-config", default=str(DEFAULT_HOME / "config.yaml"))
    plan.add_argument("--baseline-env", default=os.environ.get("SURPLUS_BASELINE_MODEL", ""))
    plan.add_argument("--out", default=None)
    plan.add_argument("--accept-stale", action="store_true")
    plan.add_argument("--no-html", action="store_true")
    plan.set_defaults(func=cmd_plan)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "plan" and not args.out:
        args.out = str(Path(args.change) / "routing-report")
    try:
        return int(args.func(args))
    except (
        snapshot_mod.SnapshotError,
        calibration.CalibrationError,
        baseline_mod.BaselineError,
        providers.ProviderError,
        ValueError,
        FileNotFoundError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1