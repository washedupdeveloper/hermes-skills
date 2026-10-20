---
name: agent-harness-design
description: "Use when changing harness seams, tools, or registries."
version: 2.2.0
author: user, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
category: software-development
metadata:
  hermes:
    tags: [harness, plugins, seams, registries, audit, composition]
    related_skills: [deterministic-quality-gates, writing-for-agents, hermes-agent, defensive-patterns, postmortem]
---

# agent-harness-design

What this setup adopted from DeepSeek Harness (`dsh`, an all-plugin Cordis harness), **where
each rule is actually implemented**, and which rules have no Hermes seam at all. The
bug-class rules it states for review live in `defensive-patterns`; the incident discipline
lives in `postmortem`.

Read this when changing a harness seam — a tool, a registry, a plugin, a skill source. It is
an index of running capability first, and judgement rules second. A rule that exists only as
prose is labelled as such.

Provenance and the rejected alternatives: `docs/adr/0004-adopt-dsh-harness-rules.md`.

## Implemented — the capability exists, and this is where

| dsh rule | Where it lives here | How to see it |
|---|---|---|
| **Model-visible means logged** | `plugins/harness-audit` — `pre_tool_call` / `post_tool_call` hooks write one JSONL line per call to `$HERMES_HOME/logs/tool-audit/<date>.jsonl` | `harness_audit(action="status")`, then `action="recent"` |
| **Discovery reports complete or incomplete, never absence** | same plugin, `action="catalog"` — every discovered skill plus any root or frontmatter that could not be read | `harness_audit(action="catalog")` |
| **Wire each invariant into a gate, with a negative control** | `nix/tests.nix` — one predicate per rule, each driven with a deliberately invalid input through the same code the gate calls | `nix flake check` |
| **A registration is an effect; teardown unwinds it** | Hermes plugin lifecycle — contributions from `register(ctx)` go away when the plugin unloads | `hermes plugins disable <name>` |
| **Composition is layered; every row patchable by id** | Hermes profiles + `config.yaml`, changed with `hermes config set` (never by hand) | `hermes config get <key> --json` |
| **A model request is a logged fact** | same plugin, `pre_api_request` — one JSONL line per call: provider, model, message and tool counts, input-token size, and a digest of the system prompt. No prompt text, no message bodies | `harness_audit(action="requests")` |

## Not implemented, because Hermes has no seam for it

- **Two independent invocation switches** (dsh: `disable-model-invocation`,
  `user-invocable`). Hermes has no model-vs-human switch. It gates skills at offer time on
  relevance (`requires_toolsets`, `fallback_for_toolsets`, `requires_tools`,
  `fallback_for_tools`, `environments`, `session_platforms`,
  `required_environment_variables`), on host compatibility (`platforms`), and by config
  (`skills.disabled`, `skills.platform_disabled`). Those decide whether a skill is *offered*,
  not *who may invoke* it.
- **Per-row config patches applied as ordered layers, with a composed-tree dump.** Hermes has
  one `config.yaml` plus profiles; `hermes config set` is the patch, and there is no dump to
  diff. Adopting the layering would mean changing the config loader.
- **Branded ids at every boundary**, and **per-file 100% coverage**: costs that buy dsh's
  all-plugin discipline across 342 packages in 58 groups, and buy nothing in a skill tree.

## Rules that stay as judgement

Each states the defect it prevents and the check that can fail.

- **A seam has three roles, never one.** A swappable capability is a service definition, a
  provider, and a consumer. One role alone is not a seam; adding a capability means designing
  all three. Check: delete the shipped provider, mount another, the consumer works unchanged.
- **New behavior goes on a documented extension point.** Keep one table of goal → mechanism.
  Changing the loop is the exception that updates the map.
- **Registries layer per scope; rank decides inside a layer.** The nearest layer wins a
  duplicate name outright, and a rank breaks ties only inside one layer, so a shadowing is
  explainable rather than mysterious. Hermes's skill resolution is the working example:
  project > custom > user > bundled.
- **Defaulting is explicit at the boundary** — a named `resolve(request): Spec` in the owning
  implementation, never a hidden `?? default` inside the operation that consumes it.
- **Tunables are config, not constants.** Deployment-varying choices are validated config
  fields; a `DEFAULT_*` constant or a test hook is not configurability. Protocol constants,
  external specs and security invariants stay fixed.
- **Misconfiguration fails loud** — at load when the check is self-contained, otherwise at the
  earliest resolvable point. Never silently skip a missing referent: a plugin that appears
  mounted and contributes nothing is worse than one that refuses.
- **A catalog carries identity; a body loads on demand.** The model-visible index is name and
  description; bodies are read at load time and never cached, so a body-only edit takes effect
  without rewriting history. Hermes already does this (`skills_list` + `skill_view`); the rule
  is recorded so it is not broken by accident.
