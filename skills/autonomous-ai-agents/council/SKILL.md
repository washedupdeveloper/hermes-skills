---
name: council
description: "Convene the code-review council on a repo."
version: 3.5.0
author: user
license: MIT
platforms: [linux, macos, windows]
category: autonomous-ai-agents
metadata:
  hermes:
    tags: [code-review, multi-agent, council, delegation, review, quality, autonomy, portable]
    related_skills: [deterministic-quality-gates, requesting-code-review, systematic-debugging]
---

# council — the review-council

One **generalist** reviewer — all five rubrics in one profile, sampled N times
(default 5) — reviews a repo and returns cited findings plus a deterministic verdict.
Two modes: **manual** (review and report) and **autonomous** (fix and re-review until
the minimum is met).

M8.5 measured this against five isolated specialists at equal cost on a 22-defect
corpus: **22/22 injected defects against 13/22**. Two samples reported only 2 of 25
findings in common. The five specialists and the mode that spawned them were deleted;
their rubrics remain.

Everything ships inside this skill; every location resolves from its own directory —
no absolute paths.

**This skill is a DEPLOYMENT of the `review-council` repository, not a copy.**
`scripts/` is synced by `council setup skill` from `skills/council/SKILL.md` and
`scripts/`; an edit here is overwritten by the next sync, and an edit to the repo
needs the sync. `council setup skill --check` exits non-zero on drift — a stale
deployment is otherwise silent.

The sync **mirrors**: `--check` also reports files deleted in the repo, and a real
sync removes them. A copy-only sync would leave a deleted profile definition in
`assets/bots/` forever, so `council setup bots` here could reinstall profiles the repo
removed.

**Depends on** the `council-generalist` profile (all five rubrics) and the
orchestrator profile (see Bootstrap). The loop spawns the reviewer, so **no** profile
needs the `delegation` toolset. For a target repo inside WSL on a Windows host, load
`nixos-clan-flake` first.

## Architecture — the harness owns the convening

```
intake → convene (1 generalist x N samples) → bucket by dimension → aggregate
       → score → gate → (fix → re-review)* → terminate
```

**One profile, sampled N times.** The loop spawns `council-generalist` N times and
buckets findings by the dimension each declares, so the scorer still reads one file
per dimension.

`delegate_task` spawns in-process subagents that inherit the *parent's* `HERMES_HOME`,
so a delegated child cannot load a rubric installed in another profile — an earlier
version fanned out that way and silently ran five generic subagents wearing dimension
labels, applying none of the rubrics' anchors, hard gates or checklists.
`tests/test_council_loop.py` pins the fix.

A finding with no usable `dimension` is **dropped and counted**, never guessed at:
the wrong dimension would corrupt the score it feeds. A non-zero drop count is printed.

- **The orchestrator aggregates, it does not conduct.** It validates the reviewer
  files, builds the evidence matrix, and reports. The gate decides pass/fail.
- **It has no `delegation` toolset**: the harness is the only fan-out, and it is the
  one that applies the rubrics.
- **The reviewers are sub-agents of the council, not free-standing agents** — each a
  leaf, no `delegation`, no code edits, driven by the loop.

## Communication — token discipline

Every message a council agent emits is read by another agent, and re-read on each
pass. The contract lives in **one** place — the review prompt (`GENERALIST_PROMPT` in
`scripts/council_loop.py`); each rubric's `## Output` points at it rather than
restating it.

**The voice is the member's `SOUL.md`, not a skill.** It is slot #1 of the system
prompt — injected every turn, never chosen by the model. Each member ships its own
(`bots/<member>/SOUL.md`); `setup bots` copies it into the profile. A council profile
is its own `HERMES_HOME`, so the global `~/.hermes/SOUL.md` does **not** reach it.

The `caveman` skill is the **long form** of that voice, declared on demand: the
identity slot carries the condensed contract (~400 tokens); the skill loads only when
the short form is not enough. As a core skill it would put ~4.5 KB into every sample.

