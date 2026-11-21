# Market parsing

The selector prices from two pages, and they answer different questions. The
catalog says what exists and its reference price; the model page says what it
actually sells for.

## Catalog (`GET {base_url}/models`)

- `data[].pricing.prompt` and `.completion` are **per token**. Multiply by
  `1e6` before storing a `Price`; storing the raw value makes every model look
  1,000,000x too cheap.
- `pricing.input_cache_read` becomes `cache_read`, also x`1e6`. When absent,
  leave it `None`; never assume cache is free.
- The catalog has **list prices only**. A monthly budget computed from it is
  wrong by the discount, often 70-95%.
- Model ids are the join key. A benchmark row with an id absent from the
  catalog is not a candidate; do not rename it to fit.

## Model page (Surplus)

The page is server-rendered. Strip `script`, `style` and `svg`, replace tags
with `|`, unescape, and collapse whitespace; then read these lines:

```
Benchmark price · $0.147 input / $0.60 output per 1M tokens|
Best discount now|96.9%|off|You pay 3.1% of reference.|
Median discount|48.7%|off|Across 78 live offers.|
Realized · 7 days|93.4%|avg|Request-weighted average.|
Requests · 24h|3,335,864|78 offers from 40 sellers.|
|InferHub|96%|$0.00450| in|$0.0200| out|4.1s|98.9%|76.9%|$984|
```

Rules:

- **Live best** is the cheapest parsed offer row. Fall back to
  `benchmark x (1 - best_discount/100)` only when no row parses; the row is the
  actual buy price, and it can be below or above that formula.
- **7-day realised** is `benchmark x (1 - realised_discount/100)`. This is the
  only price used for a monthly budget. `Realized` is spelled with a z.
- **Median discount** is a liquidity signal, never a cost. A model at 48%
  median but 93% realised is liquid enough at the prices buyers actually take.
- **`requests_24h`** is the availability signal. Absent or zero means do not
  recommend it; a model can be listed and unsellable.
- If neither an offer row nor a best discount parses, return `best=None` and
  surface the model as unpriced. Do not invent a price.
- Offer rows carry the provider, discount, in/out price, p50 latency, uptime,
  cache hit and sold total. Use the route table after `Performance by provider
  route` for a provider-level success rate when it matches the seller name.

## HTTP behaviour

- The page is roughly 300 KB. `IncompleteRead` is common: catch
  `http.client.HTTPException` as well as `URLError`/`OSError`, send
  `Connection: close`, and retry three times with a fresh request.
- One failed page must not fail the refresh. Record the error, keep the other
  models, and fail only when **no** page yielded a price.
- `refresh` intersects the requested ids with the catalog before fetching.
  Print `not in this catalog` for the missing ids; a cached benchmark entry is
  not evidence the provider still sells the model.
- Refresh before a plan if the snapshot is older than 12 hours. Spot prices
  move; a report is a dated claim, not a standing price list.

## Pitfalls

- **Do not reuse a reference price from an earlier brief.** The same model can
  list at 8/40 on one day and 2.50/12 in a hand-written example; only the page
  is authoritative.
- **A discount is not a price.** Keep list, live, realised and median in four
  fields, and label which one each table prints.
- **A missing score is not zero.** The portfolio excludes an unscored model;
  the market table prints an em dash.
