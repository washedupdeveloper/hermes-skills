"""Measure a role's real token usage and turn it into a budget.

The distinction this module exists to preserve: `monthly_total` is the sum of
what was spent, while `per_session` and `per_call` are percentiles for sizing a
single task. Confusing the two understated one measured month by 67x, because a
single 66.6M-token session disappears into a median.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from . import mini_yaml
from .model import Budget, Percentiles, RoleCalibration, Tokens

SCHEMA = "session_model_usage"
DAYS_PER_MONTH = 30.0

# Only used when a role has never been measured. Marked uncalibrated; the
# report must say so. Percentiles are zero because inventing a distribution
# would be worse than admitting there is none.
ILLUSTRATIVE: dict[str, Tokens] = {
    "builder": Tokens(input=150_000_000, output=30_000_000, calls=3_000),
    "reviewer": Tokens(input=12_000_000, output=1_500_000, calls=100),
    "runner": Tokens(input=5_000_000, output=1_000_000, calls=500),
    "judge": Tokens(input=600_000, output=80_000, calls=20),
}


class CalibrationError(RuntimeError):
    """The database cannot be read or does not carry the expected table."""


def _tokens_from_rows(rows: Iterable[tuple]) -> list[Tokens]:
    result: list[Tokens] = []
    for _session, input_tokens, output_tokens, cache_read, reasoning, calls in rows:
        result.append(
            Tokens(
                input=int(input_tokens or 0),
                output=int(output_tokens or 0),
                cache_read=int(cache_read or 0),
                reasoning=int(reasoning or 0),
                calls=int(calls or 0),
            )
        )
    return result


def _percentiles(values: list[Tokens], scale: float = 1.0) -> Percentiles:
    """The P50 and P90 token bundles, selected by each sample's total.

    Summing the per-field percentiles would produce a bundle that no session
    ever had (the P50 input plus the P50 output is not the P50 total). Sort by
    the total instead, then interpolate every component between the two
    sessions that straddle the percentile.
    """
    if not values:
        return Percentiles(Tokens(), Tokens())
    ordered = sorted(values, key=lambda item: item.total())

    def at(fraction: float) -> Tokens:
        position = (len(ordered) - 1) * fraction
        lower = int(position)
        upper = min(lower + 1, len(ordered) - 1)
        weight = position - lower
        left, right = ordered[lower], ordered[upper]

        def blend(name: str) -> int:
            a = getattr(left, name)
            b = getattr(right, name)
            return round((a + (b - a) * weight) * scale)

        return Tokens(
            input=blend("input"),
            output=blend("output"),
            cache_read=blend("cache_read"),
            reasoning=blend("reasoning"),
            calls=blend("calls"),
        )

    return Percentiles(p50=at(0.5), p90=at(0.9))


def measure(
    role: str,
    db_path: str | Path,
    *,
    window_days: int = 30,
    month_days: float = DAYS_PER_MONTH,
    now: datetime | None = None,
) -> RoleCalibration:
    """Read one profile's sessions and return its measured budget.

    `per_call` is the distribution of *session-average* call size, not of
    individual calls: the usage table stores session sums, and inventing a
    per-call distribution from them would be a different measurement wearing
    the same name. It is useful for sizing one call; it is not a P90 call.

    Raises CalibrationError when the file is absent, unreadable, or lacks the
    usage table. A missing table is a schema change, not an empty month.
    """
    path = Path(db_path)
    if not path.is_file():
        raise CalibrationError(f"no state database at {path}")
    now = now or datetime.now(timezone.utc)
    if month_days <= 0:
        raise CalibrationError("month_days must be positive")
    cutoff = now.timestamp() - window_days * 86400
    try:
        uri = path.resolve().as_uri() + "?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
    except (sqlite3.Error, OSError, ValueError) as exc:
        raise CalibrationError(f"cannot open {path}: {exc}") from exc
    try:
        check = connection.execute(
            "select name from sqlite_master where type='table' and name=?",
            (SCHEMA,),
        ).fetchone()
        if check is None:
            raise CalibrationError(
                f"{path} has no {SCHEMA} table; the Hermes schema changed"
            )
        rows = connection.execute(
            f"""
            select session_id,
                   sum(input_tokens), sum(output_tokens),
                   sum(cache_read_tokens), sum(reasoning_tokens),
                   sum(api_call_count)
            from {SCHEMA}
            where last_seen >= ?
            group by session_id
            """,
            (cutoff,),
        ).fetchall()
    except sqlite3.Error as exc:
        raise CalibrationError(f"cannot read {path}: {exc}") from exc
    finally:
        connection.close()

    sessions = _tokens_from_rows(rows)
    if not sessions:
        return _uncalibrated(role, window_days, f"{path} (no sessions in window)")

    total = Tokens()
    for session in sessions:
        total = total + session
    scale = month_days / window_days if window_days else 1.0
    total = total.scaled(scale)

    per_call_values: list[Tokens] = []
    for session in sessions:
        calls = session.calls or 0
        if calls <= 0:
            continue
        per_call_values.append(
            Tokens(
                input=session.input / calls,
                output=session.output / calls,
                cache_read=session.cache_read / calls,
                reasoning=session.reasoning / calls,
                calls=1,
            )
        )
    per_call = _percentiles(per_call_values) if per_call_values else Percentiles(Tokens(), Tokens())

    return RoleCalibration(
        role=role,
        monthly_total=total,
        per_session=_percentiles(sessions),
        per_call=per_call,
        sessions=len(sessions),
        window_days=window_days,
        source=str(path),
        uncalibrated=False,
    )


def _uncalibrated(role: str, window_days: int, source: str) -> RoleCalibration:
    total = ILLUSTRATIVE.get(role, Tokens())
    return RoleCalibration(
        role=role,
        monthly_total=total,
        per_session=Percentiles(Tokens(), Tokens()),
        per_call=Percentiles(Tokens(), Tokens()),
        sessions=0,
        window_days=window_days,
        source=source,
        uncalibrated=True,
    )


def build_budget(
    roles: Iterable[RoleCalibration],
    *,
    calibrated_at: str | None = None,
    window_days: int = 30,
) -> Budget:
    return Budget(
        roles={role.role: role for role in roles},
        calibrated_at=calibrated_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        window_days=window_days,
    )


def default_budget(window_days: int = 30) -> Budget:
    roles = [
        _uncalibrated(role, window_days, "illustrative")
        for role in ("builder", "reviewer", "runner", "judge")
    ]
    return build_budget(roles, calibrated_at="uncalibrated", window_days=window_days)


def _tokens_dict(tokens: Tokens) -> dict[str, int]:
    return {
        "input": tokens.input,
        "output": tokens.output,
        "cache_read": tokens.cache_read,
        "reasoning": tokens.reasoning,
        "calls": tokens.calls,
    }


def budget_to_dict(budget: Budget) -> dict:
    roles = {}
    for name, role in budget.roles.items():
        roles[name] = {
            "monthly_total": _tokens_dict(role.monthly_total),
            "per_session": {
                "p50": _tokens_dict(role.per_session.p50),
                "p90": _tokens_dict(role.per_session.p90),
            },
            "per_call": {
                "p50": _tokens_dict(role.per_call.p50),
                "p90": _tokens_dict(role.per_call.p90),
            },
            "sessions": role.sessions,
            "window_days": role.window_days,
            "source": role.source,
            "uncalibrated": role.uncalibrated,
        }
    return {
        "schema": 1,
        "calibrated_at": budget.calibrated_at,
        "window_days": budget.window_days,
        "roles": roles,
    }


def save_budget(budget: Budget, path: str | Path) -> None:
    Path(path).write_text(mini_yaml.dumps(budget_to_dict(budget)), encoding="utf-8")


def _tokens_from_dict(data: dict | None) -> Tokens:
    data = data or {}
    return Tokens(
        input=int(data.get("input", 0)),
        output=int(data.get("output", 0)),
        cache_read=int(data.get("cache_read", 0)),
        reasoning=int(data.get("reasoning", 0)),
        calls=int(data.get("calls", 0)),
    )


def budget_from_dict(data: dict) -> Budget:
    roles: dict[str, RoleCalibration] = {}
    for name, role in (data.get("roles") or {}).items():
        per_session = role.get("per_session") or {}
        per_call = role.get("per_call") or {}
        roles[name] = RoleCalibration(
            role=name,
            monthly_total=_tokens_from_dict(role.get("monthly_total")),
            per_session=Percentiles(
                p50=_tokens_from_dict(per_session.get("p50")),
                p90=_tokens_from_dict(per_session.get("p90")),
            ),
            per_call=Percentiles(
                p50=_tokens_from_dict(per_call.get("p50")),
                p90=_tokens_from_dict(per_call.get("p90")),
            ),
            sessions=int(role.get("sessions", 0)),
            window_days=int(role.get("window_days", data.get("window_days", 30))),
            source=str(role.get("source", "")),
            uncalibrated=bool(role.get("uncalibrated", False)),
        )
    return Budget(
        roles=roles,
        calibrated_at=str(data.get("calibrated_at", "uncalibrated")),
        window_days=int(data.get("window_days", 30)),
    )


def load_budget(path: str | Path) -> Budget:
    text = Path(path).read_text(encoding="utf-8")
    return budget_from_dict(mini_yaml.loads(text))