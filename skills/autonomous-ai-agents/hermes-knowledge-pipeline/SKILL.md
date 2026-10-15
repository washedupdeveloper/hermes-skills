---
name: hermes-knowledge-pipeline
description: "Build a Hermes KB pipeline: capture, distill, index."
version: 3.3.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [hermes-agent, knowledge-base, wiki, cron, automation, portability, obsidian, cross-platform]
    category: autonomous-ai-agents
    related_skills: [llm-wiki, obsidian, hermes-project-handoff]
---

# Hermes Knowledge Pipeline

Build a knowledge base that **accumulates without being asked**: staged capture into an
inbox, scheduled distillation of finished sessions, deterministic indexing and lint, and
one path resolver that works on Windows, WSL2, Linux and macOS.

## Relationship to the bundled skills

`llm-wiki` owns page *content* conventions (SCHEMA.md, frontmatter, tag taxonomy, the 13
lint checks). `obsidian` owns vault file operations. **This skill owns the pipeline around
them** — where knowledge comes from, how it is gated, what runs on a schedule, and how
paths stay portable. Load all three when doing the work; do not restate their conventions here.

## When to Use

- "Set up a knowledge base / second brain / wiki that the agent maintains."
- Making an agent capture what it learns from its own sessions, not just on request.
- Porting an existing vault or KB setup between Windows, WSL2 and Unix hosts.
- Any Hermes setup whose config needs one path that both a Windows-side and a WSL-side
  process can open.

## Procedure

### Phase 1 — one root, resolved per machine

1. Copy `scripts/kb_root.py` to a stable location and run it. It prints the resolved root in
   **native forward-slash** form.
2. Register it — never hand-edit `.env` or `config.yaml`:
   ```bash
   hermes config set WIKI_PATH "$(python <path>/kb_root.py)"
   hermes config set OBSIDIAN_VAULT_PATH "$(python <path>/kb_root.py)"
   ```
3. On Windows, also create a junction so WSL2 can reach the same bytes without `/mnt/c/...`:
   ```bash
   python -c "import subprocess;subprocess.run(['cmd','/c','mklink','/J',r'C:/Users/<u>/AI-Knowledge',r'C:/Users/<u>/Documents/AI-Knowledge'])"
   ```
   WSL2 side: `ln -s /mnt/c/Users/<u>/Documents/AI-Knowledge ~/AI-Knowledge`, then set that
   host's `WIKI_PATH` to the local path.
4. Write `.gitattributes` in the vault root (`* text=auto eol=lf`) and `.obsidian/app.json`
   `{"userIgnoreFilters": ["raw/", "_archive/", "_meta/"]}`. Keep `inbox/` visible.
5. Have the agent initialise the wiki structure (delegate to `llm-wiki`), then verify with
   `hermes skills list` that both skills load.
6. Write **`AGENTS.md`** at the vault root — the in-repo contract, and the highest-value file in
   the whole setup. It is the cross-agent standard entry point, so an agent opening the repo is
   told the rules without loading a skill. Keep it short and imperative: where it may write, what
   is generated and must not be edited, the frontmatter contract, the rules lint enforces, and
   the two commands that verify the work. Then add `--workdir <vault>` to the agent cron jobs so
   it is injected automatically.
7. Put the tag taxonomy and `schema_version` in a machine-readable fenced block inside
   `SCHEMA.md` (see `references/cron-pipeline-primitives.md` for the parser contract), and state
   in `SCHEMA.md` that `index.md` is generated. Do not restate the taxonomy in prose.

### Phase 2 — capture without being asked

6. Add the `inbox/` contract to `SCHEMA.md`: the agent may write **only** to `inbox/`, always
   with `status: proposed`, `proposed_by: <session_id>`, and a `sources:` entry. Canonical
   directories fill only by promotion — never by hand:
   ```bash
   python <path>/kb_promote.py <proposal> [--to concepts] [--dry-run]
   ```
   It moves the file to its type directory, sets `status: approved`, appends the log entry, and
   refuses when the page is not in `inbox/`, is not `proposed`, would collide with an existing
   page, or would land as an orphan. `index.md` regenerates itself — do not add pages to it.
