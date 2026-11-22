---
name: model-routing
description: "Use when picking a model stack for code."
version: 0.1.0
author: "Storm, Hermes Agent"
license: MIT
platforms: [linux, macos, windows]
category: software-development
metadata:
  hermes:
    tags: [models, routing, pricing, coding, benchmarks, openspec, council]
    related_skills: [technology-selection, verify-and-stop, critical-verdict]
writes: [none]
side_effects: [none]
---

# Model routing selector

Answers one question: **which model should do this task, and what does that
cost at the prices actually available?** It is deliberately not a chat tool and
not an LLM call. The decision is a pure function over a dated price snapshot, a
calibrated token budget, and a cached benchmark table.

## When to Use

- Choosing which model should implement an OpenSpec task, and which model may
  review or decide it.
- Comparing a provider's live best price, seven-day realised price and discount
  depth for coding models.
- Auditing a cheaper or more expensive model: does it actually beat the builder
  by enough to justify the price?
- Calibrating token volume from Hermes' own session history instead of guessing.

Don't use for: open-ended chat-model selection, or executing the tasks. `plan`
writes a routing report; it does not run the models or rewrite a profile.

## Prerequisites

- Python 3.11+ (standard library only).
- Read access to the Hermes `state.db` for calibration, and network access to
  the provider for `refresh`.
- The provider key is not read by this skill. `refresh` fetches the public
  market pages; the router only prices and reports.

## Quick start

Set `S` to the directory containing this SKILL.md. The example below uses the
documented install layout; an external `skills.external_dirs` checkout lives
wherever it was cloned. `STATE` is a writable cache outside the skill tree.
On Windows use `python` rather than `python3` and the `%LOCALAPPDATA%\hermes`
home.

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

# Refresh the BenchLM coding table and keep it beside the snapshot.
python3 "$S/scripts/run.py" refresh-benchmarks \
  --benchmarks "$S/assets/benchmarks.json" \
  --out "$STATE/benchmarks.json"

python3 "$S/scripts/run.py" plan \
  --change openspec/changes/<change-name> \
  --benchmarks "$STATE/benchmarks.json" \
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

## Policy defaults are flags

No decision value is fixed in code. `plan` exposes:

| Flag | Default | What it controls |
|---|---:|---|
| `--min-gain` | 0.05 | reviewer materiality |
| `--review-budget` | 0 | independent reviewer cap (USD/month) |
| `--runner-floor` | 65 | minimum coding score for a separate runner |
| `--builder-floor` | 70 | fallback builder floor when the baseline is absent |
| `--judge-coding-weight` | 0.6 | judge score = w*coding + (1-w)*reasoning |
| `--hle-weight` | 0.5 | reasoning = h*HLE + (1-h)*FrontierMath |
| `--min-context` | 128000 | context floor for candidates |
| `--min-discount` | 0 | best live offer discount floor (%) |
| `--blend-output-share` | 0.2 | display-only 80/20 price blend |
| `--callout-multiple` | 5 | "judge costs Nx" callout threshold |
| `--judge-share-alert` | 0.4 | judge-share callout |
| `--review-share-alert` | 0.5 | review-share callout |
| `--benchmark-max-age-days` | 30 | stale-benchmark banner |
| `--fresh-hours` | 12 | fresh → aging boundary |
| `--aging-hours` | 48 | aging → provisional boundary |
| `--expired-hours` | 168 | ranking refusal boundary |
| `--sources` | built-in | JSON list of `{title,url}` source rows |
| `--review-types` | bugfix, refactor, security, architecture | task types that require review |

`refresh` exposes `--timeout 30`, `--retries 3`, `--workers 6`; `refresh-benchmarks`
adds `--url`; `calibrate` exposes `--window 30` and `--month-days 30`. The direct
adapter reads `COUNCIL_DIRECT_TEMPERATURE` (0–2) beside its other `COUNCIL_DIRECT_*`
settings. Policy values are echoed into `report.json` under `policy`, and the
benchmark age under `benchmarks`, so a run records the policy it used.