- **One home per fact**; **a decision is a record with a lifecycle** (proposed → implemented →
  archived, frozen once archived). The tier table is in `writing-for-agents`.

## Where a policy goes in the tool pipeline

dsh runs one ordered pipeline per call, and each stage has exactly one job. Hermes has the
same shape with fewer stages; what survives the port is the rule that a concern belongs to
one stage.

| stage | dsh | Hermes seam | may |
|---|---|---|---|
| pre-execute | `tools/pre-execute` waterfall | `pre_tool_call` hooks | allow, deny, ask, rewrite args |
| guards | monotonic guards, un-reorderable | no seam | deny or abstain |
| around | `tools/execute` waterfall | `hermes_cli.middleware` | timeout, retry, metrics |
| body | the tool's `execute()` | the tool | its own work only |
| post | `tools/post-execute` waterfall | `post_tool_call`; `transform_tool_result` | observe; replace the result string |
| result | `tools/result` observer | `post_tool_call` after the transform | read the frozen outcome |

- **A policy that must not be reordered is a guard, not a hook.** Hermes hooks run in
  registration order and any of them may deny, so a "must run last" check has no guarantee.
  If order matters, the tool body owns the check — and then it is not a guard, it is the
  tool's own precondition.
- **Around-dispatch concerns wrap; they do not branch.** A timeout, a retry, a metric goes
  in a wrapper around the call. The same concern written as a branch inside the tool body is
  a second copy that the wrapper cannot see.
- **The result is rewritten once.** `transform_tool_result` is first-string-wins and runs
  after `post_tool_call`, before the result enters context. Two plugins that both rewrite it
  do not compose: the second is silently dropped.
- **A tool body holds no policy that belongs to a seam.** If the check would apply to a
  family of tools, it is a hook; if it applies to one tool only, it is that tool's own.

Hermes already bounds tool output per tool — a `read_file` continuation offset, a saved
file for a truncated command, head+tail for code execution. That is why dsh's **spill** (a
global bounded-output rewrite) is not ported: a blanket transform would break each tool's
own continuation contract to solve a problem those contracts already solve.

## The model-facing surface

What the model sees of a capability — the name, the description, the parameter schema, the
prompt section framing it — is read by a consumer that pays for every token on every turn.
The writing rules live in the `writing-for-agents` tool-surface reference. Two of them
matter most when adding a capability: put each parameter's rules on that parameter, and say
each fact once.

Measure, do not estimate: `harness_audit(action="requests")` reports input tokens and
system-prompt bytes per request, so a change to the offered surface has evidence beside it.

## Exercising a hook against a real run

A hook that imports cleanly proves nothing. Run it under the real binary in a throwaway
home, so it fires through the same path a session takes and the real `$HERMES_HOME` is
never the test's to edit:

```sh
S=~/.hermes/cache/scratch/plugin-probe
mkdir -p "$S/plugins"
cp -r plugins/<name> "$S/plugins/<name>"
cat > "$S/config.yaml" <<'YAML'
model: { default: "scratch-model", provider: "custom:scratch" }
custom_providers:
  - { name: scratch, base_url: "http://127.0.0.1:9/v1", api_key: "scratch", model: scratch-model }
plugins: { enabled: [<name>] }
YAML
HERMES_HOME="$S" timeout 180 hermes -z "say hi"
```

- **Point the provider at a dead address on purpose.** `pre_api_request` fires before the
  call, so a hook on it is verified with no key and no reachable model: the records appear
  while the request fails. Waiting for a 200 measures the provider, not the hook.
- **Bound the run.** An agent retrying against a dead port keeps going; `timeout` turns a
  hang into an exit code instead of a session that never returns.
- **Read the artifact, and assert the absence too.** Count the records, check a field
  against a value you know is real (a tool count, a token count), then grep the log for a
  sentence you know was in the prompt. A redactor nobody tested is a redactor that does
  not work.
- **Then run the repo's gate, with new files staged.** `git add` any new support file
  first: the Nix sandbox copies only git-visible paths, so an untracked reference file
  fails there while passing on disk (`writing-for-agents` owns that rule).

## When a rule cannot be implemented

Say so, and say what it would cost. The failure mode to avoid is a document that reads like
capability: a mapping table asserting a mechanism Hermes does not have, or a skill whose only
effect is on the reader's mood. Both are worse than an empty section, because the next session
builds on them.

## Verification

- [ ] Every "implemented" row names a file or a command that proves it
- [ ] Every rule with no Hermes seam is listed under "not implemented", with the reason
- [ ] A new invariant is in `nix flake check` with a negative control beside it
- [ ] A new hook was exercised under the real binary in a throwaway `HERMES_HOME`, not
      only imported
- [ ] No row claims a config key or frontmatter field without a `grep` behind it