7. Install the collector under `$HERMES_HOME/scripts/` (cron resolves `--script` relative to
   that directory) and schedule it:
   ```bash
   hermes cron create "0 3 * * *" --name kb-distill --skill llm-wiki \
     --script kb_collect.py --monitor-script kb_collect.py --deliver local
   ```

### Phase 3 — deterministic index and lint

8. Install `scripts/kb_reindex.py` and run it hourly with no model at all:
   ```bash
   hermes cron create "0 * * * *" --name kb-reindex --script kb_reindex.py --no-agent --deliver local
   ```
9. Add a weekly agent pass that reasons over the deterministic report rather than
   re-deriving it. Give it the same script so findings arrive in the prompt:
   ```bash
   hermes cron create "every monday 9am" "Lint the knowledge base..." \
     --name kb-lint --skill llm-wiki --script kb_reindex.py --deliver local
   ```
   Check `hermes gateway status` before targeting a messaging platform — a `--deliver`
   target that is not paired errors on every run, so `local` is the safe default.

### Phase 4 — versioning

10. `git init` the vault and set a **repo-local** identity (`git -C <vault> config user.name`),
    never the user's global git config — this is not the operator's repo.
11. Schedule the commit job. This is the pipeline's safety net: `raw/` immutability is a
    convention that lint only *reports* on, and git is what makes a clobbered source
    recoverable. It deliberately never pushes; a remote is a per-machine decision.
    ```bash
    hermes cron create "30 * * * *" --name kb-commit --script kb_commit.py --no-agent --deliver local
    ```
12. Optional, and usually not worth it: a `pre_tool_call` hook to block writes under `raw/`.
    Shell hooks run `shell=False` + `shlex.split`, so a Python hook spawns a subprocess on
    *every* matched tool call — a permanent latency tax on the whole tool loop — and needs
    consent satisfied for non-interactive runs. Lint plus git already cover the risk; add
    the hook only if something else is writing to the vault unsupervised.

### Phase 5 — the human surface

13. **Register the vault with Obsidian. Creating the folder is not enough.** A folder with a
    `.obsidian/` directory is *not* a registered vault — Obsidian creates that directory on
    first open, so pre-creating it accomplishes nothing, and `obsidian://` links fail with
    "Unable to find a vault for the URL". Registration means an entry in the app-level
    registry (`%APPDATA%\obsidian\obsidian.json` on Windows,
    `~/.config/obsidian/obsidian.json` on Linux,
    `~/Library/Application Support/obsidian/obsidian.json` on macOS):
    `{"vaults": {"<16-hex-id>": {"path": ..., "ts": <epoch-ms>, "open": bool}}}`.
14. **Quit Obsidian before editing that registry.** A running Obsidian holds it in memory and
    rewrites it on exit, silently discarding the edit — the registration appears to work and
    vanishes on the next restart. Order: quit and wait for the processes to exit, back up the
    file, add the entry, re-read to verify, restart. Use `open: false` unless you intend to
    hijack the vault Obsidian last had open. Once registered, switching needs no restart:
    `obsidian://open?vault=<id>`.
15. If Obsidian is genuinely unavailable, accept a chat-based ratification path instead — but
    say so explicitly. The gate is worthless if nobody reviews it: a proposal nobody reads is
    indistinguishable from no proposal.

### Phase 6 — retirement (archiving iterations)

16. Nothing is ever deleted. Superseded knowledge moves to `_archive/` so a later iteration can
    see what was believed before and why it changed. Never do this by hand — it is five
    coordinated edits (move the file, stamp the archived page, stamp the successor, repoint
    inbound links, log it) and one always gets forgotten:
    ```bash
    python <path>/kb_archive.py <old-slug> --superseded-by <new-slug> --reason "why"
    ```
    It refuses to run when either page cannot be resolved, the successor is itself archived, or
    the page is a pending proposal (reject those instead). Then confirm the vault is still
    clean with `kb_reindex.py`.

