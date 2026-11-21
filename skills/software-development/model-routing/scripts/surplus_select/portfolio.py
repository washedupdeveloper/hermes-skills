"""Choose a role portfolio from measured prices and published scores.

The rules are deliberately blunt and explainable, and they are ordered so a
dominated model can never be selected:

1. Drop every model that another model beats on both axes: at least as good a
   coding score for at least as low a realised price. A worse model at a higher
   price has no role on any team.
2. The judge is the best combined coding and hard-reasoning score on the
   frontier. Price is not a tie-breaker; this tier is rare by construction.
3. The builder is the ambient baseline. It is a fact about the host, not a
   recommendation.
4. The reviewer is the builder unless a review budget is set. A different model
   must clear two gates: at least `min_gain` better on the coding basket (5% by
   default; below that the difference is treated as immaterial) and fit the
   monthly review budget at the measured review volume.
5. The runner is the builder unless a cheaper frontier model clears 65. If no
   model is cheaper, a separate runner tier buys nothing.

Roles are prompts and budgets, not a requirement for four models. Three roles
sharing one model is a valid and often the rational outcome.
"""

from __future__ import annotations

from dataclasses import dataclass

from .benchmarks import Benchmark, BenchmarkCache
from .model import ModelMarket, Price, Snapshot, Tokens

DEFAULT_MIN_GAIN = 0.05
RUNNER_FLOOR = 65.0


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
    frontier: tuple[str, ...] = ()
    rejected: dict[str, str] | None = None

    def get(self, name: str) -> Role | None:
        for role in self.roles:
            if role.name == name:
                return role
        return None

    def model_ids(self) -> tuple[str, ...]:
        return tuple(role.model_id for role in self.roles)


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


def _dominated(
    candidates: list[tuple[str, ModelMarket, Benchmark]],
) -> dict[str, str]:
    """Map each dominated model to the model that dominates it.

    A dominates B when A is at least as good and at least as cheap, and
    strictly better on one axis. Equal models do not dominate each other.
    """
    rejected: dict[str, str] = {}
    for model_id, market, bench in candidates:
        coding = bench.coding or 0.0
        price = _blend(market.realised())
        for other_id, other_market, other_bench in candidates:
            if other_id == model_id:
                continue
            other_coding = other_bench.coding or 0.0
            other_price = _blend(other_market.realised())
            if (
                other_coding >= coding
                and other_price <= price
                and (other_coding > coding or other_price < price)
            ):
                rejected[model_id] = other_id
                break
    return rejected


def choose(
    cache: BenchmarkCache,
    snapshot: Snapshot,
    baseline: str,
    *,
    min_context: int = 128_000,
    review_budget_usd: float | None = None,
    review_tokens: Tokens | None = None,
    min_gain: float = DEFAULT_MIN_GAIN,
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

    rejected = _dominated(candidates)
    frontier = [item for item in candidates if item[0] not in rejected]
    if not frontier:
        raise ValueError("every model is dominated; the benchmark or price data is inconsistent")
    by_id = {item[0]: item for item in frontier}

    def judge_key(item: tuple[str, ModelMarket, Benchmark]) -> float:
        bench = item[2]
        return (bench.coding or 0) * 0.6 + _reasoning(bench) * 0.4

    judge_id, judge_market, judge_bench = max(frontier, key=judge_key)

    if baseline in by_id:
        builder_id, builder_market, builder_bench = by_id[baseline]
        builder_reason = "ambient baseline"
    elif baseline in {item[0] for item in candidates}:
        builder_id, builder_market, builder_bench = next(
            item for item in candidates if item[0] == baseline
        )
        builder_reason = "ambient baseline (dominated by a scored model, but kept as the fact)"
    else:
        eligible = [
            item for item in frontier if (item[2].coding or 0) >= 70
        ] or frontier
        builder_id, builder_market, builder_bench = max(
            eligible,
            key=lambda item: (item[2].coding or 0) / max(_blend(item[1].realised()), 0.0001),
        )
        builder_reason = "best coding per dollar above 70 (baseline absent from the market)"

    builder_coding = builder_bench.coding or 0.0
    threshold = builder_coding * (1 + min_gain)

    upgrades = [
        item
        for item in frontier
        if item[0] not in (builder_id, judge_id)
        and (item[2].coding or 0) >= threshold
    ]
    reviewer_id = builder_id
    reviewer_reason = (
        "builder model under a separate review rubric; no review premium budget is set"
    )
    if review_budget_usd and review_budget_usd > 0:
        if review_tokens is None:
            raise ValueError("review_tokens is required when a review budget is set")
        affordable = [
            item
            for item in upgrades
            if item[1].realised().cost(review_tokens) <= review_budget_usd
        ]
        if affordable:
            reviewer_id, reviewer_market, reviewer_bench = max(
                affordable, key=lambda item: item[2].coding or 0
            )
            gain = (reviewer_bench.coding or 0) - builder_coding
            reviewer_reason = (
                f"+{gain:.1f} coding points for "
                f"${reviewer_market.realised().cost(review_tokens):.2f}/mo"
            )
        else:
            reviewer_market = builder_market
            reviewer_bench = builder_bench
            reviewer_reason = (
                f"no model is both {min_gain:.0%} better and within "
                f"${review_budget_usd:.0f}/mo"
            )
    else:
        reviewer_market = builder_market
        reviewer_bench = builder_bench

    runners = [
        item
        for item in frontier
        if item[0] not in (builder_id, judge_id, reviewer_id)
        and (item[2].coding or 0) >= RUNNER_FLOOR
        and _blend(item[1].realised()) < _blend(builder_market.realised())
    ]
    if runners:
        runner_id, runner_market, runner_bench = min(
            runners, key=lambda item: _blend(item[1].realised())
        )
        runner_reason = "cheaper non-dominated model clearing 65"
    else:
        runner_id = builder_id
        runner_market = builder_market
        runner_bench = builder_bench
        runner_reason = (
            "no separate runner: the builder is already the cheapest non-dominated model"
        )

    def role(name: str, model_id: str, market: ModelMarket, bench: Benchmark, reason: str) -> Role:
        return Role(
            name=name,
            model_id=model_id,
            reason=reason,
            coding=bench.coding,
            reasoning=(
                _reasoning(bench)
                if bench.hle is not None or bench.frontier_math is not None
                else None
            ),
            live=market.live(),
            realised=market.realised(),
        )

    return Portfolio(
        roles=(
            role("judge", judge_id, judge_market, judge_bench,
                 "best combined coding and hard reasoning on the frontier"),
            role("reviewer", reviewer_id, reviewer_market, reviewer_bench, reviewer_reason),
            role("builder", builder_id, builder_market, builder_bench, builder_reason),
            role("runner", runner_id, runner_market, runner_bench, runner_reason),
        ),
        frontier=tuple(item[0] for item in frontier),
        rejected=rejected,
    )