# Selecting LLM Models and Inference Markets

Use when the candidate set is language models rather than libraries: choosing
which model runs each agent tier, or comparing providers/marketplaces on cost
and capability. The output is a routing decision with a monthly bill, not a
leaderboard summary.

"MoE" in this context means a system-level division of labour across models,
not a sparse model architecture. A model being a sparse mixture-of-experts is a
serving-cost property; the routing decision is which model gets which role.

## 1. Fix the workload and the roles before comparing

- Define one standard task shape (e.g. 1M input + 200k output) so per-token
  prices become per-task costs you can compare.
- Split the work by **reversibility**, not difficulty:

| Tier | Job | Trigger | Volume |
|---|---|---|---|
| Judge | Decide | The call is irreversible | Tens of calls/month |
| Reviewer | Plan / review | Expensive to get wrong | ~100 calls/month |
| Builder | Implement | Everything else | Thousands of turns |
| Runner | Parallel grunt work | Tests, docs, mechanical edits | Hundreds of tasks |

- The strongest model belongs at the lowest volume. Compute the oracle premium
  before optimising it: at 20 calls/month the gap between the best model and
  the third-best is usually a few dollars. Optimise the volume tiers instead.

## 2. Pull list prices from the provider's model API

- An OpenAI-compatible `/v1/models` normally returns `context_length`,
  `pricing`, `architecture`, `supported_features` and `top_provider`. Filter
  on context/modality/features in code, not in the UI.
- UI filter query params are frequently client-side. Do not assume
  `?discount=90&ctx=128000&inputs=text` changes what the API returns, or that
  the visible rows are the full filtered candidate set.
- Prices in the catalogue are per-token strings; multiply by 1e6 for $/M. Some
  entries are image/video/audio models with a zero context length — filter on
  `architecture.output_modalities` containing `text` and on the context floor
  before ranking.

## 3. Read the order book, not the headline

For each shortlisted model capture four prices plus liquidity:

| Field | Meaning | Use |
|---|---|---|
| Reference / list | Undiscounted anchor price | Compare discounts |
| Best offer | Top of book, thin | **Headline: available now** |
| Median offer | Half the live offers are worse | Pessimistic case |
| **Realised 7d** | Request-weighted average actually paid | **Budget: monthly bill** |

Also record live offers, seller count, 24h request volume, and the provider
route table (success rate, p50/p95 latency, tok/s, traffic share).

Rules:

- A deep discount on a low-success route is a retry tax. Estimate cost as price
  divided by success rate, not price.
- Report the live best as the "available now" number a buyer sees in their
  tooling; compute the monthly budget on realised. List price is reference only.
- 99–100% discounts are often stale or teaser listings and vanish at volume.
  The realised number is the one that reconciles with the invoice.
- A model with a few thousand requests/24h is a thin market. Acceptable for a
  judge; not acceptable for the builder.
- Discounts are spot prices. Re-check monthly; the tiering survives, the exact
  prices do not.

### Surplus page markers

Tag-strip each model page (`<script>`, `<style>`, `<svg>` removed; tags replaced
with `|`; entities unescaped; repeated pipes collapsed), then match:

- Reference price — `Benchmark price · $X input / $Y output per 1M tokens`
- Best discount — `Best discount now|NN.N%|off|You pay N% of reference`
- Median discount — `Median discount|NN.N%|off|Across N live offers`
- Realised 7-day — `Realized · 7 days|NN.N%|avg`
- 24h volume — `Requests · 24h|N|N offers from N sellers`
- Best offer — the first `$X| in|$Y| out` row after the price header
- Route table — header `Route|p50 latency|p95 latency|Throughput|Success rate|Share`,
  then one row per seller with traffic share as the last field

Compute `realised = reference × (1 − realised_pct/100)`. Cache each page for a
day and store the fetch timestamp; a model page is roughly 700 KB of HTML.

