# Operating an LLM Routing Policy

Companion to `llm-model-market-selection.md`. That file decides which models
clear the bar; this one decides how work reaches them, how profiles are
written, and what a report must contain. The unit of routing is a task with a
predicate, not a prompt.

## 1. Baseline and escalation

Resolve the baseline in a fixed order and record the source:

1. `--baseline <model-id>` (per-session override)
2. a configured env var (for CI and scheduled runs)
3. the active agent profile's `model.default`
4. fail loudly: "cannot determine baseline; pass `--baseline`"

An MCP server is not told which model the host is using. A selector exposed as
an MCP tool must take the baseline as an argument or read a configured default;
it cannot infer it from the host.

The policy is attempt-then-escalate, not classify-then-route:

1. Every task starts on the baseline.
2. Bounded attempt: implement, run the checks the task declares, retry once.
3. Verify against the task's acceptance predicate. Not the model's self-report.
4. On failure, escalate exactly one tier with the failure evidence attached.
5. The top tier decides the approach; it does not grind on the patch.
6. No predicate at all means "needs scoping" — not a bigger model. A stronger
   model does not make an ambiguous task verifiable; it makes the ambiguity
   more expensive.

Closed list of escalation triggers: a failed acceptance scenario, a failing
test/typecheck/gate after the bounded retry, a blocking proven finding from the
review gate, two rejected patches with the same signature, or no predicate.
"The model feels unsure" is not a trigger; it is the failure mode.

Never route below the baseline without an explicit opt-in (`--allow-downgrade`)
and a closed whitelist of mechanical, cheap-to-verify tasks (docs, formatting,
renames, test scaffolding, dependency bumps). Downgrading can make a task more
expensive overall: the cheap attempt fails, then the baseline and the escalation
are paid anyway. Keep the whitelist opt-in so it can be adopted later without
re-architecting the policy.

## 2. Task taxonomy and routing.yaml

A task needs a type and a predicate. The type selects the benchmark basket and
the default tier; the predicate decides success.

| Type | Example | Predicate | Default tier | Review |
|---|---|---|---|---|
| `mechanical` | rename a field across src and tests | suite + grep for the old name | baseline (downgrade-eligible) | optional |
| `docs` | update an agent or API doc | link check + read-through | baseline (downgrade-eligible) | optional |
| `test` | add a regression test | the new test passes | baseline | optional |
| `feature` | add a CLI flag | new tests + existing suite | baseline | on diff size |
| `bugfix` | fix a wrong identifier in output | failing repro, then green regression | baseline, escalate on failed repro | yes |
| `refactor` | split a module without API change | full suite + public API unchanged | baseline | yes |
| `architecture` | choose a state model | ADR + judge sign-off | judge decides, baseline implements | judge |
| `security` | validate a path before a sandbox mount | security tests + reviewer | baseline + mandatory reviewer | mandatory |

Put the map in a sibling `routing.yaml` under the change directory, not inline
in `tasks.md`. Inline tags make every task list noisy and are easy to lose in a
reformat; a sibling file is diffable, keyed by task ID, and can be edited ad hoc
when the plan changes.

```yaml
schema: 1
change: add-dimension-filter
tasks:
  "1.1":
    type: feature
    verify: ["pytest tests/test_cli_scope.py -q"]
  "2.1":
    type: architecture
    verify: ["review: docs/adr/0007-dimension-filter.md"]
```

Generate the draft from the task text, show it, and require approval before
routing. A task with no type or no predicate is blocked, not guessed.

## 3. Dispatch: in-session baseline, spawn on escalation

A Hermes session's model is fixed by its profile, and `delegate_task` cannot pin
a model per child. Two consequences:

- Baseline tasks run **in the current session**; the agent already is the
  selected model. No spawn, no extra boot, no context loss.
- Escalated tasks need a process boundary: `hermes -p builder-<tier>` with the
  task and the failed predicate, or a direct API call when the task is text-only.

Spawn on the happy path is the latency bug: an agent boot per task is slower
than the model call it wraps. Pay it only when the predicate has already failed.

For review and other prompt-in/raw-text-out work, a direct OpenAI-compatible
call is the right dispatch: no tools, no sandbox, no idle timeout. Profile spawn
is for tasks that need file edits, commands, or tools.