| Role | Skill | What it governs |
|---|---|---|
| reviewer | `caveman-review` | `claim` is one sentence; `falsifiable_check` is the exact command |
| reviewer, orchestrator, fixer | `caveman` / `ultracave` | The voice of every message and reply |
| reviewer | `defensive-patterns` | The bug classes a finding has to name, loaded when the diff is code |
| reviewer, orchestrator | `deterministic-quality-gates` | What a scored gate means: `beta`, `det`, a missing analyzer |
| fixer (`FIX_PROMPT`, under the orchestrator profile) | `surgical-patch`, `verify-and-stop` | Narrowest layer, no drive-by cleanup, stop when proof passes |
| orchestrator | `reply` | `next-steps.md` is a reply: labelled claims, impact first |

The on-demand half of each member's list lives in `review-council.toml`
(`members.<name>.skills`); `council setup bots` reports a name that does not resolve.

`cavecrew` and `caveman-explore` do **not** apply: they are delegation contracts, and
the council has no `delegation` toolset (see Architecture).

### Skills — core and optional

Two halves, declared per member in `review-council.toml`:

| | `core_skills` | `skills` |
|---|---|---|
| Installed into the profile? | **Yes** — always present, always loaded | **No** — never copied |
| A missing name is… | a **hard error** (`setup bots` refuses) | a **warning** (the member cannot load it) |
| Where it comes from | this repo's `skills/` | the mounted skill library |
| Who decides | a person, explicitly | a person, explicitly |

**`core_skills` is a static list, not a glob.** Globbed at install time it made the
set a side effect of adding a file: a new rubric silently reached every bot.
`setup bots` refuses a member whose core skill is absent — one that runs without its
rubrics reviews with nothing, silently.

**`skills` is the on-demand half.** The member has the `skills` toolset and the
library is mounted, so it loads these **by name, when the work calls for them** — the
reviewer's `web-app-security` is the worked example: the security rubric routes to it
only when the diff touches a web project, so a Nix-only review never pays for it.

```toml
[members.council-generalist]
core_skills = ["reviewer-architecture", "reviewer-correctness",
               "reviewer-performance", "reviewer-readability",
               "reviewer-security"]        # required, installed
skills      = ["web-app-security"]         # optional, on demand
```

Adding an optional skill is a config edit, not a code change: name it in `skills`;
`setup bots` reports whether it resolves.

### Measured: `probe_json` dominates the prompt

Rendered on the SHIPPED fixture (`tests/golden/target`), whole-repo scope, so these are
reproducible: render `generalist_prompt` for that fixture and compare
`json.dumps(probes, indent=2)` with `json.dumps(probes, separators=(",", ":"))`.

| | value |
|---|---|
| rendered reviewer prompt | 7,650 B |
| `probe_json`, indented | 4,575 B — **60%** |
| `probe_json`, compact | 2,498 B |
| saving from compacting | **805 B per sample**, 4,025 B per round at N=5 |

It is **not applied**: an agent may read indented JSON more reliably, and a token saving
that costs defect recall is a loss. `council ablate` exists to settle it — run it on the
22-defect corpus before changing serialisation.

Compressing the FINDINGS is not a lever. One archived sample measured 38% prose against
62% schema, and a one-sample A/B came out −3.9% — inside variance at n=1 per arm, so not
evidence of a saving. `rationale` and `beta_note` are not reviewer-written at all:
`merge_generalist_samples` emits fixed short strings.

**What is never compressed.** Negations, paths, symbols, numbers, rule ids, commands
and error strings are the payload. Compress the prose, never the evidence. Security
findings and anything irreversible get the full explanation.

## Known limits — measured, not suspected

**The prompt travels in a file.** The reviewer is spawned as
`hermes -p <profile> chat --query-file <path>`, never `-q <prompt>`. A real
repository's `probes.json` alone reaches ~400 KB, and the kernel caps one argument at
`MAX_ARG_STRLEN` (65536 B on Linux) — so `-q` dies with
`[Errno 7] Argument list too long`, and **every** sample returns `rc=126 / NO FILE`,
surfacing as `ESCALATE: gate could not evaluate the run`. It passes on a tiny fixture;
if a run fails uniformly on a real repo, check the prompt size before the rubric. The
prompt file sits next to the log, one per concurrent sample:
`<log>.<pid>.<thread>.prompt`.

**The prompt file must be unique per sample.** Derived from the shared log path, all
five wrote and then read the *same* file: whichever sample wrote last decided the
`out_path` in every child's prompt, all five wrote one `generalist-N.json`, and the
round reviewed one sample while reporting five. It is invisible afterwards — the round
still reports the sample count it intended, and a missing sample file reads as an
unlucky reviewer, not a lost one. Confirm five distinct `generalist-*.json` exist
after a round; treat "all log mentions are one index" as the signature.

