"""Render the decision as a versioned JSON sidecar and a standalone HTML brief.

The HTML is a rendering, never the record: everything it shows also exists in
the JSON. The two invariants the owner asked for are enforced here — every
report carries its generation time, and every cost table names its price basis.
"""

from __future__ import annotations

import html
from datetime import datetime, timezone
from typing import Iterable

from .benchmarks import BenchmarkCache
from .calibration import Budget
from .model import Decision, Price, RoutingMap, Snapshot, Tokens
from .portfolio import Portfolio, Role
from .snapshot import digest


def _money(value: float) -> str:
    if value == 0:
        return "$0"
    if value < 0.01:
        return f"${value:.5f}"
    if value < 1:
        return f"${value:.4f}"
    return f"${value:.2f}"


def _price(price) -> str:
    return f"{_money(price.input)} / {_money(price.output)}"


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value:.1f}%"


def _score(value: float | None) -> str:
    return "—" if value is None else f"{value:.1f}"


def _role_row(role: Role) -> dict:
    return {
        "role": role.name,
        "model": role.model_id,
        "reason": role.reason,
        "coding": role.coding,
        "reasoning": role.reasoning,
        "live": [role.live.input, role.live.output],
        "realised": [role.realised.input, role.realised.output],
        "realised_cache": role.realised.cache_read,
        "live_display": _price(role.live),
        "realised_display": _price(role.realised),
    }


def _monthly_cost(role: Role, budget: Budget) -> float:
    measured = budget.role(role.name)
    if measured is None:
        return 0.0
    return role.realised.cost(measured.monthly_total)


def collect_callouts(
    snapshot: Snapshot,
    budget: Budget,
    portfolio: Portfolio,
    cache: BenchmarkCache,
) -> list[dict]:
    callouts: list[dict] = []
    if not snapshot.allows_profile_writes():
        callouts.append(
            {
                "kind": "warn",
                "title": "The snapshot is stale",
                "body": (
                    f"The market snapshot is {snapshot.age_hours():.1f} hours old. "
                    "The report is provisional and profile writes are blocked until refresh."
                ),
            }
        )
    if budget.calibrated_at == "uncalibrated" or all(
        role.uncalibrated for role in budget.roles.values()
    ):
        callouts.append(
            {
                "kind": "warn",
                "title": "The budget is illustrative",
                "body": (
                    "No measured sessions were available. The monthly volumes are the "
                    "original assumptions, not your usage; run `calibrate` before trusting them."
                ),
            }
        )

    costs = {role.name: _monthly_cost(role, budget) for role in portfolio.roles}
    total = sum(costs.values()) or 1.0
    reviewer = costs.get("reviewer", 0.0) / total
    builder = costs.get("builder", 0.0) / total
    if reviewer > 0.5:
        reviewer_tokens = (
            budget.role("reviewer").monthly_total.total() if budget.role("reviewer") else 0
        )
        all_tokens = sum(role.monthly_total.total() for role in budget.roles.values()) or 1
        callouts.append(
            {
                "kind": "warn",
                "title": "The reviewer is the expensive tier",
                "body": (
                    f"Review is {reviewer * 100:.0f}% of the modelled spend on "
                    f"{reviewer_tokens / all_tokens * 100:.0f}% of the tokens. "
                    "Cutting review volume cuts more than capping the judge."
                ),
            }
        )

    illustrative = sorted(name for name, role in budget.roles.items() if role.uncalibrated)
    if illustrative and len(illustrative) < len(budget.roles):
        callouts.append(
            {
                "kind": "warn",
                "title": "Some role volumes are illustrative",
                "body": (
                    f"{', '.join(illustrative)} had no measured sessions. Their token volumes "
                    "are the labelled defaults; the other roles are measured."
                ),
            }
        )

    measured = budget.role("builder")
    if measured and measured.monthly_total.total():
        callouts.append(
            {
                "kind": "good",
                "title": "Volume is not the bill",
                "body": (
                    f"The builder carries {measured.monthly_total.total() / 1_000_000:.0f}M tokens "
                    f"for {builder * 100:.0f}% of the modelled spend."
                ),
            }
        )

    scored = [
        (market, cache.get(model_id))
        for model_id, market in snapshot.models.items()
        if cache.get(model_id) and cache.get(model_id).coding is not None
    ]
    if scored:
        market, bench = max(scored, key=lambda item: item[1].coding or 0)
        builder_role = portfolio.get("builder")
        if builder_role and builder_role.realised.blended() > 0:
            multiple = market.realised().blended() / builder_role.realised.blended()
            if multiple >= 5:
                callouts.append(
                    {
                        "kind": "warn",
                        "title": "Top of the board is the judge, not the workhorse",
                        "body": (
                            f"{market.name} scores {bench.coding:.1f} for about {multiple:.0f}x the "
                            "builder's realised price. That is why it decides and does not implement; "
                            "pay for it only where the decision is irreversible."
                        ),
                    }
                )
    return callouts


