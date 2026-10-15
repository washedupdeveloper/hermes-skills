# Hermes primitives a knowledge pipeline rests on

Verified against `hermes --version` 0.21.5 (`hermes cron --help`, `hermes hooks --help`,
`hermes mcp catalog`, `sqlite_master` dump of `state.db`). Re-check with `--help` before
relying on a flag; these move between releases.

## Cron

`hermes cron create <schedule> [prompt]` — schedule is `30m`, `every 2h`, 5-field cron, or
an ISO timestamp.

| Flag | Behaviour that shapes the design |
|---|---|
| `--script PATH` | Resolved under `$HERMES_HOME/scripts/`. `.sh`/`.bash` run via bash, everything else via Python → use `.py` for Windows portability. Default mode injects stdout into the agent's prompt. |
| `--no-agent` | The script *is* the job; stdout is delivered verbatim. Empty stdout is silent. Zero tokens. |
| `--monitor-script PATH` | Runs before the agent each tick; **byte-identical stdout suppresses the agent run entirely**, changed output injects a diff into the prompt. Output must be stable — no timestamps. Mutually exclusive with `--monitor-url`; incompatible with `--no-agent`. |
| `--monitor-url URL` | Same hash-suppression semantics over a bounded GET. |
| `--skill NAME` | Attach skills; repeatable. |
| `--deliver` | `origin`, `local`, a platform, `platform:chat_id`, or `bot-chat[:profile]`. |
| `--failure-deliver` | Override for failure notices only; `local` suppresses them. |
| `--workdir DIR` | cwd for terminal/file tools + injects that dir's `AGENTS.md`/`CLAUDE.md`. |
| `--model` / `--provider` | Pin the job's inference. |

Limits and invariants:

- **3-minute hard interrupt per run.** Bound every collector; never scan full history.
- `.tick.lock` prevents duplicate ticks across processes.
- Cron sessions pass `skip_memory=True` — a maintenance job cannot pollute memory.
- Deliveries are framed with a header/footer rather than mirrored into the target session,
  which keeps role alternation intact.
- Related verbs: `hermes cron runs|history`, `incidents`, `notepad` (durable per-job KV),
  `doctor`, `tick`.

## Session store

`$HERMES_HOME/state.db` — SQLite with FTS5. The tables a pipeline needs:

- `sessions(id, title, display_name, cwd, started_at, ended_at, last_activity_at,
  message_count, tool_call_count, tool_names, hidden, archived, profile_name, git_branch,
  git_repo_root, estimated_cost_usd, …)`
- `messages(id, session_id, role, content, tool_call_id, tool_calls, tool_name, timestamp,
  token_count, reasoning, …)`, plus the FTS5 view `messages_fts_src` over
  `(content, tool_name, tool_calls)` where tool content is truncated to 8192 chars.

Open read-only when a script only reads: `sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)`.
Use `COALESCE(ended_at, last_activity_at)` as the watermark — live sessions have no `ended_at`.

## Config vs env

- `hermes config set <key> <val>` — a bare `UPPER_SNAKE` key is an *env* setting and is routed
  to the profile's `.env` (`hermes_cli/config_env_routing.is_env_setting_key`); dotted keys go
  to `config.yaml`. Same-named stale `config.yaml` copies are dropped on write.
- Top-level scalars in `config.yaml` are bridged into `os.environ`, so a skill can read a
  config-style key either way.
- Deprecated: `MESSAGING_CWD` / `TERMINAL_CWD` in `.env` — canonical home is `terminal.cwd`.
- Never hand-edit `config.yaml`; a stray indent corrupts a live gateway.

## Hooks

Valid events: `pre_tool_call`, `post_tool_call`, `pre_llm_call`, `post_llm_call`,
`pre_api_request`, `post_api_request`, `on_session_start`, `on_session_end`,
`on_session_finalize`, `on_session_reset`, `subagent_stop`.

Shell hooks (`hooks:` block in `config.yaml`) are executed **`shell=False` + `shlex.split`**
with a JSON payload on stdin — so a `.sh` hook is not portable to Windows; write the hook as
`command: "python <abs>/kb-guard-raw.py"`. A `pre_tool_call` hook can block or fail closed.

Non-interactive runs (gateway, cron) need first-use consent satisfied: `hooks_auto_accept: true`,
`HERMES_ACCEPT_HOOKS=1`, or `--accept-hooks`. Inspect with `hermes hooks list` (shows matcher,
timeout, consent state) and `hermes hooks doctor` (exec bit, allowlist, mtime drift, JSON
validity, synthetic-run timing). Gateway hooks (`HOOK.yaml` + `handler.py` in `$HERMES_HOME/hooks/`)
load only in the gateway — never in CLI/TUI/Desktop/cron.

## MCP

`hermes mcp catalog` is the one-click install list; it contains **no Obsidian server**
(closest: `craft`, `notion`). Exposing a vault to every surface therefore means writing a
stdio server and `hermes mcp add <name> --command python --args <abs path>`.

## Skill frontmatter that gates a job

`required_environment_variables:` in a skill's frontmatter is checked by cron preflight
(`cron/scheduler_preflight.py`) — a missing var surfaces as a preflight failure rather than a
silent half-run. Use it when a job depends on a path or key being set.

## The SCHEMA.md machine block

The vault's tag taxonomy and schema version live in a fenced yaml block in `SCHEMA.md`, not in
prose. Contract:

```yaml
# kb-schema — machine-readable
schema_version: 1
tags:
  tag-name:
  other-tag:
```

The parser takes the **first fenced yaml block that contains both** a `schema_version` and a
`tags:` mapping with indented children. Everything else in the file is prose and is ignored —
that is the point. Rules that keep it working:

- `tags:` must be a mapping with one tag per indented line. An inline list (`tags: [a, b]`) is
  not read as the taxonomy and the block gets skipped, which silently yields an empty taxonomy
  and flags every page as out-of-taxonomy. This is the failure mode to watch for.
- Adding a tag is a one-line edit here. Adding it in prose does nothing.
- `schema_version` lets lint flag pages written under older rules.
- The prose elsewhere may legitimately contain other yaml fences (frontmatter examples). They
  are skipped because they lack the `tags:` mapping, so ordering does not matter.
