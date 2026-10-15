---
name: council
description: "Convene the code-review council on a repo."
version: 3.3.0
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
(default 5) — reviews a repo and returns cited findings plus a deterministic
verdict. Two modes: **manual** (review the current stage and report) and
**autonomous** (fix and re-review until the minimum is met).

M8.5 measured this against five isolated specialists at equal cost on a 22-defect
corpus: **22/22 injected defects against 13/22**. Across two samples only 2 of 25
findings were reported by both, so the samples are complementary rather than
redundant — that is the mechanism behind the result. The five specialists, and the
mode that spawned them, were deleted; their rubrics remain.

Everything ships inside this skill, and every location resolves at runtime from the
skill's own directory — no absolute paths.

**This skill is a DEPLOYMENT of the `review-council` repository, not a copy.**
`scripts/` is synced by `council setup skill`, which reads `skills/council/SKILL.md`
and `scripts/` there. Edit the REPO and re-sync: an edit made here is overwritten by
the next sync, and an edit to the repo changes nothing until the sync runs. Check
with `council setup skill --check`, which exits non-zero on drift. A stale
deployment is silent — `/council` keeps running the old code and reporting the old
behaviour, with nothing to say a newer version exists.

The sync **mirrors**: `--check` also reports files deleted in the repo, and a real
sync removes them. That direction matters — a sync that only ever copies leaves a
deleted profile definition in `assets/bots/` forever, and `council setup bots` run
from this skill would then reinstall the very profiles the repo removed.

**Depends on** the `council-generalist` profile, which carries all five rubrics, and
the orchestrator profile being installed (see Bootstrap). The loop spawns the
reviewer itself, so **no** profile needs the `delegation` toolset. If the target repo
lives inside WSL on a Windows host, load `nixos-clan-flake` first — it owns reaching
and verifying code across that boundary.

## Architecture — the harness owns the convening

```
intake → convene (1 generalist x N samples) → bucket by dimension → aggregate
       → score → gate → (fix → re-review)* → terminate
```

**One profile, sampled N times.** The loop spawns `council-generalist` N times and
buckets the findings by the dimension each declares, so the scorer still reads one
file per dimension and nothing downstream changes.

The profile-per-dimension detail matters more than it looks. `delegate_task` spawns
in-process subagents that inherit the *parent's* `HERMES_HOME`, so a delegated child
cannot load a rubric that lives in a different profile. An earlier version fanned out
that way and silently ran five generic subagents wearing dimension labels, applying
none of the rubrics' scoring anchors, hard gates or checklists.
`tests/test_council_loop.py` pins the fix.

A finding with no usable `dimension` is **dropped and counted**, never guessed at:
attributing it to the wrong dimension would corrupt the per-dimension score it feeds.
A non-zero drop count is printed — a silent drop would just lower a score with
nothing to say why.

Consequences worth knowing:

- **The orchestrator aggregates, it does not conduct.** It validates the reviewer
  files, builds the evidence matrix, and reports. The gate decides pass/fail.
- **It has no `delegation` toolset**, by design: the harness is the only thing that
  spawns agents, so there is exactly one fan-out mechanism and it is the one that
  applies the rubrics.
- **The reviewers are sub-agents of the council, not free-standing agents.** Each is
  a leaf — no `delegation`, no code edits — driven by the loop.

## Communication — token discipline

Every message a council agent emits is read by another agent, and re-read on each
pass. The contract lives in **one** place — the review prompt (`GENERALIST_PROMPT` in
`scripts/council_loop.py`) — so it cannot drift across five rubrics. Each rubric's
`## Output` section points at it rather than restating it.

**The voice is the member's `SOUL.md`, not a skill.** `SOUL.md` is slot #1 of the
system prompt — injected every turn, never chosen by the model. Each member ships its
own in this repo (`bots/<member>/SOUL.md`) and `setup bots` copies it into the
profile. A council profile is its own `HERMES_HOME`, so the global
`~/.hermes/SOUL.md` does **not** reach it; the voice has to be shipped here.