def build(
    *,
    snapshot: Snapshot,
    budget: Budget,
    portfolio: Portfolio,
    routing: RoutingMap,
    decisions: Iterable[Decision],
    cache: BenchmarkCache,
    baseline: str,
    baseline_source: str,
    generated_at: datetime | None = None,
    sources: list[dict] | None = None,
) -> dict:
    generated = generated_at or datetime.now(timezone.utc)
    decisions = list(decisions)
    market_rows = []
    for model_id, market in snapshot.models.items():
        bench = cache.get(model_id)
        market_rows.append(
            {
                "model": model_id,
                "name": market.name,
                "context": market.context,
                "coding": bench.coding if bench else None,
                "live": [market.live().input, market.live().output],
                "live_display": _price(market.live()),
                "realised": [market.realised().input, market.realised().output],
                "realised_display": _price(market.realised()),
                "list_display": _price(market.list_price),
                "median_discount": market.median_discount,
                "requests_24h": market.requests_24h,
            }
        )
    market_rows.sort(key=lambda row: (-(row["coding"] or -1), row["realised"][0]))
    costs = {role.name: round(_monthly_cost(role, budget), 2) for role in portfolio.roles}
    return {
        "schema_version": 1,
        "generated_at": generated.astimezone(timezone.utc).isoformat(timespec="seconds"),
        "title": "Model routing decision",
        "provider": snapshot.provider,
        "base_url": snapshot.base_url,
        "snapshot": {
            "fetched_at": snapshot.fetched_at.astimezone(timezone.utc).isoformat(timespec="seconds"),
            "age_hours": round(snapshot.age_hours(generated), 2),
            "freshness": snapshot.freshness(generated),
            "digest": digest(snapshot),
        },
        "pricing_basis": {
            "headline": "live best offer",
            "budget": "seven-day realised average",
            "reference": "list price (never used in a cost calculation)",
        },
        "baseline": {"model": baseline, "source": baseline_source},
        "budget": {
            "calibrated_at": budget.calibrated_at,
            "window_days": budget.window_days,
            "roles": {
                name: {
                    "monthly_total": {
                        "input": role.monthly_total.input,
                        "output": role.monthly_total.output,
                        "cache_read": role.monthly_total.cache_read,
                        "calls": role.monthly_total.calls,
                    },
                    "sessions": role.sessions,
                    "uncalibrated": role.uncalibrated,
                    "source": role.source,
                }
                for name, role in budget.roles.items()
            },
        },
        "portfolio": [_role_row(role) for role in portfolio.roles],
        "costs": {
            "roles": costs,
            "total": round(sum(costs.values()), 2),
            "currency": "USD",
            "basis": "seven-day realised average",
        },
        "tasks": [
            {
                "id": decision.task_id,
                "title": routing.tasks.get(decision.task_id).title if routing.tasks.get(decision.task_id) else "",
                "type": routing.tasks.get(decision.task_id).type if routing.tasks.get(decision.task_id) else "unclassified",
                "model": decision.model,
                "decider": decision.decider,
                "requires_review": decision.requires_review,
                "predicate": list(decision.predicate),
                "reason": decision.reason,
                "needs_scoping": decision.needs_scoping,
            }
            for decision in decisions
        ],
        "market": market_rows,
        "callouts": collect_callouts(snapshot, budget, portfolio, cache),
        "sources": sources or [],
        "method": (
            "Prices are the live best offer (headline) and the request-weighted seven-day "
            "realised average (budget), both read from the provider's order book; list price "
            "is reference only. Coding scores come from BenchLM's weighted basket; reasoning "
            "from HLE-Diamond and FrontierMath where cached. Token volumes come from the "
            "Hermes state database when calibrated, otherwise from the labelled illustrative "
            "defaults. The model and baseline that produced this report are recorded above."
        ),
    }