## Always-On Rules

- **One root, derived everywhere else.** Never hardcode an absolute path in a shared skill,
  doc or script — the OS default resolves per machine, and the second env var is derived from
  the first. Two independent absolute paths drift apart silently.
- **Emit native forward-slash paths** (`C:/Users/x/...`). It is the only form MSYS bash,
  `cmd.exe` and native Windows programs all accept; `/c/Users/x` breaks native tools and
  `C:\Users\x` needs escaping in every shell.
- **`hermes config set` routes a bare `UPPER_SNAKE` key to the profile `.env` automatically.**
  Use it; a hand-edited `.env` or `config.yaml` is how a working setup breaks.
- **Never route `cmd.exe` builtins through the MSYS bash tool.** MSYS rewrites single-letter
  switches, so `cmd //c mklink /J A B` fails with `'ache' is not recognized as an internal or
  external command` — the `/J` is eaten. Invoke `cmd` from Python's `subprocess.run([...])`,
  which passes argv without a shell.
- **The agent writes only to `inbox/`.** Canonical pages fill by promotion. Without this gate
  the failure mode inverts: instead of losing knowledge you accrete plausible-looking model
  prose with no provenance, and lint can only say a page is unsourced, never that it is wrong.
- **Collectors are incremental and bounded, never full-history scans.** A cron run is
  interrupted hard at 3 minutes; a "scan everything" collector dies mid-run and replays badly.
  Select sessions newer than a stored cursor and cap the batch size.
- **A monitor-mode script's idle output must be a stable sentinel, not empty.**
  `--monitor-script` suppresses the agent run only when stdout is byte-identical to the
  previous tick, so a non-empty → empty transition is itself a change and fires one wasted run.
- **Never distil the pipeline's own runs.** Filter cron-originated sessions out of the
  collector (`source != 'cron'` on the `sessions` table). Without it each night distils the
  previous night's distillation run — a self-referential loop whose queue never drains.
  Subagent sessions inherit their parent's source, so real research is still captured.
- **The vault is the record of what has been distilled; the cursor is only an optimisation.**
  A run interrupted between "write proposals" and "advance cursor" re-proposes everything on
  the next tick. Have the collector filter out sessions the vault already cites (`proposed_by:`
  and `sources: [session:<id>]`) so replay is harmless. Idempotency by construction beats
  idempotency by instruction-following.
- **Separate lint STATE from lint FINDINGS.** Pending proposals awaiting review are the normal
  steady state, not a defect. Reporting them in the same channel as broken links means the job
  is never silent while anything is pending, and an operator who sees the same alarm every hour
  stops reading it. Print findings; append pending counts as context.
- **A wikilink resolver must cover every page directory.** Omitting one — `inbox/` and
  `queries/` are the easy ones to forget — makes legitimate cross-references between those
  pages report as broken links.
- **Exclude code spans and fenced blocks before extracting wikilinks.** A page that *documents*
  `[[wikilink]]` syntax contains literal examples, and every one of them self-reports as a
  broken link on every run.
- **Hash content, not bytes.** A `sha256` over raw bytes makes CRLF-vs-LF churn look like
  `raw/` source drift; Obsidian or Notepad on Windows reintroduces CRLF, so a byte-exact hash
  cries wolf on every platform hop. Normalise line endings before hashing.
- **A collector advances nothing; the agent writes the cursor after successfully filing.**
  A failed run then replays at worst one batch instead of losing sessions silently.
- **Deterministic work belongs in `--no-agent` scripts.** Zero tokens, zero model variance,
  silent on a healthy vault. The model is only for synthesis.
- **Prefer `.py` over `.sh` for cron scripts and hook commands.** `.sh` runs via bash, which is
  not a given on Windows; Python is the portable interpreter.