**A council run outlives the turn that started it.** A whole-repo round is ~5 samples
plus an orchestrator turn each — measured at 20–30 minutes, past any foreground
timeout. A tracked background process is sent `SIGTERM` at turn end and dies
mid-sample with exit `143` (`128+15`); the round it leaves behind has a partial sample
set and no verdict. Launch it so it survives the turn (`persist_on_release`, or a
detached session) and read the verdict from the run dir.

**A uniform `rc=124` is late, not lost.** When every sample reports `rc=124 / NO FILE` and
the round ends `ESCALATE: gate could not evaluate the run`, the reviewer processes are
usually still running: the five `generalist-*.json` files land in `round-1/` minutes after
the round gave up. Look at the directory before believing the escalation. If the files are
there, `council.py merge <run-dir>/round-1` (it prints `merged N sample(s) from N file(s)`)
recovers them, and `council.py gate <run-dir>/round-1 --json --repo <repo>` then scores the
round normally. Measured twice on a real repository: budget about an hour for a whole-repo
round and treat the sample files, not the round's own timeout, as the completion signal.

**N samples re-report the same claim.** Five samples on one repository produced 60
finding entries collapsing to ~6 distinct issues — ~5× repetition, and it does **not**
dedupe, because each sample cites a slightly different line range. Count distinct
claims, never entries.

**Verify every finding before applying it.** On that run roughly half of the distinct
findings were actionable. A finding is a claim about the code, not a fact — the procedure
for turning claims into fixes or evidence-backed rejections is **Acting on findings**,
below.

## Acting on findings

The loop's job is to convert claims into either a verified fix or a rejection with
evidence. An edit made because the council said so is not a fix.

1. **Reproduce first, using the finding's own `falsifiable_check`.** Run the command it
   carries, or read the call path it names. The usual survivors are an unreachable branch
   (a caller already guarantees the invariant), pre-existing behaviour the diff did not
   touch, and a genuine gap described as a crash.
2. **Reject in the commit, not in silence.** A wrong finding is information: say what was
   claimed, what the reproduction returned, and why no edit followed. A silently dropped
   finding returns next round from a different sample.
3. **Check whether the finding is an artifact of the reviewer's own output encoding.** A
   quoted `\"` that appears in a finding but not in the file is the JSON encoding of the
   reviewer's tool output, not the file's bytes — and the "fix" that adds the escape
   *creates* the defect the finding described. Grep the file for the byte before editing,
   and expect the same shape elsewhere: a path reported with a `./` prefix the file lacks,
   a line number taken from a 0-based API (`row`), a count that came from a summary line.
4. **Fix the source, then sync, then test the deployment.** The deployed skill is a
   mirror: `council setup skill`, then `council setup skill --check`, then run the suite
   **in the deployed copy**. It legitimately skips the repo-only tests, and a pass there
   is what proves the mirror rather than the checkout.
5. **Re-run to converge, and read the trend in the files you fixed — not the aggregate.**
   Each round reviews the previous round's fixes, so those files' finding count is the
   measure: measured over eight rounds on one repository, 34 → 27 → 8 → 8 → 4 → 4 → 1 →
   none above `info`. Stop there. A high aggregate does not mean done: it can sit above the
   minimum while a blocker remains in a file you never touched, which is exactly what the
   gate reports as `not_satisfied` beside a passing score.
6. **A review of the council's own harness is a code review of the gate, and it finds the
   classes the gate exists to catch.** Expect an off-by-one in a reported line, a path
   normaliser that corrupts a path, and a scanner that ignores the harness's own skip
   list. Those are the silent failures the `deterministic-quality-gates` skill catalogues
   in its `silent-failure-patterns` reference — fix them there, not by weakening the rule.

## When to Use

- `/council`, or a request for a multi-specialist review of a repo, diff or feature
  → **manual mode**.
- "make it pass", "keep fixing until it's clean", "run the council autonomously"
  → **autonomous mode**.
- Not for a single-dimension review — run one reviewer profile directly.

## Resolve paths (do this first)

**1. This skill's directory.** `skill_view(name='council')` returns `skill_dir`. If
`skill_view` is unavailable, fall back to
`$HERMES_HOME/skills/autonomous-ai-agents/council`. Never hardcode a user path.