If the provider key sets a minimum discount, pass the same value as
`--min-discount`; otherwise the selector can recommend a model the request path
will refuse with `minimum_discount_not_met`. Read the refusal, not the retry
button: the body names the key's floor and the best eligible discount, so a
model below the floor cannot succeed on a second attempt. Diagnose with a
one-token request before planning; `references/market-parsing.md` has the
request and the decision table.

## The four roles

| Role | Rule | What it is allowed to do |
|---|---|---|
| **judge** | Best `w*coding + (1-w)*mean(HLE-Diamond, FrontierMath)` with `w=--judge-coding-weight` (0.6); price is not a tie-breaker | Architecture decisions only. Never implements. |
| **reviewer** | The builder model by default. A different model only when `--review-budget` is set, it beats `--min-gain` (5%), fits that budget, and is the cheapest model that clears both gates | Checks and plans. Never writes the patch. |
| **builder** | The ambient baseline when it is in the market | Implements every task. |
| **runner** | The builder model unless a cheaper non-dominated model clears `--runner-floor` (65) | Mechanical and test work. |

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
   under a separate rubric. A budget is a cap, not a target: among the models
   that clear the materiality gate, the cheapest one is selected. Raising
   `--min-gain` is how you ask for a larger quality step, not raising the cap.

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
| ≤ `--fresh-hours` (12 h) | fresh | Full report |
| `--fresh-hours`–`--aging-hours` (48 h) | aging | One-line note |
| `--aging-hours`–`--expired-hours` (168 h) | provisional | Report is provisional |
| > `--expired-hours` | expired | Refuses to rank unless `--accept-stale` |

`plan` refuses an expired snapshot by default. `status` prints the age, digest
and calibration in one screen.

## Task routing

Types, first match wins: `security`, `architecture`, `bugfix`, `refactor`,
`test`, `mechanical`, `docs`, `feature`, otherwise `unclassified`.

- Every task needs an acceptance predicate (a test command, a gate, or
  `review: <path>`). Without one the task is returned as **needs scoping**; it
  is not routed and not escalated.
- `bugfix`, `refactor`, `security` and `architecture` require review by default;
  `--review-types` changes the set.
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

- `refresh-benchmarks` parses BenchLM's coding table only. HLE-Diamond and
  FrontierMath rows are carried over from `assets/benchmarks.json`; they do not
  refresh yet. A model with a coding score but no cached reasoning rows scores
  zero on the judge's reasoning term, so its judge rank is coding-led.
- `--emit-profiles` / `create-profiles` are not implemented. The report names
  the portfolio but does not rewrite Hermes profiles.
- The portfolio is a heuristic, not a proof. It puts a defensible default on
  the page; the report says so.
- Generic providers have no discount book, so the budget column equals list
  price there.
- BenchLM slugs and provider model ids are matched literally. A model listed
  under one name at the provider and another at BenchLM is unpriced or
  unscored, not guessed; add the slug to `assets/benchmarks.json` or pass
  `--benchmarks` with your own mapping.

## Verification

```bash
python3 tests/unit/test_model_routing.py        # 67 tests, stdlib only
bash tests/e2e/run_from_scratch.sh             # clone + CLI, black box
python3 -m surplus_select status --snapshot <file> --budget <file>
```

Prove the end-to-end path rather than the unit suite alone: run `refresh`, then
`plan`, then read `report.json` and confirm the portfolio, the frontier verdicts
and the monthly total. A unit suite cannot see a flag that parses but never
reaches the selection, so also run one `plan` with `--review-budget 80` and
confirm the reviewer model actually changes in the output.

## Tests

```bash
python3 tests/unit/test_model_routing.py
```