## 4. Cross-check boards that disagree

| Board | What it measures | Status |
|---|---|---|
| BenchLM coding | Weighted multi-benchmark basket | Broad ranking; penalises missing rows |
| Vals AI SWE-bench | Independent run, named harness, cost/test | Top saturated |
| SWE-bench Verified | Real GitHub issues | Saturated; tie-breaker only |
| SWE-bench Pro / DeepSWE / Terminal-Bench 4.x | Agentic coding | Unsaturated; prefer these |
| HLE-Diamond | Hard expert reasoning | Unsaturated |
| FrontierMath Tiers 1–3 | Research math | Unsaturated |
| HF model cards | Vendor tables, incl. DeepSWE/TB4 | Claims, not measurements |
| Senior SWE-Bench | Long-horizon engineering | Vendor-heavy |

Rules:

- Two boards minimum, and explain the disagreement rather than averaging it.
- Separate measured (third party, named harness) from vendor-reported. A
  vendor-only launch table is a claim until an independent run exists.
- Read the basket weights: a composite heavy on SWE-bench Pro will rank a model
  with no SWE-bench Verified row differently from one heavy on SWE-V.
- A saturated benchmark cannot separate frontier models; use it to catch
  regressions, not to choose.
- Check feature gates before ranking: tool calling, context length, vision and
  structured output decide whether the agent loop works at all.

### BenchLM embedded table

The coding page ships its rows in a Next.js data blob under
`table.lanes["bench-align-v5"].rows`. Row length changes when optional fields
are null, so fixed indices break.

- Anchor from the end: `arr[-1]` benchmark dict, `arr[-2]` exact-row count,
  `arr[-3]` weighted coding score.
- Stable prefix: `arr[1]` name, `arr[2]` slug, `arr[4]` Open Weight/Proprietary,
  `arr[8]` context, `arr[9]` list input, `arr[10]` list output, `arr[14]` overall.
- Validate the mapping against two rendered rows (a known leader and a known
  mid-table model) before trusting it.
- Coding and overall are different columns. A model can lead SWE-bench Verified
  and sit far lower on the weighted coding basket, or the reverse.

## 5. Price the roles, not the tokens

```
task_cost = in_M × realised_in + out_M × realised_out
monthly   = Σ (tier_tokens × tier_realised_price)
```

Report **token share and spend share side by side**, and derive them from the
selected portfolio rather than assuming a shape. A reviewer that shares the
builder model adds volume at the builder's price; the small-volume judge can
then dominate the bill. The opposite is also possible: a premium reviewer on
high cache volume can be 80%+ of spend. Neither is a default — measure it.

Before costing, remove dominated candidates:

- A dominates B when `score(A) >= score(B)` and `price(A) <= price(B)`, with at
  least one strict inequality. B has no role on any tier.
- A different model for a role must clear a materiality threshold (5% relative
  on the primary score is a defensible default) **and** fit a stated monthly
  budget. Otherwise the role uses the incumbent model under a separate prompt.
- Report marginal cost per point: `(cost_upgrade - cost_incumbent) /
  (score_upgrade - score_incumbent)`. A large price multiple for a small score
  delta is a rejected upgrade, not a tier.
- A role with no better-and-cheaper candidate collapses into the incumbent.
  Do not fill a tier for symmetry.

Deliver two build levels from the same parts (lean and recommended), plus the
all-frontier comparison so the saving is visible.

## 6. Operating the router

- Closed trigger list for the judge. Ask for an ADR-style answer (options,
  trade-off, recommendation, reversal cost), never code.
- Reviewer sees the diff, not the repo; cap context per call and split oversized
  diffs.
- Run the builder at high reasoning effort, not max; reserve max for the judge.
- Use the provider's minimum-discount path if it has one (e.g. `/min30`) so
  retries cannot quietly fill at list price.
- One base URL and key for every tier means routing is a model-id change, not a
  vendor integration.