def _table(
    headers: list[str],
    rows: list[list[str]],
    numeric: set[int] | None = None,
    table_class: str = "",
) -> str:
    numeric = numeric or set()
    head = "".join(f"<th>{html.escape(item)}</th>" for item in headers)
    body = []
    for row in rows:
        cells = []
        for index, item in enumerate(row):
            cls = ' class="num"' if index in numeric else ""
            cells.append(f"<td{cls}>{item}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    classes = f' class="{table_class}"' if table_class else ""
    return (
        f'<div class="tablewrap"><table{classes}><thead><tr>'
        + head
        + "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
    )


def render_html(payload: dict) -> str:
    roles = payload["portfolio"]
    role_cards = []
    for role in roles:
        role_cards.append(
            f"""
      <div class="tier {html.escape(role['role'])}">
        <div class="role">{html.escape(role['role'])}</div>
        <div class="model">{html.escape(role['model'])}</div>
        <div class="job">{html.escape(role['reason'])}</div>
        <div class="price"><span>coding {_score(role['coding'])}</span></div>
        <div class="rate"><strong>{_money(role['realised'][0])}</strong> in · <strong>{_money(role['realised'][1])}</strong> out</div>
      </div>"""
        )

    callouts = []
    for callout in payload["callouts"]:
        callouts.append(
            f"""
    <div class="callout {html.escape(callout['kind'])}">
      <div class="label">{html.escape(callout['title'])}</div>
      <p>{html.escape(callout['body'])}</p>
    </div>"""
        )

    market_rows = [
        [
            html.escape(row["name"]),
            _score(row["coding"]),
            row["live_display"],
            row["realised_display"],
            row["list_display"],
            _pct(row["median_discount"]),
            f'{row["requests_24h"]:,}' if row["requests_24h"] else "—",
        ]
        for row in payload["market"]
    ]
    market_table = _table(
        [
            "Model",
            "Coding",
            "Live best $/M (in/out)",
            "7-day avg $/M (in/out)",
            "List $/M (in/out)",
            "Median off",
            "24h req",
        ],
        market_rows,
        numeric={1, 2, 3, 4, 5, 6},
        table_class="market",
    )

    task_rows = []
    for task in payload["tasks"]:
        badge = (
            '<span class="tag warn">needs scoping</span>'
            if task["needs_scoping"]
            else f'<span class="tag">{html.escape(task["type"])}</span>'
        )
        model = html.escape(task["model"])
        if task["decider"]:
            model += f'<br><span class="muted">decider: {html.escape(task["decider"])}</span>'
        task_rows.append(
            [
                html.escape(task["id"]),
                html.escape(task["title"]),
                badge,
                model,
                "yes" if task["requires_review"] else "no",
                html.escape("; ".join(task["predicate"]) or "—"),
            ]
        )
    task_table = _table(
        ["ID", "Task", "Type", "Implementer", "Review", "Predicate"],
        task_rows,
        table_class="tasks",
    )

    source_items = "".join(
        f'<li id="s{index}"><a href="{html.escape(item["url"])}">{html.escape(item["title"])}</a></li>'
        for index, item in enumerate(payload["sources"], 1)
    )

    freshness = payload["snapshot"]["freshness"]
    badge_class = {"fresh": "good", "aging": "aging", "provisional": "warn", "expired": "warn"}.get(
        freshness, "aging"
    )
    generated = payload["generated_at"].replace("T", " ").replace("+00:00", " UTC")
    fetched = payload["snapshot"]["fetched_at"].replace("T", " ").replace("+00:00", " UTC")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(payload["title"])} — {html.escape(payload["generated_at"])}</title>
