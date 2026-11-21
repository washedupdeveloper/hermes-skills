---
name: model-routing
description: "Use when picking a model stack for code."
version: 0.1.0
author: "Storm / Hermes"
license: MIT
platforms: [linux, macos, windows]
category: software-development
metadata:
  hermes:
    tags: [models, routing, pricing, coding, benchmarks, openspec, council]
---

# Model routing selector

Answers one question: **which model should do this task, and what does that
cost at the prices actually available?** It is deliberately not a chat tool and
not an LLM call. The decision is a pure function over a dated price snapshot, a
calibrated token budget, and a cached benchmark table.

## Quick start

Set the skill directory once. It is the directory containing this file.

```bash
S="${HERMES_HOME:-$HOME/.hermes}/skills/software-development/model-routing"
STATE="${HERMES_HOME:-$HOME/.hermes}/cache/surplus-select"
mkdir -p "$STATE"
```

Calibrate from Hermes' own state database (read-only), then price the market,
then route a change:

```bash
python3 "$S/scripts/run.py" calibrate \
  --hermes-home "${HERMES_HOME:-$HOME/.hermes}" --window 30 \
  --out "$STATE/budget.yaml"

python3 "$S/scripts/run.py" refresh \
  --url https://api.surplusintelligence.ai/v1 \
  --out "$STATE/snapshot.json"

python3 "$S/scripts/run.py" plan \
  --change openspec/changes/<change-name> \
  --out "$STATE/report"

# Optional: authorise an independent reviewer up to $80/month.
# Without this, the builder model reviews under a separate rubric.
python3 "$S/scripts/run.py" plan \
  --change openspec/changes/<change-name> \
  --review-budget 80 \
  --out "$STATE/report-independent"
```

`plan` reads `routing.yaml` from the change when present; otherwise it drafts
one from `tasks.md` by tagging each task. It writes `report.json` and
`report.html`. The JSON is the record; the HTML is the shareable rendering.

## The four roles

| Role | Rule | What it is allowed to do |
|---|---|---|
| **judge** | Best combined coding and hard-reasoning score on the frontier; price is not a tie-breaker | Architecture decisions only. Never implements. |
| **reviewer** | The builder model by default. A different model only when `--review-budget` is set, it is at least 5% better on coding, and its measured monthly cost fits that budget | Checks and plans. Never writes the patch. |
| **builder** | The ambient baseline when it is in the market | Implements every task. |
| **runner** | The builder model unless a cheaper non-dominated model clears 65 | Mechanical and test work. |

### Dominance and materiality

Before any role is filled, a model that another model beats on **both** axes is
removed: at least as high a coding score for at least as low a realised price.
A worse model at a higher price is not a tier and cannot be selected.

The reviewer is the builder model unless a review budget is set. A different
reviewer must clear both gates:

1. **Materiality** — at least `--min-gain` better on the coding basket, 5% by
   default. A 3.6-point gain on a 76.4 baseline is 4.7%; it is rejected as
   immaterial, not because the model is bad.
2. **Budget** — its monthly cost at the measured review volume must fit
   `--review-budget`. The default is `0`, which means the builder model reviews
   under a separate rubric. That is a consistency check, not an independent
   reviewer.

A role is a prompt and a budget. Three roles sharing one model is a valid and
often the rational outcome.

The judge is the "most capable, least used" tier: it is attached as `decider`
to `architecture` tasks and nothing else. The reviewer is a volume role; it
defaults to the builder and only buys a different model when the materiality
and budget gates both pass.

## The four price bases

Never mix these in one number.

| Basis | Meaning | Used for |
|---|---|---|
| **list** | Provider's reference price | Reference only; never a cost calculation |
| **live best** | Cheapest offer on the book now | Headline table and "what can I buy" |
| **7-day realised** | Request-weighted average actually paid | Every monthly budget figure |
| **median discount** | Middle of the live offers | Liquidity check; a low value means thin supply |

A model with no live offer is still listed, but it cannot be recommended.
`requests_24h` is the availability signal: a model with 147 requests/day is
sellable; one with 0 is not.

## Freshness ladder