- **Resolve `$HERMES_HOME` — never hardcode `~/.hermes`.** Profiles and Windows installs put it
  elsewhere (`%LOCALAPPDATA%\hermes`), and a stale `HERMES_HOME` silently redirects commands.
- **Keep machine-local state out of the synced content.** The root path is per-machine config;
  the vault is data. Gitignore `.obsidian/`, `_meta/kb-index.json`, `_meta/distill-cursor.json`.
- **Generate every derived view; never hand-maintain a catalogue.** A hand-written index and a
  generated one are two copies of the same data and they drift. Generate `index.md` from the
  pages, give it a "do not edit" banner, and state the override loudly — the bundled `llm-wiki`
  skill assumes the agent maintains `index.md` by hand. Two owners for one file is a defect, so
  the agent must be told which owner wins.
- **Store structured data as structure.** A tag taxonomy written as prose has to be recovered by
  regex, and any schema rewording silently breaks the parser — an empty taxonomy then flags every
  page. Put the taxonomy and `schema_version` in a machine-readable block that the agent also
  reads, so one edit changes both.
- **Never declare a convention you do not check.** `confidence`, `contested` and provenance
  markers that nothing validates teach the agent the schema is decorative. Either wire them into
  lint (as state) or delete them from the schema.
- **Accept the forms an LLM actually writes.** Resolution must be case- and
  separator-insensitive and match path slug, basename, `title` and `aliases`. An agent writes
  `[[Hermes Agent]]`, not `[[entities/hermes-agent]]`, and a strict resolver turns correct links
  into reported defects.
- **Give the repository an in-repo agent contract and wire the jobs to read it.** `AGENTS.md` at
  the vault root is the cross-agent standard (Hermes, Codex and others read it). Add
  `--workdir <vault>` to agent cron jobs so the cwd is the vault and its `AGENTS.md` is injected
  into the job's context automatically — the rules arrive without the agent loading a skill.
- **Keep orientation to one read.** A vault that needs `SCHEMA` + `index` + recent `log` to get
  oriented costs that every session and will not be read. Write `_meta/orient.json` and expose a
  `--orient` flag that prints pages by directory, pending proposals, contested/low-confidence/
  stale counts, open findings and recent log entries in one command.
- **Ship a self-test, and make it assert silence as well as detection.** Ad-hoc shell checks are
  unrepeatable, so the next agent cannot tell whether a change broke detection. Codify both
  directions: every seeded defect is found, and a healthy vault produces no output.
- **One source of truth for the code, with a verifiable deploy.** Scripts that must live under
  `$HERMES_HOME/scripts/` but are maintained in the skill drift silently when copied by hand.
  Provide an install step that prints a hash per file and a `--check` mode that exits non-zero
  on drift.
- **Version the schema.** Without `schema_version` in the machine-readable block there is no way
  to migrate pages, and no way for lint to flag a page written under older rules.
- **Archive, never delete.** A retired page is a previous iteration: keep it so a later one can
  see what was believed and why it changed. Archiving is five coordinated edits, so make it
  mechanical (`kb_archive.py`) rather than a documented ritual, and lint the result — an
  archived page with no successor, a successor that does not exist, a non-reciprocal pair, or a
  live page still linking at a retired one are all defects.
- **One writer per derived artefact.** Frontmatter serialisation, path resolution and index
  rendering each live in exactly one module and are imported elsewhere. A second copy in a
  sibling script is the same drift defect as a hand-maintained index, just smaller.
- **Derive a path from the authoritative record, not from a derived identifier.** A slug is a
  path with the suffix stripped; building a filename from it silently drops the extension and
  writes `concepts/foo` instead of `concepts/foo.md` — with a success exit code. Take the name
  from the recorded `path`.
- **Make any multi-step ritual mechanical.** If a procedure has four or five coordinated steps,
  an agent will eventually skip one, and the lint checks you wrote to catch that are a worse
  fix than not making the mistake. Ship the script.
- **Registering a vault is a separate step from creating it, and a running GUI app will
  clobber a config edit on exit.** For any app whose config is rewritten on quit, the write must
  happen while it is closed, and must be verified by re-reading afterwards.