The suite covers the price arithmetic (including cache reads), the
total-versus-median distinction, classification, routing predicates, the
freshness ladder, provider parsing and its refusal of an unpriced catalog,
portfolio dominance and materiality, the CLI end-to-end path including
`--review-budget` and a refused expired snapshot, and report emission.

Every test is standard library `unittest`; there is no pytest dependency, so it
runs in the bundled Hermes environment.

## Pitfalls

- **A sample is not a ceiling.** `requests_24h` shows liquidity, not capacity.
  A model with 251 requests/day can be sold out at your peak.
- **A benchmark gain is a proxy for a capability step.** 3.6 points on a 76.4
  baseline is inside the noise of most baskets; that is why the materiality
  gate exists, and why it is a flag rather than a constant.
- **A finding is pair-, effort- and harness-specific.** A result from model A
  versus model B cannot support a claim about model A versus model C; a lead
  smaller than the benchmark's measured run-to-run range is a tie; native-CLI
  runs measure model plus harness. Put the exact comparator, effort and harness
  in the same sentence or table row — if one is missing, the number is not
  evidence for your pair.
- **Dominance is priced at the role's measured volume.** A model can look
  cheap per input token and be dominated once output and cache reads are
  priced; a single 80/20 blend would hide that.
- **A model with no live offer is not selectable.** It remains in the market
  table with `—`, but no role can recommend it.
- **Reasoning is already inside output.** `output_tokens` in the Hermes usage
  table includes `reasoning_tokens`; adding both double-bills the model. The
  formula is checked against Hermes's own recorded estimate.
- **The judge weight is a policy, not a measurement.** `0.6*coding + 0.4*hard
  reasoning` is a stated default. If your work is more reasoning-heavy, change
  the constants and record the change; do not present the ranking as objective.
- **Cache reads carry an assumption.** The provider page gives a list cache
  price and one realised discount; the selector applies that discount to cache
  as well. No separate cache invoice is available to confirm it. If Surplus
  bills cache at list, every cache-heavy role is understated.
- **A provider discount floor is a runtime gate, not a price statistic.** The
  selector can recommend a model that the request path refuses with
  `minimum_discount_not_met`. Pass the key's floor as `--min-discount`, match it
  against the model's **best live offer**, not its seven-day realised discount,
  and smoke-test each selected model with a one-line request before creating its
  profile. A high realised discount does not imply a high best offer. The
  refusal is deterministic: it names the key's minimum and the best eligible
  offer, and resending the same model cannot change either. Probe once, then
  lower the key floor or pick a model at or above it. If the response is 401
  instead, fingerprint the credentials before blaming the floor — a stale
  `OPENAI_API_KEY` can be a different, revoked key from the one the custom
  provider's `key_env` resolves.
- **The reviewer sharing the builder is not independence.** It is a second read
  of the same diff by the same weights; say so in the report rather than letting
  the role name imply an independent check.

## References

- `references/cost-verification.md` — matching the cost formula to recorded charges.
- `references/market-parsing.md` — provider page and catalog fields.
- `references/report-design.md` — report sections and callout policy.
- `references/council-integration.md` — direct reviewer adapter and profile notes.

## Troubleshooting

- **`no state database`** — pass `--hermes-home` at the directory containing
  `state.db`, not the profile directory. On Windows that is
  `%LOCALAPPDATA%\hermes`; the tool resolves that default itself.
- **`has no session_model_usage table`** or a silent empty read — the path was
  probably unescaped in a URI. The reader uses `Path.as_uri()`, so a path with a
  space or `#` is safe; if you see this on a plain path, the schema itself moved.
- **`not in this catalog`** — the benchmark cache names a model the provider no
  longer sells. Remove it or pass `--models` explicitly.
- **`no benchmark price`** — the model page changed shape. Run `refresh` with
  one model and inspect; do not guess a price.
- **`no market page parsed`** — usually a truncated response. The HTTP layer
  retries three times; if it persists, the page is behind a wall.