- In Hermes: one profile per tier; delegated children inherit
  `delegation.model`; the runner belongs in a cron job. Per-task routing needs
  a classifier in front of dispatch — a closed trigger list is cheaper and more
  predictable.

## 7. Report contract

- Machine artifact first: a versioned `recommendation.json` carrying candidates,
  price basis, role assignment, monthly scenario, rejected candidates and the
  reason each was rejected, the source ledger, and `as_of`.
- Human artifact: `report.html` rendered from that JSON. Markdown is derived
  from the same data when a text copy is wanted. No PDF by default.
- Lead with the decision and the constraint driving it; comparison tables are
  support, not the opening.
- Every pick states which board and which price basis produced it. Keep the
  rejected candidates visible so a later reader can see the road not taken.
- Stamp prices and benchmark data with separate `as_of` values; a spot market
  and a monthly board age at different rates.

## 8. Consumer: council v2

`council review --profile <name>` selects one Hermes profile per run, and the
profile's `config.yaml` bytes enter the instrument digest — changing the model
changes the instrument. The five dimensions are in one prompt; v2 has no
per-dimension model routing.

Operating details — baseline resolution, escalation, `routing.yaml`, dispatch,
profile emission, budget calibration, report contract — are in
`llm-routing-operations.md`.

- The useful output is a profile (or a small family of profiles) plus the
  reasoning for it, not runtime hot-swapping.
- Write to a target directory, print a diff, and require an explicit flag to
  overwrite; never silently edit the active profile.
- Verify with `council doctor --profile <name>` before claiming the profile
  works.
- council's MCP server exposes `plan`, `review` and `doctor`; its ACP and MCP
  adapters do not load skills, and the reviewer prompt forbids tool calls. A
  selector cannot be invoked by council's server without a new tool or a
  standalone MCP server; selecting profiles is a pre-run step owned by the host
  agent.

## Pitfalls

- **Budgeting on the best offer or the median.** Both are listings; realised
  is the only number that matches the invoice.
- **Ranking on one composite.** Two boards that disagree teach you where the
  model is weak; one board hides it.
- **Treating vendor tables as measurements.** Independent runs with a named
  harness are the only comparable numbers.
- **Comparing $/M without a task shape.** A 10x input-price difference can be a
  1.2x task-cost difference once output and caching are included.
- **Reading a deep discount as availability.** Price is what you pay when the
  request succeeds; success rate is part of the price.
- **Promoting the cheapest capable model to judge because it writes good code.**
  Patch quality and judgment quality are different axes; check the hard
  reasoning board before trusting architecture calls to a strong coder.
- **Filling every role with a different model.** A worse model at a higher
  price is not a tier; a role is a prompt and a budget. Collapse it into the
  incumbent unless it clears both the materiality bar and the budget.
- **Shipping a report without an as-of snapshot.** Prices and scores move
  independently; two runs on the same day can disagree and neither is
  auditable.
- **Editing the live profile in place.** The profile hash is part of the review
  instrument; stage the file, show the diff, and require an explicit overwrite.

## Provider quirk: Surplus Intelligence

- `https://api.surplusintelligence.ai/v1/models` returns the full catalogue with
  reference pricing and ignores the market-page filters.
- `/v1/prices` returns the same catalogue with per-provider list prices and an
  `updated_at`; it carries no discounts. The live book and the realised average
  exist only on the model pages — do not mistake `/v1/prices` for a market
  snapshot.
- `/markets?discount=90&ctx=128000&inputs=text` is a client-side filter; the HTML
  renders roughly two dozen rows sorted by 24h credits, not the full filtered
  set. Do not treat the visible rows as the candidate list.
- Per-model pages `/markets/<slug>` are server-rendered; the field markers are
  in §3. Parse the tag-stripped text, not CSS classes.
- The API base URL supports a `/min30` path suffix to buy only at ≥30% off.
