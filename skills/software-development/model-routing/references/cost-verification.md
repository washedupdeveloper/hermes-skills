# Cost and usage verification

Use this when a change touches price arithmetic, calibration from Hermes usage,
the monthly budget, or the report's cost columns. The unit tests prove the code
matches its own assertions; this procedure proves the formula matches the
system that actually bills.

## 1. Fit the formula to the recorded charge

Hermes records one row per session and model in `session_model_usage`:
`input_tokens`, `output_tokens`, `reasoning_tokens`, `cache_read_tokens`,
`api_call_count`, `estimated_cost_usd`. Reconstruct the charge with the price
triple you believe applies:

```
cost = (input * p_in + output * p_out + cache_read * p_cache) / 1e6
```

Run it over rows with a non-trivial `estimated_cost_usd` and compare. The fit is
decisive when it is **exact** (floating-point noise only): that is the billing
shape. A residual means the schema or the price is wrong, not that the estimate
is approximate.

`estimated_cost_usd` is an estimate at the provider's **list** pricing. It is the
schema oracle, not the Surplus realised invoice: use it to establish which
columns are billed, then price the monthly budget from the snapshot's realised
basis. Do not copy the list-price fit into the report as the realised cost.

**`output_tokens` already includes `reasoning_tokens`.** Treat reasoning as a
subset for diagnostics, not an additive field. Adding it double-bills every
reasoning model; a formula that does so still looks plausible because the error
is a fraction of the bill. If the exact fit is obtained only when reasoning is
excluded, that is the answer: exclude it.

## 2. Keep cache reads in the bill

A cache read with no published cache price bills at the input price, never at
zero. A catalog's `pricing.input_cache_read` is per token; multiply by `1e6`
for a per-million price. A model page may publish live input/output but omit
cache; merge the catalog's cache price into the page's `list_price` and `best`
rather than replacing the catalog entry, or every cache-heavy role is
understated.

When only one realised discount is published for the offer, applying it to the
cache price is an **assumption**. Record it in the report and the skill's
pitfalls; do not present a discounted cache price as invoice-confirmed when no
separate cache charge exists. If the provider bills cache at list, the budget
is understated by the difference.

## 3. Percentiles from session sums

Never sum per-field percentiles. The sum of P50 input and P50 output is a
bundle no session ever had. Sort sessions by **total tokens**, then interpolate
each component between the two sessions straddling the requested percentile:

```
position = p * (n - 1)
lower, upper = floor(position), ceil(position)
weight = position - lower
value = component[lower] * (1 - weight) + component[upper] * weight
```

Keep the monthly total separate: it is the **sum over the window**, normalised
to 30 days, and is the only input to a monthly cost. P50 sizes one task; it does
not size the month. `per_call` derived from session sums is a session-average
call size, not a per-call distribution; say so rather than naming it a P90 call.

## 4. Recompute the report independently

Do not import the report builder to certify the report. Read three artifacts
and recompute with plain arithmetic:

- the snapshot's `list_price` and `realised_discount` (realised = list *
  `(1 - discount/100)`);
- the budget's `monthly_total` for each role;
- the report's role, frontier and total values.

For every role and every frontier row, recompute the cost from the tokens and
the realised price, then compare within one cent. Recompute the total as the
sum of the unrounded role costs; a one-cent difference from independently
rounded components is acceptable, a larger one is not. Confirm the HTML contains
that total and the snapshot digest, and open the rendered page or a screenshot
for clipping and overlap.

A verifier that shares the builder's price model, rounding or token schema can
only prove self-consistency. The independent script must take the raw fields.

## 5. Report semantics that look like arithmetic errors

- **Dominated rows compare against their dominator.** The frontier's `Δ`
  column is versus the builder; the verdict's deficit must be versus the model
  that dominates it. A row can be `+0.6` versus the builder and `-11.3` versus
  its dominator; label both, or the reader sees a contradiction.
- **Price multiples below 10x need one decimal.** `{:.0f}` renders `1.14` as
  `1x`, which reads as "same price" for a strictly dearer model. Use one
  decimal below 10x and integers above it.
- **No live offer means no recommendation.** A model with `best is None` stays
  in the market table with a dash but cannot fill a role; do not fall back to
  list price in selection.

## 6. Checklist

- [ ] The chosen price triple reproduces `estimated_cost_usd` to machine precision
- [ ] Reasoning is excluded from the output term (it is already inside output)
- [ ] Cache reads are priced, with the discount assumption stated
- [ ] P50/P90 components were interpolated from sessions sorted by total tokens
- [ ] Monthly total is the summed, normalised volume, not P50 × sessions
- [ ] An independent script recomputed every role and frontier cost from raw fields
- [ ] The rendered report contains the total and digest, with no clipping
- [ ] A mutation of each pricing rule makes the suite fail (not just pass when intact)
