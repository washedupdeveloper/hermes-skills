"""Plain data for the selector: prices, markets, tasks, decisions, calibration.

Every type here is immutable and free of I/O. Modules that read the network,
the state database or a profile return these; modules that decide consume them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(frozen=True, slots=True)
class Price:
    """US dollars per million tokens."""

    input: float
    output: float
    cache_read: float | None = None

    def cost(self, tokens: "Tokens") -> float:
        """Cost of a token bundle at this price.

        `Tokens.output` already includes `Tokens.reasoning` in the Hermes usage
        schema: reconstructing the recorded `estimated_cost_usd` matches exactly
        when reasoning is excluded and fails when it is added. A cache read with
        no published cache price is billed at the input price; treating it as
        free would understate every cache-heavy role.
        """
        total = tokens.input * self.input + tokens.output * self.output
        cache_price = self.cache_read if self.cache_read is not None else self.input
        total += tokens.cache_read * cache_price
        return total / 1_000_000

    def blended(self, output_share: float = 0.2) -> float:
        """One number for ranking only; never for a report."""
        return self.input * (1 - output_share) + self.output * output_share


@dataclass(frozen=True, slots=True)
class Offer:
    """One seller's listing for a model."""

    provider: str
    price: Price
    discount: float | None = None
    success: float | None = None
    latency_p50: float | None = None
    sold: float | None = None


@dataclass(frozen=True, slots=True)
class ModelMarket:
    """One model as the market shows it, with all four price bases kept apart."""

    model_id: str
    name: str
    context: int
    list_price: Price
    best: Price | None = None
    best_discount: float | None = None
    median_discount: float | None = None
    realised_discount: float | None = None
    requests_24h: int | None = None
    offers: tuple[Offer, ...] = ()

    def live(self) -> Price:
        """The price a caller can buy at now; list when no offer is known.

        The order book publishes input and output only, so a live offer with no
        cache price inherits the catalog's. Dropping it would bill cache reads
        at zero for the role that carries the most of them.
        """
        if self.best is None:
            return self.list_price
        if self.best.cache_read is None and self.list_price.cache_read is not None:
            return Price(self.best.input, self.best.output, self.list_price.cache_read)
        return self.best

    def realised(self) -> Price:
        """The request-weighted average, used for budgets."""
        if self.realised_discount is None:
            return self.live()
        keep = 1 - self.realised_discount / 100
        return Price(
            input=round(self.list_price.input * keep, 6),
            output=round(self.list_price.output * keep, 6),
            cache_read=(
                round(self.list_price.cache_read * keep, 6)
                if self.list_price.cache_read is not None
                else None
            ),
        )


@dataclass(frozen=True, slots=True)
class Snapshot:
    """A dated view of one provider's market. The only input the router prices from."""

    provider: str
    base_url: str
    fetched_at: datetime
    capabilities: dict[str, bool] = field(default_factory=dict)
    models: dict[str, ModelMarket] = field(default_factory=dict)
    source_hashes: dict[str, str] = field(default_factory=dict)

    def age_hours(self, now: datetime | None = None) -> float:
        now = now or datetime.now(timezone.utc)
        fetched = self.fetched_at
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=timezone.utc)
        return (now - fetched).total_seconds() / 3600

    def freshness(self, now: datetime | None = None) -> str:
        """fresh / aging / provisional / expired, per the design's ladder."""
        age = self.age_hours(now)
        if age <= 12:
            return "fresh"
        if age <= 48:
            return "aging"
        if age <= 24 * 7:
            return "provisional"
        return "expired"

    def allows_profile_writes(self, now: datetime | None = None) -> bool:
        return self.freshness(now) in ("fresh", "aging")

    def allows_ranking(self, now: datetime | None = None) -> bool:
        return self.freshness(now) != "expired"


@dataclass(frozen=True, slots=True)
class Tokens:
    """A token bundle. Reasoning bills as output and is tracked separately."""

    input: int = 0
    output: int = 0
    cache_read: int = 0
    reasoning: int = 0
    calls: int = 0

    def __add__(self, other: "Tokens") -> "Tokens":
        return Tokens(
            input=self.input + other.input,
            output=self.output + other.output,
            cache_read=self.cache_read + other.cache_read,
            reasoning=self.reasoning + other.reasoning,
            calls=self.calls + other.calls,
        )

    def scaled(self, factor: float) -> "Tokens":
        return Tokens(
            input=round(self.input * factor),
            output=round(self.output * factor),
            cache_read=round(self.cache_read * factor),
            reasoning=round(self.reasoning * factor),
            calls=round(self.calls * factor),
        )

    def total(self) -> int:
        """Billable tokens. Reasoning is a subset of output, not an extra."""
        return self.input + self.output + self.cache_read


@dataclass(frozen=True, slots=True)
class Percentiles:
    p50: Tokens
    p90: Tokens


@dataclass(frozen=True, slots=True)
class RoleCalibration:
    """Measured volumes for one role. `monthly_total` is a sum; percentiles size one task."""

    role: str
    monthly_total: Tokens
    per_session: Percentiles
    per_call: Percentiles
    sessions: int
    window_days: int
    source: str
    uncalibrated: bool = False


@dataclass(frozen=True, slots=True)
class Budget:
    roles: dict[str, RoleCalibration]
    calibrated_at: str
    window_days: int

    def role(self, name: str) -> RoleCalibration | None:
        return self.roles.get(name)


@dataclass(frozen=True, slots=True)
class TaskSpec:
    """One routable unit of work from a change's tasks.md."""

    id: str
    title: str
    type: str
    verify: tuple[str, ...] = ()
    notes: str = ""


@dataclass(frozen=True, slots=True)
class RoutingMap:
    change: str
    tasks: dict[str, TaskSpec]
    path: str = ""


@dataclass(frozen=True, slots=True)
class Decision:
    """One routing outcome. `model` is the implementer; `decider` may differ."""

    task_id: str
    model: str
    decider: str | None
    tier: str
    requires_review: bool
    predicate: tuple[str, ...]
    reason: str
    needs_scoping: bool = False
    budget_usd: float | None = None
    reviewer: str | None = None