<style>
  :root{{--ink:#1b1f24;--muted:#5f6b7a;--line:#dfe3e8;--accent:#0b5c8a;--soft:#eaf3f8;
        --paper:#fff;--band:#f7f6f2;--warn:#9a4a08;--warnsoft:#fdf3e7;--good:#1f6b4a;--goodsoft:#eaf5ef}}
  *{{box-sizing:border-box}}
  body{{margin:0;background:var(--band);color:var(--ink);
       font:16px/1.62 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}}
  .page{{max-width:1000px;margin:0 auto;background:var(--paper);padding:0 0 56px}}
  header{{padding:48px 60px 32px;border-bottom:1px solid var(--line);
          background:linear-gradient(180deg,#fbfaf7,#fff)}}
  .eyebrow{{font-size:11px;letter-spacing:.18em;text-transform:uppercase;color:var(--accent);
            font-weight:700;margin:0 0 12px}}
  h1{{font-family:Georgia,"Iowan Old Style",serif;font-size:40px;line-height:1.12;
      letter-spacing:-.015em;margin:0 0 14px;font-weight:600}}
  .standfirst{{font-size:18px;line-height:1.5;color:#39424e;max-width:760px;margin:0 0 22px}}
  .meta{{display:flex;flex-wrap:wrap;gap:8px 20px;font-size:13px;color:var(--muted);
         border-top:1px solid var(--line);padding-top:14px}}
  .meta strong{{color:var(--ink);font-weight:600}}
  main{{padding:0 60px}}
  section{{padding:34px 0 6px;border-bottom:1px solid var(--line)}}
  section:last-of-type{{border-bottom:0}}
  h2{{font-family:Georgia,serif;font-size:26px;line-height:1.2;margin:0 0 8px;font-weight:600}}
  .kicker{{font-size:11px;letter-spacing:.16em;text-transform:uppercase;color:var(--muted);
           font-weight:700;margin:0 0 8px}}
  p{{margin:0 0 12px}}
  .badge{{display:inline-block;padding:2px 8px;border-radius:3px;font-size:11px;
          letter-spacing:.06em;text-transform:uppercase;font-weight:700}}
  .badge.good{{background:var(--goodsoft);color:var(--good)}}
  .badge.aging{{background:var(--warnsoft);color:var(--warn)}}
  .badge.warn{{background:#f6e9ea;color:#7a1f2b}}
  .tiers{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:22px 0 8px}}
  .tier{{border:1px solid #c6ccd4;border-radius:8px;padding:14px 14px 12px;background:#fff}}
  .tier .role{{font-size:10px;letter-spacing:.14em;text-transform:uppercase;font-weight:700;color:var(--muted)}}
  .tier .model{{font-size:15px;font-weight:650;margin:5px 0 3px;line-height:1.25;word-break:break-word}}
  .tier .job{{font-size:12px;color:var(--muted);line-height:1.4;margin:4px 0 10px;min-height:64px}}
  .tier .price{{font-size:12px;border-top:1px solid var(--line);padding-top:8px;
               display:flex;justify-content:space-between;gap:6px}}
  .tier .rate{{font-size:11.5px;font-variant-numeric:tabular-nums;margin-top:1px;white-space:nowrap;color:var(--ink)}}
  .tier.judge{{border-top:4px solid #7a1f2b}}
  .tier.reviewer{{border-top:4px solid var(--accent)}}
  .tier.builder{{border-top:4px solid var(--good)}}
  .tier.runner{{border-top:4px solid #8a6d1f}}
  .tablewrap{{overflow-x:auto;margin:16px 0 8px;border:1px solid var(--line);border-radius:6px}}
  table{{border-collapse:collapse;width:100%;font-size:13.5px;line-height:1.4;background:#fff}}
  th{{text-align:left;font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);
      font-weight:700;padding:10px 11px;border-bottom:1px solid #c6ccd4;background:#fafaf8;white-space:nowrap}}
  td{{padding:10px 11px;border-bottom:1px solid var(--line);vertical-align:top}}
  tr:last-child td{{border-bottom:0}}
  tbody tr:nth-child(even) td{{background:#fcfcfb}}
  td.num,th.num{{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}}
  .note{{font-size:13px;color:var(--muted);margin-top:6px}}
  .callout{{border:1px solid #c6ccd4;border-radius:8px;padding:14px 16px;margin:12px 0;background:#fdfcf9}}
  .callout.warn{{background:var(--warnsoft);border-color:#ecd3b3}}
  .callout.good{{background:var(--goodsoft);border-color:#c8e3d4}}
  .callout .label{{font-size:10.5px;letter-spacing:.14em;text-transform:uppercase;font-weight:700;
                   margin-bottom:4px;color:var(--accent)}}
  .callout.warn .label{{color:var(--warn)}}
  .callout.good .label{{color:var(--good)}}
  .callout p{{margin:0;font-size:14.5px}}
  .tag{{display:inline-block;font-size:10px;letter-spacing:.05em;text-transform:uppercase;
        padding:2px 6px;border-radius:3px;font-weight:700;background:#f1f2f4;color:#4a5563;white-space:nowrap}}
  .tag.warn{{background:#f6e9ea;color:#7a1f2b}}
  .tasks td:nth-child(4),.tasks td:nth-child(6){{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
    font-size:11.5px;line-height:1.4}}
  .tasks td:nth-child(4){{min-width:188px}}
  .tasks td:nth-child(6){{white-space:nowrap}}
  .market td:nth-child(1){{white-space:nowrap}}
  .muted{{color:var(--muted);font-size:12px}}
  .sources{{font-size:12.5px;line-height:1.55;color:#3c4550}}
  .sources ol{{padding-left:18px;margin:12px 0 0}}
  .sources li{{margin:0 0 6px;word-break:break-word}}
  footer{{padding:28px 60px 0;color:var(--muted);font-size:12px;line-height:1.5}}
  @media (max-width:860px){{header{{padding:32px 22px 24px}}main{{padding:0 22px}}
    footer{{padding:24px 22px 0}}h1{{font-size:30px}}.tiers{{grid-template-columns:1fr 1fr}}}}
  @media print{{@page{{size:A4;margin:15mm 13mm}}body{{background:#fff}}.page{{max-width:none}}
    header{{padding:0 0 18px;background:#fff}}main{{padding:0}}footer{{padding:18px 0 0}}
    .tablewrap,.tier,.callout{{page-break-inside:avoid}}h2{{page-break-after:avoid}}
    a{{color:var(--ink)}}}}
</style>
</head>
<body>
<div class="page">
<header>
  <p class="eyebrow">Model routing brief · {html.escape(payload["provider"])}</p>
  <h1>{html.escape(payload["title"])}</h1>
  <p class="standfirst">Baseline <strong>{html.escape(payload["baseline"]["model"])}</strong>.
  Prices are live best offers; the budget column uses the seven-day realised average.</p>
  <div class="meta">
    <span><strong>Generated</strong> {html.escape(generated)}</span>
    <span><strong>Snapshot</strong> {html.escape(fetched)} · <span class="badge {badge_class}">{html.escape(freshness)} · {payload["snapshot"]["age_hours"]:.1f}h</span></span>
    <span><strong>Provider</strong> {html.escape(payload["base_url"])}</span>
    <span><strong>Digest</strong> {html.escape(payload["snapshot"]["digest"])}</span>
    <span><strong>Baseline source</strong> {html.escape(payload["baseline"]["source"])}</span>
  </div>
</header>
<main>
<section>
  <p class="kicker">The portfolio</p>
  <h2>Four roles, four jobs</h2>
  <div class="tiers">{''.join(role_cards)}</div>
  <p class="note">The judge decides, the reviewer plans and reviews, the builder implements, the runner takes the mechanical work. Role choice is heuristic; the evidence is in the JSON.</p>
</section>
{''.join(callouts)}
<section>
  <p class="kicker">01 · Market</p>
  <h2>Every price basis, kept apart</h2>
  <p>The live best is what you can buy now. The seven-day realised average is what buyers actually paid and is the only number used for the monthly budget. List price is reference and never enters a cost calculation.</p>
  {market_table}
  <p class="note">Coding score is BenchLM's weighted basket. A dash means the model has no score, not a zero. Snapshot digest {html.escape(payload["snapshot"]["digest"])}.</p>
</section>
<section>
  <p class="kicker">02 · Tasks</p>
  <h2>What runs where</h2>
  <p>Each task carries its acceptance predicate. A task without one is not routed; it is returned for scoping.</p>
  {task_table}
  <p class="note">Review is mandatory for bug fixes, refactors, security and architecture. Architecture tasks also carry a decider.</p>
</section>
<section>
  <p class="kicker">03 · Budget</p>
  <h2>Measured volume, not a guess</h2>
  <p>Monthly totals are the sum over the calibration window. Per-session and per-call percentiles size one task; they are not multiplied by the session count. Calibration: {html.escape(payload["budget"]["calibrated_at"])}, window {payload["budget"]["window_days"]} days.</p>
  {_budget_table(payload)}
</section>
<section>
  <p class="kicker">References</p>
  <h2>Sources and method</h2>
  <p>{html.escape(payload["method"])}</p>
  <div class="sources"><ol>{source_items}</ol></div>
</section>
</main>
<footer>
  <p>Generated {html.escape(generated)}. Snapshot {html.escape(fetched)} ({payload["snapshot"]["age_hours"]:.1f} hours old).</p>
  <p>Spot prices move. Re-check the order book before committing a budget; the tiering survives price changes better than any single model choice.</p>
</footer>
</div>
</body>
</html>"""


def _mtok(value: int) -> str:
    millions = value / 1_000_000
    return f"{millions:.2f}M" if millions < 10 else f"{millions:.1f}M"


def _budget_table(payload: dict) -> str:
    rows = []
    total_tokens = total_input = total_output = total_cache = 0
    for role in payload["portfolio"]:
        data = payload["budget"]["roles"].get(role["role"])
        if not data:
            continue
        total = data["monthly_total"]
        tokens = total["input"] + total["output"] + total.get("cache_read", 0)
        cost = payload["costs"]["roles"].get(role["role"], 0.0)
        total_tokens += tokens
        total_input += total["input"]
        total_output += total["output"]
        total_cache += total.get("cache_read", 0)
        rows.append(
            [
                html.escape(role["role"]),
                _mtok(tokens),
                _mtok(total["input"]),
                _mtok(total["output"]),
                _mtok(total.get("cache_read", 0)),
                role["realised_display"],
                f"${cost:,.2f}",
                "uncalibrated" if data["uncalibrated"] else f'{data["sessions"]} sessions',
            ]
        )
    rows.append(
        [
            "<strong>Total</strong>",
            f"<strong>{_mtok(total_tokens)}</strong>",
            f"<strong>{_mtok(total_input)}</strong>",
            f"<strong>{_mtok(total_output)}</strong>",
            f"<strong>{_mtok(total_cache)}</strong>",
            "",
            f'<strong>${payload["costs"]["total"]:,.2f}</strong>',
            "",
        ]
    )
    table = _table(
        [
            "Role",
            "Tokens/mo",
            "Input",
            "Output",
            "Cache read",
            "7-day $/M (in/out)",
            "Monthly $",
            "Provenance",
        ],
        rows,
        numeric={1, 2, 3, 4, 5, 6},
    )
    return (
        table
        + '<p class="note">Monthly $ includes cache reads at the provider\'s cache price; '
        "the input and output columns are uncached.</p>"
    )