- **A proposal is not evidence. Verify before promoting, or the gate is theatre.** Check the
  falsifiable claims against their source: `file:line` references, config defaults, version
  numbers and CLI flags are cheap to check and rot fastest. Record the revision a citation was
  verified against, and say in the page that line numbers are stable but names are not.
- **A source that does not contain the claim is a defect.** A page whose findings came from
  running something cites `session:<id>`, not an unrelated article that happens to sit in
  `raw/`. Attributing a claim to a source that cannot support it is the same failure as no
  provenance, and it is invisible to lint - only the ratifier can catch it.
- **Lower confidence rather than inflate it, and amend the rule if the rule is wrong.**
  Uncited figures are `low`. But direct verification by execution is at least as strong as
  corroboration by a second source, so a schema demanding "2+ sources" for `high` understates
  a reproduced finding - fix the schema, not the page.
- **Check whether a new cluster is an island.** Pages that link only to each other pass the
  orphan check while remaining unreachable by walking links from the rest of the vault. Track
  zero-inbound pages as STATE, not as a finding: a self-contained page may legitimately have no
  inbound links, and alarming on it makes a healthy vault noisy.
- **Verify which key authenticates before configuring a remote; never assume the obvious one.**
  Test each candidate: `ssh -T -o IdentitiesOnly=yes -i <key> git@github.com`. A key that is
  *accepted* against a missing repo reports `ERROR: Repository not found.` while a rejected key
  reports `Permission denied (publickey)` - that distinction is how you tell an auth problem
  from a missing repo, and it makes the check conclusive without creating anything.
- **Pin the working key per-repo (`core.sshCommand`) instead of editing the user's global ssh
  config or `~/.ssh/config`.** With several candidate keys, ssh offers them in sequence and a
  success on the fifth still costs four failed attempts, which can trip `MaxAuthTries`.
  `IdentitiesOnly=yes` plus an explicit `-i` removes that class of intermittent failure.
- **An SSH key grants git transport only - it cannot create a repository.** Creation needs API
  auth. Before asking a human for a token, check for a credential the machine already has
  (`git credential fill`, which may hit an OS keychain via Git Credential Manager) and use it
  **in-process**, never on a command line and never printed. Only if there is nothing stored
  should you fall back to asking.
- **Make pushing opt-in via an environment variable.** `hermes cron create --script` takes a
  path and no arguments, so a flag cannot be passed per job. A `KB_COMMIT_PUSH=1`-style env
  check keeps the safe default (commit-only, nothing leaves the host) while letting one machine
  opt in.
- **Decide to push from the branch's ahead-count, never from "did this run commit
  something".** A push placed inside the commit branch strands the commit forever after one
  transient failure: there is no next commit coming, so there is no retry. "The next run will
  retry it" is only true if the push is evaluated on every run, whether or not anything was
  staged — that is the difference between an idempotent push and a claim about one.
- **Guard a "nothing to push to" message with "did this run actually strand a commit".** A
  vault with push enabled but no upstream is a configuration choice, not a finding; reporting
  it on every run makes the job permanently noisy, and a channel that always speaks is a
  channel nobody reads. This is the same cry-wolf defect as a lint that flags healthy state —
  check the new branch of an early-return refactor against the silence rule.
- **Compare content, never raw bytes, in a drift or integrity check.** A byte comparison makes
  every CRLF-vs-LF difference look like a changed file, so a Windows checkout makes the check
  cry wolf on byte-identical code and the operator stops reading it. Normalise line endings
  before comparing or hashing — the same class and the same fix as a byte-exact source hash.
  Report a line-endings-only difference distinctly (`current*`) rather than silently passing it,
  so a real drift is still visible next to it.
- **Run every script against a fixture before shipping it, and say which platform branches you
  actually exercised.** Cross-platform code with one tested branch is untested code elsewhere;
  label the unrun branches as untested rather than implying they were verified. Use the shipped
  `kb_selftest.py` rather than ad-hoc checks — it encodes every lesson above as an assertion.