```
<skill>/scripts/council.py    the CLI — the entry point
 scripts/council_loop.py      the driver
 scripts/score_reviews.py     the deterministic gate
 scripts/probes.py            built-in deterministic checks
 scripts/doctor.py            toolchain report / provision
 scripts/install_bots.py      profile bootstrap
 assets/bots/                 the bot definitions
 assets/rubrics/              the reviewer rubrics
```

The copier — `sync_to_skill.py` — never ships itself. It lives in the council
repository checkout; run it there to reinstall or refresh this skill.

**2. The interpreter.** Hermes exports `HERMES_PYTHON` — the pinned Python Hermes runs
on. Use it, so these scripts work where no system `python3` exists (a NixOS host has
none; on Windows the interpreter is not named `python3`):

```bash
PY="${HERMES_PYTHON:-$(command -v python3 || command -v python)}"
```

Every command below uses `"$PY"`.

**3. The target project**, first match wins:

1. **An explicit path** in the invocation (`/council <path/to/project>`) — always wins.
2. **The session's anchored project.** On desktop call `desktop_project(action='list')`
   and, when `active_id` is set, use the active project's `primary_path`.
3. **The session working directory** — run the loop with no path argument; it infers
   from its own cwd, walking up to the nearest `.git`, else the nearest directory with
   `.hermes.md`, `HERMES.md`, `AGENTS.md`, `CLAUDE.md`, `pyproject.toml`,
   `package.json`, `Cargo.toml`, or `go.mod`.

**4. If nothing resolves**, the script exits 2. Do NOT review an unanchored
directory — a session with no project has the user's home as its cwd. Ask which
project they mean and offer the fix (anchor the session: desktop → Projects picker;
TUI/CLI → `hermes --in /path/to/project`) or an explicit path. **State the resolved
project in your reply** either way.

## Bootstrap (once per machine)

```bash
council setup                                      # GUIDED: writes your config, then installs
nix run .#council -- setup                         # the same, through nix
"$PY" "<skill_dir>/scripts/council.py" setup       # the same, with neither nix nor a clone
hermes -p council-orchestrator setup               # then credentials — Hermes keeps
hermes -p council-generalist setup                 # them per profile, and shares none
```

`council setup` is guided: it detects Hermes, asks the user's few choices (the gate,
the sample count, the mode), shows the plan, writes one editable file, then installs
the skill and the profiles. With no terminal it takes every default and says so.

`council setup skill` and `council setup bots` install either half alone;
`council setup --no-install` writes the config and stops.

### What you can change afterwards

Everything lives in `$HERMES_HOME/review-council.toml`. Edit it, then run
`council setup bots` to apply.

| key | what it does |
|---|---|
| `review.threshold` | the gate. Lower is stricter. PROVISIONAL — recalibrate on your repo. |
| `review.samples` | reviewer passes per round. More finds more, costs more time. |
| `review.mode` | `advisory` (report only), `semi` (fix, confirming), `full` (fix until it passes). |
| `members.<name>.toolsets` | exactly what that member may do. `delegation` is refused. |
| `members.<name>.model` / `.provider` | pin a model per member. Empty means inherit. |
| `members.<name>.skills` | extra skills to load, by name. |

TOML, not YAML: the framework is stdlib-only and the toolchain's interpreter has no
PyYAML; `tomllib` is stdlib. A broken file is refused with the line and the reason
rather than half-applied.

**Capabilities are read, not assumed** — the config is the one source (the installer
once hardcoded each member's toolsets, and `bots/*/bot.yaml` declared them in a file
nothing read).

**Run the CLI through `council.py`, never a module directly** — every module refuses a
hand invocation and points at the verb.

β is `tools_ran / tools_expected`; a missing analyzer lowers β rather than failing the
run. Check the toolchain before the first review:

```bash
nix run .#council -- doctor --repo "<project>"                    # if nix is available
"$PY" "<skill_dir>/scripts/council.py" doctor --repo "<project>"  # otherwise
```

It reports detected stacks, β now vs reachable, and per-missing-tool advice
(declarative under nix: add to `flake.nix`). Offer `--install`; **never install
without asking**. The built-in probes work with zero installs.

## Driving the council with `/goal` (native Hermes)

