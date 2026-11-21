"""Choose a role portfolio from measured prices and published scores.

The rules are deliberately blunt and explainable:

- judge: the best combined coding and hard-reasoning score; price is not a tie-breaker.
- reviewer: the best coding per realised dollar on the affordable frontier (at most 75% of the judge's price),
  which avoids paying 6x for one extra benchmark point.
- builder: the ambient baseline when it is in the market; otherwise the best coding per dollar above 70.
- runner: the cheapest model with a coding score of at least 65, excluding the builder.

They are heuristics, and the report says so. Their job is to put a defensible
default on the page, not to pretend a single composite settles the choice.
"""

from __future__ import annotations

from dataclasses import dataclass

from .benchmarks import Benchmark, BenchmarkCache
from .model import ModelMarket, Price, Snapshot


@dataclass(frozen=True, slots=True)
class Role:
    name: str
    model_id: str
    reason: str
    coding: float | None
    reasoning: float | None
    live: Price
    realised: Price


@dataclass(frozen=True, slots=True)
class Portfolio:
    roles: tuple[Role, ...]

    def get(self, name: str) -> Role | None:
        for role in self.roles:
            if role.name == name:
                return role
        return None


def _blend(price: Price) -> float:
    return price.blended(0.2)


def _reasoning(bench: Benchmark) -> float:
    if bench.hle is not None and bench.frontier_math is not None:
        return (bench.hle + bench.frontier_math) / 2
    if bench.hle is not None:
        return bench.hle
    if bench.frontier_math is not None:
        return bench.frontier_math
    return bench.coding or 0.0


def choose(
    cache: BenchmarkCache,
    snapshot: Snapshot,
    baseline: str,
    *,
    min_context: int = 128_000,
) -> Portfolio:
    candidates: list[tuple[str, ModelMarket, Benchmark]] = []
    for model_id, market in snapshot.models.items():
        bench = cache.get(model_id)
        if bench is None or bench.coding is None:
            continue
        if market.context and market.context < min_context:
            continue
        candidates.append((model_id, market, bench))
    if not candidates:
        raise ValueError("no model has both a market price and a coding score")

    def judge_key(item: tuple[str, ModelMarket, Benchmark]) -> float:
        bench = item[2]
        return (bench.coding or 0) * 0.6 + _reasoning(bench) * 0.4

    judge_id, judge_market, judge_bench = max(candidates, key=judge_key)
    judge_blend = _blend(judge_market.realised())

    by_id = {item[0]: item for item in candidates}
    builder_coding = (by_id[baseline][2].coding or 0.0) if baseline in by_id else 0.0

    reviewers = [item for item in candidates if item[0] != judge_id]
    affordable = [
        item for item in reviewers if _blend(item[1].realised()) <= judge_blend * 0.75
    ]
    pool = affordable or reviewers
    floor = builder_coding + 2
    band = [
        item for item in pool if (item[2].coding or 0) >= floor and item[0] != baseline
    ]
    if not band:
        band = [item for item in pool if item[0] != baseline] or pool
    reviewer_id, reviewer_market, reviewer_bench = min(
        band, key=lambda item: _blend(item[1].realised())
    )

    if baseline in by_id:
        builder_id, builder_market, builder_bench = by_id[baseline]
        builder_reason = "ambient baseline"
    else:
        eligible = [item for item in candidates if (item[2].coding or 0) >= 70] or candidates
        builder_id, builder_market, builder_bench = max(
            eligible,
            key=lambda item: (item[2].coding or 0) / max(_blend(item[1].realised()), 0.0001),
        )
        builder_reason = "best coding per dollar above 70 (baseline absent from the market)"

    runners = [
        item
        for item in candidates
        if item[0] not in (builder_id, judge_id, reviewer_id) and (item[2].coding or 0) >= 65
    ]
    if runners:
        runner_id, runner_market, runner_bench = min(
            runners, key=lambda item: _blend(item[1].realised())
        )
        runner_reason = "cheapest non-builder, non-judge, non-reviewer model clearing 65"
    else:
        runner_id = builder_id
        runner_market = builder_market
        runner_bench = builder_bench
        runner_reason = "no separate model cleared the 65 floor"

    def role(name: str, model_id: str, market: ModelMarket, bench: Benchmark, reason: str) -> Role:
        return Role(
            name=name,
            model_id=model_id,
            reason=reason,
            coding=bench.coding,
            reasoning=_reasoning(bench) if bench.hle is not None or bench.frontier_math is not None else None,
            live=market.live(),
            realised=market.realised(),
        )

    return Portfolio(
        roles=(
            role("judge", judge_id, judge_market, judge_bench, "best combined coding and hard reasoning"),
            role(
                "reviewer",
                reviewer_id,
                reviewer_market,
                reviewer_bench,
                "cheapest model at least two points above the builder",
            ),
            role("builder", builder_id, builder_market, builder_bench, builder_reason),
            role("runner", runner_id, runner_market, runner_bench, runner_reason),
        )
    )