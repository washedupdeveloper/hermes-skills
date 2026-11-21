# Report design

Two artifacts, one source of truth: `report.json` is the record, `report.html`
is a rendering. Every number on the page must exist in the JSON, and every cost
table must name its price basis.

## Header

Required, in this order: generated-at, snapshot fetched-at plus age and
freshness, provider `base_url`, snapshot digest, baseline model and its source.
Two runs on the same afternoon must be distinguishable without opening the
JSON.

## Portfolio cards

Four equal cards: role label, model id, one-line reason, coding score, and a
**two-line** realised price:

```
JUDGE
claude-fable-5.2
best combined coding and hard reasoning
coding 92.3
$3.33 in · $16.64 out
```

Do not put `in/out` on the same flex line as the coding score. It squeezes the
output price onto a second line and reads as a broken pair.

A role may share a model with another role. Say so in the reason; do not
invent a second model to make four cards look different.

## Frontier table

Before the market table, show every scored model on one page:

| Model | Coding | Blended 7-day $/M | Review $/mo | Δ pts | Marginal $/pt | Verdict |
|---|---|---|---|---|---|---|

- `Review $/mo` applies the seven-day realised price to the measured review
  month. State that volume in the note under the table.
- `Δ pts` is against the builder and carries the relative percentage in
  parentheses, e.g. `+3.6 (+4.7%)`.
- `Marginal $/pt` is the incremental monthly cost divided by the incremental
  coding points. Blank for a dominated model and for the builder.
- Verdict is one of: `role: ...`, `dominated by <model>: Nx cost, -X pts`,
  `rejected: +X pts (+Y%) < threshold`, `upgrade at $N/mo`, `no gain over
  builder`.
- The table shows dominated models instead of hiding them. The reader must be
  able to see that a worse model costs more.

## Market table

Columns: `Model`, `Coding`, `Live best $/M (in/out)`, `7-day avg $/M (in/out)`,
`List $/M (in/out)`, `Median off`, `24h req`. Sort by coding descending. A dash
means no score, not zero. Put the snapshot digest under the table.

## Budget table

Columns: `Role`, `Tokens/mo`, `Input`, `Output`, `Cache read`,
`7-day $/M (in/out)`, `Monthly $`, `Provenance`.

- The total row must sum tokens, input, output, cache **and** cost.
- Add the note: "Monthly $ includes cache reads at the provider's cache price;
  the input and output columns are uncached."
- State both share of spend and share of tokens. Never call a share "small"
  without the measured number beside it.

## Callouts

Computed from the payload, never hand-written:

- the judge's share of spend, when it is the premium tier;
- roles whose volumes are illustrative (uncalibrated);
- no separate runner when the builder is already the cheapest non-dominated
  model;
- review is a role, not a second model, when the reviewer shares the builder;
- a dominated example with its cost multiple;
- the top-scoring model's cost multiple over the builder, framed as "that is
  why it decides and does not implement".

## Selection policy the report must explain

1. **Dominance.** Remove A when another model has at least as high a coding
   score for at least as low a realised price, with one strict inequality. A
   worse model at a higher price is not a tier.
2. **Materiality.** A different reviewer must beat the builder by `--min-gain`,
   5% by default. Below that the gain is treated as immaterial, however cheap
   the marginal point is.
3. **Budget.** The reviewer's monthly cost at the measured review volume must
   fit `--review-budget`. The default is 0: the builder model reviews under a
   separate rubric. A cap is not a target: the cheapest model that clears the
   materiality gate is selected, so raising the cap alone does not buy quality.

## Sources and method

A numbered list of real URLs: the market, BenchLM coding, Vals SWE-bench, HLE
Diamond, FrontierMath. The method paragraph names the price basis, the
benchmark dates, the calibration window, the dominance rule, the materiality
threshold and the review budget.

## Style

Standalone CSS, serif `h1`, 4-column cards, A4 `@media print` rules, no PDF.
Keep the editorial header, the callout blocks and the numbered sources; they
are the part the owner reads first.