## Verification

```bash
python <path>/kb_selftest.py                       # must print OK
python <path>/kb_install.py --check                # exit 1 if deployed copies drift
python <path>/kb_root.py --explain                 # path + platform + source
hermes cron list                                   # jobs registered, workdir set
```

The self-test is the primary check and covers every lesson in this skill as an assertion: it
builds a deliberately broken vault and asserts each defect is **detected**, then builds a clean
vault and asserts the run is **silent**. Both directions matter — a check that fires on a healthy
vault gets ignored, which is worse than not checking.

Beyond the self-test, confirm by hand:

- **Silence:** run the indexer against the real vault and expect no output. Pending proposals are
  state, not findings, so a vault with proposals awaiting review still reads clean.
- **Idempotency:** run the collector, write proposals, leave the cursor unadvanced, run again —
  the same sessions must not reappear in the queue.
- **Link forms:** a proposal in `inbox/` linking to another `inbox/` page, and a link written in
  title form, must both resolve.
- **Generated index:** `index.md` must carry the "do not edit" banner and list both canonical
  pages and pending proposals; re-running must not change its bytes.

Collector check: point `HERMES_HOME` at a real home with a `state.db`, run once (queue
printed), advance the cursor, run again (stable idle sentinel, no agent run).

## Supervisor surface: Bases views and the generated dashboard

A corpus with two readers needs two surfaces. The agent reads it through `--orient`, the index
and the lint report; the supervisor reads it through Obsidian, and needs things no terminal
surface shows — what is in flight, what is waiting on a decision, how a reviewed project
scored.

Build that surface **derived, never authored**. Bases views read the same frontmatter the
agent already writes, so there is no second copy of any fact to drift. `DASHBOARD.md` is
rendered by the same job that renders `index.md`.

**Group a Kanban view on a note property, not a file property or a formula.** Bases only
allows moving cards between columns when the group is an editable note property (`groupBy:
{property: note.status}`). Grouping on `file.folder` or a formula makes the board read-only.
That distinction is the whole difference between a report and a control surface: with the
right group, dragging a card rewrites `status` in the note's frontmatter, the auto-commit job
pushes it, and the agent sees it on its next orient. That is the only channel where the human
writes *to* the agent, and it costs nothing extra to enable.

Ship a plain-markdown fallback (`DASHBOARD.md`) alongside the `.base` views. Bases needs a
recent Obsidian and a GUI; the markdown version works in any editor, in the TUI, on the forge,
and on older builds. Same state, no second source.

Verify what you can: `.base` files are YAML, so parse them and assert the view types and
`groupBy` properties. That catches a malformed file but **cannot** confirm Obsidian renders it
— say so rather than implying you checked.

## Review-council integration

When a corpus must serve a multi-agent review panel, the panel's output directory is the
integration point, not its code. A council run writes `outcome.json` (the verdict),
`next-steps.md`, and `round-N/<dimension>.json` per reviewer plus `meta.json`.

**Never recompute a score the panel already computed.** Read its recorded outcome verbatim.
A second implementation of the scoring can disagree with the gate that actually decided the
merge, and then two numbers claim authority over one decision. If the panel recorded no
outcome, report that there is no verdict instead of inventing one.

Two more rules that generalise: emit **project-relative paths** in ingested pages (an absolute
path hardcodes one machine and leaks a local layout into a shared corpus), and mark ingested
pages `generated: true` so a later reader knows they are rewritten rather than authored.

## Linking the vault and the agent (URI schemes, not plugins)

Both applications register a URI scheme, so the vault and the agent address each other with no
plugin, no server and no copied IDs:

| direction | link | notes |
|---|---|---|
| vault -> chat | `hermes://open/<session-id>` | the desktop app's own deep link |
| chat -> vault | `obsidian://open?vault=<name>&file=<vault-relative-path>` | `vault` is the folder name |

`kb_sessions.py` writes the first into every session note; `kb_open.py` fires the second.

