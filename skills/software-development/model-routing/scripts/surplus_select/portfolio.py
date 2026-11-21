"""Choose a role portfolio from measured prices and published scores.

Rules, in the order they bind:

1. Only a model with a live offer can fill a role. A model with no current
   offer is listed in the report and cannot be selected.
2. For the worker roles, drop every model that another model beats on both
   axes *at the role's own measured volume*: at least as high a coding score
   for no more money. A model that is only cheap at a volume it never sees is
   not cheaper, and a blend would hide that.
3. The judge is the best combined coding and hard-reasoning score among live
   models. Price is a tie-breaker only; this tier is rare by construction.
4. The builder is the ambient baseline. It is a fact about the host, not a
   recommendation.
5. The reviewer is the builder unless a review budget is set. A different model
   must beat the builder by `min_gain` on coding (5% by default), fit the
   budget at the measured review volume, and be the cheapest model that does.
   A budget is a cap, not a target.
6. The runner is the builder unless another live model costs less at the
   runner's own measured volume and clears 65.

Roles are prompts and budgets, not a requirement for four models.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

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
    available: bool = True


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
    cost: Callable[[tuple[str, ModelMarket, Benchmark]], float],
) -> dict[str, str]:
    """Map each dominated model to the best model that dominates it.

    A dominates B when A scores at least as high and costs no more at the
    volume being priced, with one strict inequality. The dominator is chosen
    deterministically: highest coding, then cheapest, then model id.
    """
    rejected: dict[str, str] = {}
    for item in candidates:
        model_id, _, bench = item
        own_cost = cost(item)
        dominators = []
        for other in candidates:
            if other[0] == model_id:
                continue
            other_coding = other[2].coding or 0.0
            coding = bench.coding or 0.0
            if other_coding < coding:
                continue
            other_cost = cost(other)
            if other_cost > own_cost:
                continue
            if other_coding > coding or other_cost < own_cost:
                dominators.append(other)
        if dominators:
            best = min(
                dominators,
                key=lambda other: (-(other[2].coding or 0.0), cost(other), other[0]),
            )
            rejected[model_id] = best[0]
    return rejected


def choose(
    cache: BenchmarkCache,
    snapshot: Snapshot,
    baseline: str,
    *,
    min_context: int = 128_000,
    review_budget_usd: float | None = None,
    review_tokens: Tokens | None = None,
    runner_tokens: Tokens | None = None,
    builder_tokens: Tokens | None = None,
    judge_tokens: Tokens | None = None,
    min_gain: float = DEFAULT_MIN_GAIN,
) -> Portfolio:
    if min_gain < 0 or min_gain > 1:
        raise ValueError("min_gain must be between 0 and 1")
    if review_budget_usd is not None and review_budget_usd < 0:
        raise ValueError("review_budget_usd must be non-negative")

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

    priced = [item for item in candidates if item[1].best is not None]
    if not priced:
        raise ValueError("no model has a live offer; refresh the market snapshot")

    def cost(item: tuple[str, ModelMarket, Benchmark], tokens: Tokens | None) -> float:
        if tokens is not None and tokens.total() > 0:
            return item[1].realised().cost(tokens)
        return _blend(item[1].realised())

    def review_cost(item: tuple[str, ModelMarket, Benchmark]) -> float:
        return cost(item, review_tokens)

    def judge_key(item: tuple[str, ModelMarket, Benchmark]) -> float:
        bench = item[2]
        return (bench.coding or 0) * 0.6 + _reasoning(bench) * 0.4

    # The judge is chosen from every live model, not the review frontier: a
    # model can be expensive at review volume and still be the best decision
    # model, and price is only a tie-breaker here.
    judge_id, judge_market, judge_bench = min(
        priced,
        key=lambda item: (-judge_key(item), cost(item, judge_tokens), item[0]),
    )

    rejected = _dominated(priced, review_cost)
    frontier_items = [item for item in priced if item[0] not in rejected]
    by_id = {item[0]: item for item in frontier_items}

    builder_id: str
    if baseline in by_id:
        builder_id, builder_market, builder_bench = by_id[baseline]
        builder_reason = "ambient baseline"
    elif baseline in {item[0] for item in candidates}:
        builder_id, builder_market, builder_bench = next(
            item for item in candidates if item[0] == baseline
        )
        builder_reason = "ambient baseline (no live offer; cost is an estimate)"
    else:
        eligible = [item for item in frontier_items if (item[2].coding or 0) >= 70] or frontier_items
        builder_id, builder_market, builder_bench = min(
            eligible,
            key=lambda item: (
                -((item[2].coding or 0.0) / max(cost(item, builder_tokens), 0.0001)),
                -(item[2].coding or 0.0),
                cost(item, builder_tokens),
                item[0],
            ),
        )
        builder_reason = "best coding per dollar above 70 (baseline absent from the market)"

    builder_coding = builder_bench.coding or 0.0
    threshold = builder_coding * (1 + min_gain)

    upgrades = [
        item
        for item in frontier_items
        if item[0] not in (builder_id, judge_id)
        and (item[2].coding or 0) >= threshold
    ]
    reviewer_id = builder_id
    reviewer_reason = (
        "builder model under a separate review rubric; no review premium budget is set"
    )
    reviewer_market = builder_market
    reviewer_bench = builder_bench
    if review_budget_usd and review_budget_usd > 0:
        if review_tokens is None or review_tokens.total() == 0:
            raise ValueError("review_tokens is required when a review budget is set")
        affordable = [
            item for item in upgrades if cost(item, review_tokens) <= review_budget_usd
        ]
        if affordable:
            # A budget is a cap, not a target: take the cheapest model that
            # clears the materiality bar, not the most expensive one that fits.
            reviewer_id, reviewer_market, reviewer_bench = min(
                affordable,
                key=lambda item: (
                    cost(item, review_tokens),
                    -(item[2].coding or 0.0),
                    item[0],
                ),
            )
            gain = (reviewer_bench.coding or 0) - builder_coding
            reviewer_reason = (
                f"+{gain:.1f} coding points for "
                f"${cost((reviewer_id, reviewer_market, reviewer_bench), review_tokens):.2f}/mo "
                "(cheapest material upgrade)"
            )
        else:
            reviewer_reason = (
                f"no model is both {min_gain:.0%} better and within "
                f"${review_budget_usd:.0f}/mo"
            )

    runner_id = builder_id
    runner_market = builder_market
    runner_bench = builder_bench
    runner_reason = (
        "no separate runner: the builder is already the cheapest non-dominated model"
    )
    runner_candidates = [
        item
        for item in frontier_items
        if item[0] not in (builder_id, judge_id, reviewer_id)
        and (item[2].coding or 0) >= RUNNER_FLOOR
        and (
            cost(item, runner_tokens) < cost(
                (builder_id, builder_market, builder_bench), runner_tokens
            )
        )
    ]
    if runner_candidates:
        runner_id, runner_market, runner_bench = min(
            runner_candidates,
            key=lambda item: (
                cost(item, runner_tokens),
                -(item[2].coding or 0.0),
                item[0],
            ),
        )
        runner_reason = "cheaper at the measured runner volume, clearing 65"

    def role(
        name: str,
        model_id: str,
        market: ModelMarket,
        bench: Benchmark,
        reason: str,
        *,
        available: bool = True,
    ) -> Role:
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
            available=available,
        )

    return Portfolio(
        roles=(
            role("judge", judge_id, judge_market, judge_bench,
                 "best combined coding and hard reasoning among live models"),
            role("reviewer", reviewer_id, reviewer_market, reviewer_bench, reviewer_reason),
            role("builder", builder_id, builder_market, builder_bench, builder_reason,
                 available=builder_market.best is not None),
            role("runner", runner_id, runner_market, runner_bench, runner_reason),
        ),
        frontier=tuple(item[0] for item in frontier_items),
        rejected=rejected,
    )