The `--mode full` loop is this repository's own: it spawns each reviewer and the fixer,
and the gate decides. `/goal` is the **native alternative** for a single session, and it
wraps the same gate rather than replacing the loop. Hermes ships the two features the
loop imitates:

* a **completion contract** — `outcome`, `verification`, `constraints`, `boundaries`,
  `stop_when` — which tightens both the continuation prompt and the judge;
* **quality gates** — a deterministic shell command that must exit 0 before the goal
  can be judged done. Gates run *before* the judge, and a red gate skips the judge
  entirely, feeding its exit code and output tail back as the next turn's prompt.

The council's gate is already such a command:

```bash
council goal <repo>          # prints the contract and the gate, ready to paste
council goal <repo> --json   # the same fields, machine-readable
```

Paste the output into a Hermes session. `/goal` is a session command, so this verb
cannot set it for you. The gate is `council gate --latest --repo <repo>`, which scores
the newest run and exits 0 only when the run is satisfied — the decision to stop is a
command's exit code, not a model's opinion. `/goal status`, `/goal pause`, `/subgoal`
and the turn budget then work on it for free.

## Manual mode — review the current stage

```bash
nix run .#council -- --mode advisory --max-rounds 1
"$PY" "<skill_dir>/scripts/council.py" review --mode advisory --max-rounds 1   # without nix
```

**Prefer the `nix run` form when nix is available.** It puts the *pinned* toolchain on
PATH, so the probes are the analyzers `flake.lock` names rather than whatever the
machine has — which is what makes β and the score comparable between machines. Without
nix the `council.py` call still works; the built-in probes need no installs.

A flag with no verb means `review`, so existing flags keep working unchanged.
`advisory` reviews and reports but never edits; `--max-rounds 1` stops after the one
review. There is no separate manual path: the loop *is* the council.

Run it with `terminal(background=True, persist_on_release=True, notify=True)` — a full
round takes minutes, and a plain background job is killed at turn end.

Report in this order: the resolved project path (and why, if inferred) · the verdict
and aggregate vs minimum · each reviewer's top findings with `file:line` · any reviewer
that produced no file (a gap, not a clean bill of health).

## Autonomous mode

```bash
nix run .#council -- --mode full --scope working-tree
"$PY" "<skill_dir>/scripts/council.py" review --mode full --scope working-tree   # without nix
```

Omit the path to infer the project from the session; it refuses (exit 2) when the
session is not anchored.

Each round: the harness runs the probes once, convenes the reviewer (one generalist
profile, sampled N times), runs the orchestrator to set the goals and aggregate, then
runs the gate. A round prints one line per dimension (`ok` / `NO FILE`).

| Flag | Default | Meaning |
|---|---|---|
| `<repo>` | *inferred* | Target repo; omit to infer from the session |
| `--mode` | `full` | `full` auto-applies fixes; `semi` asks before each edit; `advisory` reports only |
| `--scope` | `working-tree` | `diff` / `working-tree` / `whole-repo` |
| `--baseline` | `off` | `auto` (newest qualifying run) or a run-root path: read only what changed since that whole-repo run, carrying its findings for the rest |
| `--threshold` | calibrated (`80.0`) | **Minimum** aggregate required to pass — the requirement |
| `--min-rounds` | `1` | Always attempt at least this many rounds |
| `--max-rounds` | `8` | Hard safety cap, not the normal stopping mechanism |
| `--budget-seconds` | `0` | Wall-clock budget (`0` = unlimited); when spent, stop and hand over the plan |
| `--epsilon` | `0.5` | Marginal-improvement floor; below it the run is stalled |
| `--dry-run` | off | Print the plan and the inferred project, then exit |

**The threshold is the minimum, not the target.** The loop stops when the minimum is
met *and* gains stall, or when the budget/cap/terminators fire. Exit 0 = satisfied,
1 = escalated, 2 = error (including "not anchored"). The verdict comes from
`score_reviews.py` reading reviewer JSON — never from orchestrator prose. Gate exit 0
requires `aggregate >= threshold` **and** no open blocking finding: `high` or `critical`
in security or correctness, `critical` anywhere else.

Security and correctness are the hard requirements. A `high` there blocks, because the
observed cost of getting one wrong is a supply-chain compromise or a build that does not
work — nine well-regarded repositories produced 93 of 94 blocking findings in exactly
those two dimensions. Performance, readability and architecture block only at `critical`:
they move the score without vetoing a merge, while a `critical` anywhere still blocks.