**Do not build this as a desktop plugin button.** The Hermes desktop bridge admits web schemes
only (`SUPPORTED_WEB = ['http:', 'https:', 'mailto:']` in
`apps/desktop/electron/external-open.ts`), so `ctx.os.openExternal('obsidian://...')` is
rejected — a plugin cannot launch Obsidian. Handing the URI to the OS is the route that works,
which is why `kb_open.py` shells out instead of using an API.

**Verify a deep link by its effect, not its syntax.** Firing `hermes://open/<id>` and reading
`$HERMES_HOME/logs/desktop.log` is the cheap proof: the app logs `[deeplink] delivered
open/<id>` plus `[second-instance] relaunch (deepLink=yes)`. For Obsidian, `kb_open.py` plus a
CDP read of `app.workspace.getActiveFile()` shows which note actually opened — and note that
Obsidian can hold **several vault windows at once**, so check the window whose
`app.vault.getName()` matches or you will read the wrong vault and conclude the link failed when
it worked.

**Link both ways from inside the vault too.** A page names its session in
`sources: [session:<id>]`; `kb_sessions.py` inverts that to list the pages a session produced.
Without the inversion a session note is a dead end — you can read what the agent did but not
what came of it.

## Support files

- `scripts/kb_root.py` — the cross-platform root resolver.
- `scripts/kb_open.py` — open the vault, a note, or a session note in Obsidian.
- `scripts/kb_reindex.py` — the single generator for all derived views (`index.md`,
  `_meta/*.json`) and the lint report.
- `scripts/kb_council.py` — ingests review-council runs into `work/` pages for the board. — deterministic graph/sha256 indexer + lint, silent when clean.
  Regenerates `index.md` and `_meta/orient.json` from the pages; `--orient` prints a one-read
  orientation and writes nothing.
- `scripts/kb_selftest.py` — builds a broken vault and a clean vault in temp dirs and asserts
  detection, silence, tolerant link forms, generation and idempotency. Run it after every edit.
- `scripts/kb_install.py` — deploys the scripts to `$HERMES_HOME/scripts/` and prints a hash per
  file; `--check` exits non-zero when the deployed copies drift from the skill.
- `scripts/kb_collect.py` — cursor-based session digest for the distill job; filters out
  sessions the vault already covers, so replay is idempotent.
- `scripts/kb_commit.py` — `--no-agent` git commit of vault changes, silent when nothing
  changed; deliberately never pushes.
- `scripts/kb_stamp_raw.py` — stamps a `raw/` source with correct provenance frontmatter
  (LF-normalised `sha256`), so hand-computed hashes cannot poison the drift check.
- `scripts/kb_promote.py` — promotes an inbox proposal to canonical in one verified step
  (move, `status: approved`, log) with guard rails: refuses a page that is not in `inbox/`,
  is not `proposed`, would collide, or would land as an orphan. Promotion is the other
  multi-step ritual, and the more dangerous one — a missing *promote* log line is invisible,
  because the `proposals_missing_log_entry` check only inspects pages still in `inbox/`.
- `scripts/kb_archive.py` — retires a superseded page in one verified step: moves it to
  `_archive/`, stamps `status`/`archived`/`superseded_by`, adds `supersedes` to the successor,
  repoints inbound links, and logs it. Refuses on unmet preconditions.
- `references/cron-pipeline-primitives.md` — the Hermes primitives the pipeline rests on
  (cron flags and limits, session-store schema, env routing, hook events).
- `references/cross-platform-paths.md` — resolver precedence, per-OS defaults, junction/
  symlink recipes, MSYS pitfalls.

## Ingesting sources

When the pipeline ingests a URL, store the raw copy under `raw/<kind>/` and stamp it with
`scripts/kb_stamp_raw.py --source-url <url>` — it writes `source_url`, `ingested` and a
correct LF-normalised `sha256`. Do not hand-compute the hash. If a fetch is blocked,
prefixing the URL with `https://r.jina.ai/` returns the page as markdown.