| Age | State | Effect |
|---|---|---|
| ≤ 12 h | fresh | Full report; profile writes allowed |
| 12–48 h | aging | One-line note; profile writes allowed |
| 48 h–7 d | provisional | Report is provisional; no profile writes |
| > 7 d | expired | Refuses to rank unless `--accept-stale` |

`plan` refuses an expired snapshot by default. `status` prints the age, digest
and calibration in one screen.

## Task routing

Types, first match wins: `security`, `architecture`, `bugfix`, `refactor`,
`test`, `mechanical`, `docs`, `feature`, otherwise `unclassified`.

- Every task needs an acceptance predicate (a test command, a gate, or
  `review: <path>`). Without one the task is returned as **needs scoping**; it
  is not routed and not escalated.
- `bugfix`, `refactor`, `security` and `architecture` require review.
- `architecture` also gets `decider: <judge>`.
- The implementer is always the baseline. Escalation is a separate, recorded
  step, not an anticipation of difficulty.

Override the draft by writing `routing.yaml` in the change:

```yaml
schema: 1
change: add-dimension-filter
tasks:
  "1.1":
    type: feature
    verify: ["pytest tests/test_cli.py -q"]
```

## Baseline resolution

Order, first hit wins:

1. `--baseline MODEL`
2. `SURPLUS_BASELINE_MODEL`
3. `model.default` in the active Hermes profile config
4. Stop with an error

The baseline is a fact about the host, not a recommendation. It is recorded in
the report with its source.

## Providers

- `surplus` — catalog plus per-model order book: live best, median discount,
  seven-day realised, request volume, per-seller offers.
- `generic-openai` — any other `/v1` endpoint. Reads `/v1/models` list prices
  and records `discounts: false`. It never invents a discount.

The provider is inferred from `--url`; nothing is hardcoded to Surplus.

## Reading the report

- Header: generated time, snapshot time, age, freshness, provider, digest,
  baseline and its source.
- Portfolio cards: role, model, coding score, realised price (in/out).
- Market table: every basis, side by side, with median discount and 24h
  requests.
- Tasks table: implementer, review flag, predicate, and decider when present.
- Budget table: measured tokens, cache reads, realised price, monthly cost and
  provenance. `Total` is the sum of the role costs.
- Callouts are computed, not written: the reviewer's share of spend, the
  illustrative roles, the builder's token share, and the cost multiple of the
  top-scoring model.

## Calibration

`calibrate` reads `state.db` read-only and groups profiles by role:
`default` → builder, `council*`/`review*` → reviewer, `runner*` → runner,
`judge*`/`architect*` → judge. A profile with no mapping is skipped, not
silently counted.

The budget keeps three separate quantities; do not collapse them:

- `monthly_total` — the **sum** over the window, normalised to 30 days. This is
  the only input to monthly cost.
- `per_session.p50/p90` — the size of one session; used to size one task.
- `per_call.p50/p90` — the size of one model call.

A median is not a monthly total. With one heavy session, P50 × session count
understates the sum by an order of magnitude.

## Known limits

- Benchmark refresh parses BenchLM's coding page only. HLE-Diamond and
  FrontierMath rows are cached in `assets/benchmarks.json`; they do not refresh
  yet.
- `--emit-profiles` / `create-profiles` are not implemented. The report names
  the portfolio but does not rewrite Hermes profiles.
- The portfolio is a heuristic, not a proof. It puts a defensible default on
  the page; the report says so.
- Generic providers have no discount book, so the budget column equals list
  price there.

## Tests

```bash
python3 tests/unit/test_model_routing.py
```

The suite covers the price arithmetic (including cache reads), the
total-versus-median distinction, classification, routing predicates, the
freshness ladder, provider parsing, portfolio selection, and report emission.

## Troubleshooting

- **`no state database`** — pass `--hermes-home` at the directory containing
  `state.db`, not the profile directory.
- **`not in this catalog`** — the benchmark cache names a model the provider no
  longer sells. Remove it or pass `--models` explicitly.
- **`no benchmark price`** — the model page changed shape. Run `refresh` with
  one model and inspect; do not guess a price.
- **`no market page parsed`** — usually a truncated response. The HTTP layer
  retries three times; if it persists, the page is behind a wall.