## 4. Provider snapshot and staleness

Use a provider adapter registry, not a hardcoded vendor:

```
ProviderAdapter:
  name
  matches(base_url) -> bool
  fetch_catalog() -> models + list prices
  fetch_offers(model_id) -> sellers, discounts, effective price, availability
  capabilities -> {discounts: bool, availability: bool}
```

Discovery order: explicit provider config -> infer from the active profile's
provider entry (`base_url`) -> generic OpenAI-compatible fallback (catalogue and
list price only). The snapshot records which adapter ran and what it could not
see, so a report never pretends a provider has a discount book.

Write a JSON snapshot with `provider`, `base_url`, `fetched_at`, `models`,
`offers`, `capabilities`, `source_hashes`. Refresh it out of band (cron every
12-24h); the request path reads the file. Never scrape 15-40 model pages on the
request path.

Staleness ladder (checked at first use in a session, which is effectively
session-start; the prompt only fires when stale):

| Age | Behavior |
|---|---|
| <= 12h | silent |
| 12-48h | one-line note: prices N hours old |
| 48h-7d | provisional report; block profile writes; suggest refresh |
| > 7d | refuse to rank until refreshed or `--accept-stale` |

Stale data is acceptable for advice a human will read; it is not acceptable for
a config another process will trust.

## 5. Calibrate token volumes; never invent them

Round-number budgets (3,000 turns x 50k in / 10k out) are guesses. Measure from
the agent's own state database.

Hermes `state.db` exposes `session_model_usage` with `session_id`, `model`,
`api_call_count`, `input_tokens`, `output_tokens`, `cache_read_tokens`,
`cache_write_tokens`, `reasoning_tokens`, `estimated_cost_usd`, `first_seen`,
`last_seen`. `sessions` carries the same counters per session plus
`parent_session_id` and `started_at`.

Query a 30-day window, group by model, and compute p50/p90 per session. A
per-call distribution is not available from session sums; if you derive one,
label it as a session-average call size, not a P90 call. Include cache reads: they can exceed input, and providers price them
separately. Output is commonly under 10% of input, so a 20%-output assumption
overprices the stack by roughly 3x.

The review profile often contains automated and test runs; either filter by
session source or label its figure as an upper bound. Calibrate **tokens**, not
dollars: price the measured volumes with the current snapshot so the same
token budget can be repriced when the market moves.

Write `budget.yaml` with three views, not one:

- `monthly_total` — the measured sum over the window, normalised to 30 days.
  This feeds the monthly cost table.
- `per_session.p50 / p90` — typical and heavy session. This feeds per-task and
  per-review sizing.
- `per_call.p50 / p90` — derived session-average call size, not a measured
  per-call distribution. This feeds the per-call line with that caveat.

The total is a sum, not a percentile. Multiplying the p50 by the session count
understated a measured month by 67x because one session used 66.6M input tokens
while the median session used 50k. Use the total for the bill and the
percentiles for sizing; never substitute one for the other.

Record the window, sample size and filter used. The report cites it
("calibrated from N sessions / M calls, 30 days ending <date>"). Keep an
illustrative fallback only for the no-data case and label it `uncalibrated`.

Calibration is an explicit command (setup, then monthly), not a read on every
plan: the state-db schema is a Hermes internal, so a schema change should break
one command rather than every run. A role with no measured sessions is marked
`uncalibrated`, not filled with a guess.

## 6. Profile emission (not implemented in v1)

The selector is report-only in v1: it does not write a profile, create one, or
protect the ambient profile. This section is the contract for the emission verb
when it is implemented; do not present it as a shipped capability.

A profile is config, persona, skills and state. The selector only has business
with the first:

- Patch only `model.default`, the matching provider entry (`base_url`, key), and
  optionally `model.reasoning_effort`.
- Never touch `memories/`, `skills/`, `SOUL.md`, `state.db`, sessions or auth
  caches.
- Use a comment-preserving YAML round-trip (`ruamel.yaml`). A parse-and-dump
  rewrites the file, changes the instrument hash, and makes every past review
  look like it used a different instrument.
- Back up (`config.yaml.bak-<timestamp>`), show a unified diff, write to a temp
  file and rename.