For the design rationale behind the gates, weighting and calibration, load
`deterministic-quality-gates`; this skill is its operational side.

## Incremental runs — `--baseline`

A whole-repo review re-reads files nobody touched. `--baseline` stops that: the first
whole-repo run is the baseline, and later runs read only what changed, carrying the
baseline's findings for everything else.

```bash
nix run .#council -- review <repo>                   # the baseline (whole-repo)
nix run .#council -- review <repo> --baseline auto   # incremental from here on
```

Carried findings go back into the numerator before the gate reads the files, so
`carried + new` still covers the whole repository and the aggregate stays comparable
to the baseline. The probes re-run whole-repo every time, so the deterministic half of
β is never stale.

**It is not `--scope diff`.** That narrows what is read and puts nothing back, so the
score rises because less was reviewed — measured, 69.71 to 89.61 on identical code,
clearing a threshold of 87.11. Never score a diff-scoped run against a whole-repo
threshold.

Three things to know:

- **The LLM self-score is carried from the baseline.** A reviewer that saw six files
  cannot honestly score a fifty-file repository, so its number is discarded and the
  baseline's is kept; the new signal lands in `det`. An incremental score is a
  *tracking* score, comparable to its own baseline and not to a fresh whole-repo run —
  which is why `mode` is recorded.
- **It saves little on a small repository.** The saving scales with the unchanged
  fraction: 50 files with 16 changed saves almost nothing; 2000 files with 5 changed
  saves most of the sampling cost.
- **A baseline must be complete.** `baseline.is_baseline` requires a whole-repo scope,
  a pinned sha, all five dimension files, and `dropped == 0` recorded. Older runs
  predate that field and are rejected rather than assumed complete.

Inspect before running:

```bash
"$PY" "<skill_dir>/scripts/council.py" baseline --repo <repo> status    # the baseline, or why none qualifies
"$PY" "<skill_dir>/scripts/council.py" baseline --repo <repo> changed   # what changed, what it invalidates
```

## Next steps — the handover plan

Every run writes `<run-root>/next-steps.md` (path recorded in `outcome.json`),
satisfied or not. Report its path. It carries the outcome and why it stopped, the
score trajectory, **separately** the aggregate vs the minimum and what is blocking,
the required work, the desirable work ranked by how much aggregate each item can move,
and the exact command to resume.

When a run stops early, that plan is the deliverable — present it rather than
describing the run as a failure.

## Reading a run

```bash
"$PY" "<skill_dir>/scripts/council.py" gate "<run-dir>" --json --repo "<project>"
```

`<run-dir>` is `<project>/.review-council/<timestamp>/round-N`. The JSON gives the
aggregate, per-dimension `llm`/`det`/`beta`/`score`, open blocking findings, and
detected stacks.

## Hard rules

- **Never report a run as passing on prose.** Read the gate's exit code.
- **Never invent findings** for a reviewer that failed or returned invalid schema.
- **Never invent a tool result.** A tool that could not run is `{"ran": false}` —
  claiming otherwise inflates β and is a fabrication.
- If the orchestrator reports a delegation-budget error, say so — do not summarize as
  if the council ran.
- Hold the rubric and threshold **out** of the reviewers' context (anti-gaming).
- **Never hardcode a machine path**, and never review an unanchored directory.

## Requirements

- Hermes Agent with the reviewer and orchestrator profiles installed (see Bootstrap).
  The council harness spawns the reviewer; the orchestrator does **not** need the
  `delegation` toolset.
- Working provider credentials per profile (`hermes -p <bot> setup`).
- External analyzers are optional — `council doctor` reports what is missing.

## Evaluating the council

The ablation, its pre-registered rule, the four arms, the scoring pitfalls and the
injection rules are framework-author material and live in the repository that
publishes this skill — not here. `council ablate` and `council corpus` are **dev**
verbs: they exist in a checkout and the devshell, not in the shipped app or the image.

From a checkout, `REVIEW_COUNCIL_AUDIENCE=dev` exposes the dev surface — `version`,
`calibrate`, `golden`, `ablate`, `corpus`. Without it the CLI answers `not a verb, and no
such path`, which reads like a missing module rather than a hidden verb.