The `caveman` skill is the **long form** of that same voice, declared on demand — the
identity slot carries the condensed contract (~400 tokens), and the skill is loaded
only when the short form is not enough. Installing it as a core skill would put ~4.5 KB
into every sample to restate what `SOUL.md` already says.

**Which skill applies to which role:**

| Role | Skill | What it governs |
|---|---|---|
| reviewer | `caveman-review` | `claim` is one sentence; `falsifiable_check` is the exact command |
| reviewer, orchestrator, fixer | `caveman` / `ultracave` | The voice of every message and reply |
| fixer (`FIX_PROMPT`) | `surgical-patch`, `verify-and-stop` | Narrowest layer, no drive-by cleanup, stop when proof passes |

**What does NOT apply, and why.** `cavecrew` and `caveman-explore` are delegation
contracts, and the council deliberately has **no `delegation` toolset** — the harness
is the only thing that spawns agents (see Architecture). They are general Hermes
skills, not council ones. Do not wire them here; they would name a capability no
council agent has.

### Skills — core and optional

Two halves, declared per member in `review-council.toml`, and they behave
differently on purpose:

| | `core_skills` | `skills` |
|---|---|---|
| Installed into the profile? | **Yes** — always present, always loaded | **No** — never copied |
| A missing name is… | a **hard error** (`setup bots` refuses) | a **warning** (the member just cannot load it) |
| Where it comes from | this repo's `skills/` | the mounted skill library |
| Who decides | a person, explicitly | a person, explicitly |

**`core_skills` is a static list, not a glob.** It used to be `reviewer-*` globbed at
install time, which made the set a side effect of adding a file: a new rubric
silently reached every bot. A list is a decision, and `setup bots` refuses to install
a member whose core skill is absent — a member that runs without its rubrics reviews
with nothing and reports nothing, silently.

**`skills` is the on-demand half.** The member has the `skills` toolset and the
library is mounted, so it loads these **by name, when the work calls for them**. The
reviewer's `web-app-security` is the worked example: the security rubric routes to it
only when the diff touches a web project, so a Nix-only review never pays for it.

```toml
[members.council-generalist]
core_skills = ["reviewer-architecture", "reviewer-correctness",
               "reviewer-performance", "reviewer-readability",
               "reviewer-security"]        # required, installed
skills      = ["web-app-security"]         # optional, on demand
```

Adding an optional skill is a config edit, not a code change: name it in `skills` and
`setup bots` reports whether it resolves. This key used to be written to the config
and read by nothing — a user could set it and see no effect. It is read now.

### Measured: the prose instruction is the small lever

One generalist sample against a two-file Python fixture, whole-repo scope:

| | value |
|---|---|
| findings file | 6562 B, 7 findings |
| prose (`claim` + `falsifiable_check`) | 2515 B — **38%** |
| structural (keys, ids, locations, `tools_run`, indentation) | 4047 B — **62%** |
| mean `claim` | 182 chars |

A one-sample A/B against the pre-change prompt (7800 B, 8 findings) gives **937 vs 975
bytes per finding, −3.9%**. At n=1 per arm that is inside sample variance and is **not
evidence of a saving**. The prose instruction costs +401 B per sample (+2005 B per round
at the default N=5), so it must be justified by output savings that have not yet been
demonstrated.

The reason the ceiling is low is structural: most of the file is schema, not filler.
`rationale` and `beta_note` — the fields that look like prose — are **not written by
the reviewer at all**; `merge_generalist_samples` generates them as fixed short strings
(`council_loop.py`, the collapsed-mode path). Do not chase them.

### The dominant measured lever is structural, and untested