- The ambient profile is protected: never change it without `--force` and a
  warning; prefer a sibling profile.
- `--emit-profiles` patches existing profiles; `--create-profiles` is the one
  explicit gate for creating missing ones (clone config and persona, no state,
  no memories).
- Naming: `builder-<tier>` for spawned implementers, `council-<role>` for
  reviewers. The baseline has no profile of its own.

## 7. Report contract

The machine artifact is the record; the HTML is a rendering.

- **HTML + versioned JSON sidecar. No PDF** unless a recipient asks. Markdown is
  derived from the same data when a text copy is wanted.
- **Generated-at** in ISO 8601 with timezone, in the header and the JSON.
- **Freshness badge**: green <= 12h, amber 12-48h, red > 48h, with provider and
  snapshot age.
- **Pricing block** on every cost table: live best as the headline ("now"),
  7-day realised as the budget column, median and list for reference, discount
  %. No cost row without a named basis.
- **Callout boxes**: amber for a trap, blue for a recommendation, green for a
  value pick. One claim, the evidence, the source. The callouts are the part a
  reader remembers; do not bury the trap in a table cell.
- **Numbered sources** at the bottom plus a Method paragraph: which provider,
  which price basis, which boards, what was assumed and what was excluded.
- JSON fields: `schema_version`, `generated_at`, `provider`, `snapshot`
  (`fetched_at`, `sha256`, `age_hours`), `pricing_basis` (`headline`, `budget`),
  `constraints`, `roles[]`, `tasks[]`, `sources[]`, `method`.

## 8. Council v2 integration

`council review --profile <name>` selects one Hermes profile per run. The five
review dimensions are in one prompt; v2 has no per-dimension model routing.

- The profile's `config.yaml` bytes enter the instrument digest: changing the
  model changes the instrument. Record the profile in the decision, never
  hot-swap mid-run.
- The useful output is a profile (or a small family) plus the reasoning, not a
  runtime selector.
- Verify with `council doctor --profile <name>` before claiming it works.
- council's MCP server exposes `plan`, `review` and `doctor`; its ACP and MCP
  adapters do not load skills, and the reviewer prompt forbids tool calls. A
  selector cannot be invoked by council's server without a new tool or a
  standalone server. Selecting profiles is a pre-run step owned by the host
  agent.
- A direct text-only adapter is the latency fix for reviews. See
  `editor-agent-integration` for the adapter contract: one HTTP request per
  sample, configured by the adapter's own environment (model, base URL, key),
  identity over model + base URL + prompt version + temperature, no boot and no
  tool loop. It does not parse a Hermes profile; profile bytes are the identity
  only for an adapter that actually reads the profile.
- Five profiles per review means five runs, five full-diff contexts and a
  cross-run merge. It multiplies cost and loses cross-dimension findings (the
  security issue that is really an architecture issue). Defer it; make the
  report recommend per-dimension models without pretending council executes
  them.

## Pitfalls

- **Headlining the realised price when the user asked for the available one.**
  Realised is the budget; the editor and the buyer see the live best. Show both.
- **Inventing token volumes.** A budget built on invented turns is a fiction
  with a decimal point. Calibrate from `state.db` or label it uncalibrated.
- **Assuming output is 20% of input.** Agent workloads are input- and
  cache-dominated; output is often under 10%.
- **Five dimension reviews by default.** 5x full-diff context, 5x latency, and a
  merge contract that does not exist yet.
- **An LLM router.** Using a model to choose a model adds a round-trip to every
  task. The policy is a decision tree; make it deterministic.
- **Synchronous scraping on the request path.** A market page is ~700 KB; a
  shortlist is tens of pages. Cache, cron, and read the file.
- **Sleep-polling a build or subagent.** `sleep 120; check` is self-inflicted
  latency. One blocking call with a timeout, or a background job with a
  notification; never a polling loop.
- **Spawn-per-task on the happy path.** The baseline already runs in-session;
  spawn only after a predicate fails.
- **Editing the live profile in place.** The config hash is the instrument;
  stage, diff, back up, and require an explicit overwrite.
- **Assuming the review server can load a skill.** The shipped adapter does not
  pass `--skills`, and the reviewer prompt forbids tool calls.
