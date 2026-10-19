# Plugins

Skills this repo ships are **mounted** (`skills.external_dirs`) — Hermes reads them in
place, and `git pull` is the update. Plugins have no such mount: Hermes discovers them
under `<profile home>/plugins/`, so a plugin has to be placed there. It is the one part of
this repo that is installed rather than referenced, and the reason is stated once, here.

## harness-audit

Three DeepSeek-Harness invariants, implemented against Hermes mechanics that exist today:

| Invariant | What it does here |
|---|---|
| **Model-visible means logged** | `pre_tool_call` / `post_tool_call` hooks append one JSONL line per call to `$HERMES_HOME/logs/tool-audit/<date>.jsonl`: tool, task, redacted arguments, duration, result size and a sha256 prefix. The result *text* is never stored, and anything credential-shaped is dropped before it is written. |
| **Discovery reports complete or incomplete, never absence** | `harness_audit(action="catalog")` returns every discovered skill plus any directory or frontmatter that could not be read, so a shorter list is never mistaken for "not installed". |
| **A model request is a logged fact** | `pre_api_request` appends one JSONL line per call to `$HERMES_HOME/logs/model-requests/<date>.jsonl`: provider, model, api mode, message and tool counts, input-token size, request chars, and a sha256 prefix of the system prompt. No prompt text and no message bodies — a log that quotes the prompt is a second copy of it. `harness_audit(action="requests")` returns the window plus prompt growth. |

A fourth invariant — dsh's two invocation switches, model-invocable vs user-invocable —
is **not** implemented, because Hermes has no seam for it. Hermes gates skills at offer
time on relevance (`requires_toolsets`, `environments`, `platforms`, `skills.disabled`),
which is a different axis. A naming convention pretending otherwise would be advice, not
a capability.

### Install

Three routes, in order of how much of the machine they change.

**1. Nix overlay — nothing is copied, and Hermes is not patched.** The plugin ships a
`pyproject.toml` with the `hermes_agent.plugins` entry point, so it can be added through
Hermes' own documented seam, `pkgs.hermes-agent.override { extraPythonPackages = …; }`:

```nix
# in the flake that builds your Hermes
inputs.hermes-skills.url = "github:washedupdeveloper/hermes-skills";
nixpkgs.overlays = [ hermes-skills.overlays.default ];   # or .wrapper, see below
```

`overlays.default` rebuilds the Hermes derivation with the plugin in its wrapper's
`PYTHONPATH`. `overlays.wrapper` wraps the **existing** binary instead — same effect, no
Hermes rebuild — and is the shape to reach for when the rebuild is not worth waiting for.
Both are verified: `default` routes the plugin through `extraPythonPackages`, and the
wrapper's `hermes plugins list` reports the plugin with source `entrypoint` against the
real installed binary.

**2. `hermes plugins install` / a manual copy**, if the machine is not Nix-managed:

```bash
cp -r plugins/harness-audit "$HERMES_HOME/plugins/"       # or: hermes plugins install <path>
hermes config set plugins.enabled '["harness-audit"]'      # `hermes plugins enable` needs uv.lock
```

**3. `nix build .#harness-audit`** produces the distribution on its own, for pointing any
Hermes build at it by hand.

Then restart Hermes: plugin discovery happens once, at gateway startup, so the tool and
the hooks appear in the next session — not in the one that installed them.

`hermes plugins enable <name>` is the documented path and does not work on a Nix-managed
install (it aborts looking for `uv.lock` in the store). The `config set` above is the same
effect: `hermes plugins list` then reports `enabled`.

### Check it is working

```bash
hermes plugins list | grep harness-audit          # enabled; source `entrypoint` under Nix
ls "$HERMES_HOME/logs/tool-audit/"                # a JSONL file, one line per tool call
```

Inside a session, `harness_audit(action="status")` reports both log paths and today's
counts; `action="recent"` reads the last tool calls back; `action="requests"` reports model
requests with their input-token sizes and prompt growth; `action="catalog"` reports the
skill catalog with its completeness.

### What it deliberately does not do

- No network, no credentials, no configuration writes.
- No `override=True` on any built-in tool: nothing is intercepted or replaced.
- No argument values in the log — only key names, plus a digest of each result. An audit
  log that quotes the thing it is auditing becomes the leak it exists to prevent.