`probe_json` is **57% of the rendered reviewer prompt** and is injected
pretty-printed (`json.dumps(probes, indent=2)`) into every sample. Serialising it
compactly saves **1006 B per sample — 5030 B per round** at N=5, with no information
lost. That is 2.5× the cost of the prose instruction, in the direction paid N times.

It is **not applied**, because the trade is unmeasured in the other direction: an agent
may read indented JSON more reliably, and a token saving that costs defect recall is a
loss. `council ablate` exists to settle exactly this — run it on the 22-defect corpus
before changing serialization or extending the terse contract.

**What is never compressed.** Negations, paths, symbols, numbers, rule ids, commands
and error strings are the payload. Compress the prose, never the evidence. Security
findings and anything irreversible get the full explanation — a misread one is
expensive, and the format is not worth a wrong fix.

## Known limits — measured, not suspected

**The prompt travels in a file.** The reviewer is spawned as
`hermes -p <profile> chat --query-file <path>`; never `-q <prompt>`. A real
repository's `probes.json` alone reaches ~400 KB, and the kernel caps a single
argument at `MAX_ARG_STRLEN` (65536 B on Linux) — so `-q` dies with
`[Errno 7] Argument list too long` and **every** sample returns `rc=126 / NO FILE`,
which surfaces as `ESCALATE: gate could not evaluate the run`. It passes on a tiny
fixture, which is how it survived: if a run fails uniformly on a real repo, check the
prompt size before the rubric. The prompt file is kept next to the log, one per
concurrent sample: `<log>.<pid>.<thread>.prompt`.

**The prompt file must be unique per sample.** It was derived from the log path, which
the samples share, so all five wrote and then read the *same* file: whichever sample
wrote last decided the `out_path` embedded in every child's prompt, all five wrote one
`generalist-N.json`, and the round reviewed a single sample while reporting five. It is
invisible afterwards — the round still reports the sample count it intended, and a
missing sample file reads as an unlucky reviewer rather than a lost one. Confirm five
distinct `generalist-*.json` exist after a round, and treat "all log mentions are one
index" as the signature.

**A council run outlives the turn that started it.** A whole-repo round is ~5 samples
plus an orchestrator turn each — measured at 20–30 minutes, which is past any single
foreground timeout. A run started as a tracked background process is sent `SIGTERM`
when its turn ends, and dies mid-sample with exit `143` (`128+15`); the round it leaves
behind has a partial sample set and no verdict. Launch it so it survives the turn
(`persist_on_release`, or a detached session) and read the verdict from the run dir
rather than from a live process.

**N samples re-report the same claim.** Five samples on one repository produced 60
finding entries collapsing to ~6 distinct issues — the repetition is ~5×, and it does
**not** dedupe, because each sample cites a slightly different line range. Count
distinct claims, never entries.

**Verify every finding before applying it.** On that run roughly half the distinct
findings were actionable. One filed as a `TypeError` crash was unreachable — the
caller only returns runs that already satisfy the invariant — while the same line was
a genuine type-checker gap. A finding is a claim about the code, not a fact: read the
call path before editing, and say so when it does not hold.

## When to Use

- `/council`, or a request for a multi-specialist review of a repo, diff or feature
  → **manual mode**.
- "make it pass", "keep fixing until it's clean", "run the council autonomously"
  → **autonomous mode**.
- Not for a single-dimension review — run one reviewer profile directly.

## Resolve paths (do this first)

**1. This skill's directory.** `skill_view(name='council')` returns `skill_dir`.
If `skill_view` is unavailable, fall back to
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

The copier itself — `sync_to_skill.py` — is deliberately **not** part of the
deployment: it never ships itself. It lives in the council repository checkout; run it
from there to reinstall or refresh this skill.

**2. The interpreter.** Hermes exports `HERMES_PYTHON` — the pinned Python Hermes
itself runs on. Use it, so these scripts work where no system `python3` exists (a
NixOS host has none, and on Windows the interpreter is not named `python3`):

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
project they mean, and offer the fix (anchor the session: desktop → Projects picker;
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

`council setup` is guided: it detects Hermes, asks the few things that are the
user's to decide (the gate, the sample count, the mode), shows what it is about to
do, writes one editable file, then installs the skill and the profiles. It never
hangs: with no terminal it takes every default and says so.

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

It is TOML because the framework is stdlib-only and the toolchain's interpreter has
no PyYAML; `tomllib` is stdlib. The file round-trips through a real parser before it
is written, and a broken one is refused with the line and the reason rather than
half-applied.

**Capabilities are read, not assumed.** The installer used to hardcode the toolsets
while `bots/*/bot.yaml` declared them again in a file nothing read, so editing either
changed nothing. The config is now the one source.

**Run the CLI through `council.py`, never a module directly.** Every module refuses a
hand invocation — `python3 .../scripts/install_bots.py` exits with a message pointing
at the verb — because a module run by hand bypasses the CLI's argument handling.

Check the toolchain before the first review — β is `tools_ran / tools_expected`, and a
missing analyzer lowers β rather than failing the run:

```bash
nix run .#council -- doctor --repo "<project>"                    # if nix is available
"$PY" "<skill_dir>/scripts/council.py" doctor --repo "<project>"  # otherwise
```

It reports detected stacks, β now vs reachable, and per-missing-tool advice. With nix
available the advice is declarative (add to `flake.nix`). Offer `--install`; **never
install anything without asking**. The built-in probes work with zero installs, so the
framework is useful on a bare machine.

## Driving the council with `/goal` (native Hermes)

The council's autonomous mode is a **`/goal`**, not a bespoke loop. Hermes ships two
features that already do what this framework used to hand-roll:

* a **completion contract** — `outcome`, `verification`, `constraints`, `boundaries`,
  `stop_when` — which tightens both the continuation prompt and the judge;
* **quality gates** — a deterministic shell command that must exit 0 before the goal
  can be judged done. Gates run *before* the judge, and a red gate skips the judge
  entirely, feeding its exit code and output tail back as the next turn's prompt.

The council's gate is already such a command, so:

```bash
council goal <repo>          # prints the contract and the gate, ready to paste
council goal <repo> --json   # the same fields, machine-readable
```

Paste the output into a Hermes session. `/goal` is a session command, so this verb
cannot set it for you — it prints what to set. The gate is
`council gate --latest --repo <repo>`, which scores the newest run and exits 0 only
when the run is satisfied, so the decision to stop is a command's exit code rather
than a model's opinion. `/goal status`, `/goal pause`, `/subgoal` and the turn budget
then work on it for free.

## Manual mode — review the current stage

```bash
nix run .#council -- --mode advisory --max-rounds 1
"$PY" "<skill_dir>/scripts/council_loop.py" --mode advisory --max-rounds 1   # without nix
```

**Prefer the `nix run` form when nix is available.** It puts the *pinned* toolchain on
PATH, so the probes are the analyzers `flake.lock` names rather than whatever the
machine happens to have — which is what makes β and the score comparable between
machines. Without nix the direct call still works; the built-in probes need no installs.

A flag with no verb means `review`, so the existing flags keep working unchanged.
`advisory` reviews and reports but never edits, and `--max-rounds 1` stops after the
one review. There is no separate manual path any more: the loop *is* the council, so
the two modes cannot drift apart.

Run it with `terminal(background=True, persist_on_release=True, notify=True)` — a full
round takes minutes, and a plain background job is killed at turn end.

Report in this order: the resolved project path (and why, if inferred) · the verdict
and aggregate vs minimum · each reviewer's top findings with `file:line` · any reviewer
that produced no file (that is a gap, not a clean bill of health).

## Autonomous mode

```bash
nix run .#council -- --mode full --scope working-tree
"$PY" "<skill_dir>/scripts/council_loop.py" --mode full --scope working-tree   # without nix
```

Omit the path to infer the project from the session; it refuses (exit 2) when the
session is not anchored.

Each round: the harness runs the probes once, convenes the reviewer (one generalist
profile, sampled N times), runs the orchestrator to set the goals and aggregate, then
runs the gate. A round prints one line per dimension (`ok` / `NO FILE`) so a partial
council is visible immediately.

| Flag | Default | Meaning |
|---|---|---|
| `<repo>` | *inferred* | Target repo; omit to infer from the session |
| `--mode` | `full` | `full` auto-applies fixes; `semi` asks before each edit; `advisory` reports only |
| `--scope` | `working-tree` | `diff` / `working-tree` / `whole-repo` |
| `--baseline` | `off` | `auto` (newest qualifying run) or a run-root path: read only what changed since that whole-repo run, carrying its findings for the rest |
| `--threshold` | `80` | **Minimum** aggregate required to pass — the requirement |
| `--min-rounds` | `1` | Always attempt at least this many rounds |
| `--max-rounds` | `8` | Hard safety cap, not the normal stopping mechanism |
| `--budget-seconds` | `0` | Wall-clock budget (`0` = unlimited); when spent, stop and hand over the plan |
| `--epsilon` | `0.5` | Marginal-improvement floor; below it the run is stalled |
| `--dry-run` | off | Print the plan and the inferred project, then exit |

**The threshold is the minimum, not the target.** The loop stops when the minimum is
met *and* gains stall, or when the budget/cap/terminators fire. Exit 0 = satisfied,
1 = escalated, 2 = error (including "not anchored"). The verdict comes from
`score_reviews.py` reading reviewer JSON — never from orchestrator prose. Gate exit 0
requires `aggregate >= threshold` **and** no open high/critical finding.

For the design rationale behind the gates, weighting and calibration, load
`deterministic-quality-gates`. This skill is the operational side of it.

## Incremental runs — `--baseline`

A whole-repo review re-reads files nobody touched. `--baseline` stops that: the first
whole-repo run is the baseline, and later runs read only what changed, carrying the
baseline's findings for everything else.

```bash
nix run .#council -- review <repo>                   # the baseline (whole-repo)
nix run .#council -- review <repo> --baseline auto   # incremental from here on
```

The carried findings go back into the numerator before the gate reads the files, so
`carried + new` still covers the whole repository and the aggregate stays comparable
to the baseline. The probes re-run whole-repo every time, so the deterministic half of
β is never stale.

**It is not `--scope diff`.** That narrows what is read and puts nothing back, so the
score rises because less was reviewed — measured, 69.71 to 89.61 on identical code,
clearing a threshold of 87.11. Never score a diff-scoped run against a whole-repo
threshold.

Three things to know before using it:

- **The LLM self-score is carried from the baseline.** A reviewer that saw six files
  cannot honestly score a fifty-file repository, so its number is discarded and the
  baseline's is kept. The new signal lands in `det`. An incremental score is a
  *tracking* score, comparable to its own baseline and not to a fresh whole-repo run —
  which is why `mode` is recorded.
- **It saves little on a small repository.** The saving scales with the unchanged
  fraction. 50 files with 16 changed saves almost nothing; 2000 files with 5 changed
  saves most of the sampling cost.
- **A baseline must be complete.** `baseline.is_baseline` requires a whole-repo scope,
  a pinned sha, all five dimension files, and `dropped == 0` recorded. Older runs
  predate that field and are rejected rather than assumed complete.

Inspect before running:

```bash
"$PY" "<skill_dir>/scripts/baseline.py" --repo <repo> status    # the baseline, or why none qualifies
"$PY" "<skill_dir>/scripts/baseline.py" --repo <repo> changed   # what changed, what it invalidates
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
"$PY" "<skill_dir>/scripts/score_reviews.py" "<run-dir>" --json --repo "<project>"
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
