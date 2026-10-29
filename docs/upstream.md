# Upstream skills

Eighteen skills here were adapted from three external sources. This file records where each came
from — and the question that matters operationally: **whether they update themselves.**

They do not. Each is a **one-way copy at a recorded revision**, rewritten for Hermes, and the rewritten
file is ours. The upstream owns the *idea*; this repo owns the *file*. That is the safer default too:
an auto-updating skill is unreviewed code running with the agent's permissions.

| Source | Delivery | Syncs? |
|---|---|---|
| [mattpocock/skills](https://github.com/mattpocock/skills) via `npx skills add` | Editable files copied into your project | **No.** Upstream: "Nothing updates behind your back." |
| the same repo as a Claude Code plugin | Managed, read-only bundle | Yes, but Claude Code only — it does not apply to Hermes. |
| [agentskills.codes](https://agentskills.codes) | A one-time `.zip` per skill | **No.** No update mechanism exists. |

So: snapshots from both sources, re-adapted by hand. An upstream change must be re-adapted rather than
merged.

## mattpocock/skills — 9 skills

Upstream: **v1.3.1** (2026-10-04, commit `6fd947921b935b7e1e69293a200400f0fdd5c15f`).

| Skill | Upstream path | What was worth taking |
|---|---|---|
| `handoff` | `productivity/handoff` | A resume point for a fresh session. |
| `domain-modeling` | `engineering/domain-modeling` | Glossary + ADR discipline; the three-test rule for when an ADR is warranted is the load-bearing part. |
| `to-spec` | `engineering/to-spec` | Conversation → spec, with test seams. |
| `to-tickets` | `engineering/to-tickets` | Tracer-bullet slices, blocking edges, expand–contract for wide refactors. |
| `wayfinder` | `engineering/wayfinder` | Work too big for one session as a map of decision tickets. |
| `retro` | `engineering/retro` | Reviewing the agent's environment rather than the code. |
| `wizard` | `engineering/wizard` | A generated script for steps only a human can perform. |
| `writing-for-agents` | `productivity/writing-for-agents` | Context pointers, and the two loads. |
| `wait-what` | `productivity/wait-what` | Re-pitch in Simplified Technical English. |

All nine were rewritten: descriptions cut to the 57-character index window, Claude-Code frontmatter
(`disable-model-invocation`, `argument-hint`) dropped, the `/setup-matt-pocock-skills` and issue-tracker
dependencies replaced by local files, and shell prose replaced with Hermes tool names.

### Not taken

| Rejected | Because |
|---|---|
| `grill-me`, `grilling` | `grill-me` is already here, from this source. |
| `grill-with-docs` | A two-line router; composing two existing skills adds a hop and no content. |
| `tdd` / `code-review` / `diagnosing-bugs` / `prototype` / `research` | Covered by `test-driven-development`, `requesting-code-review`, `systematic-debugging`, `spike`, `grounded-citations`. |
| `pr` | The bundled `github` skill covers PR bodies. |
| `improve-codebase-architecture`, `codebase-design` | `simplify-code` plus the council's architecture rubric. |
| `implement`, `implement-spec` | Hermes delegates natively; the council drives an implement-and-re-review loop. |
| `setup-matt-pocock-skills`, `ask-matt`, `git-guardrails-claude-code`, `claude-handoff`, `migrate-to-shoehorn`, `setup-ts-deep-modules`, `scaffold-exercises`, `setup-pre-commit` | Tied to Claude Code or TypeScript. |
| `in-progress/*`, `writing-*` | Book-writing, unreleased. |

**Nothing from agentskills.codes.** It is a scraped aggregator of ~6,300 skills, most at 0–1 installs,
and two things disqualify it: its provenance is third-hand (`effective-go` is itself a copy from
`openshift/hypershift`), and its content is often a pointer — "follow the official guide at <URL>" —
rather than a skill. The framework guides it does carry duplicate documentation the frameworks
maintain, which a snapshot would fossilise.

## JuliusBrussee/caveman — 8 skills

A token-compression pack. Upstream lists `hermes` among its targets, but delivery is a compiled plugin
with session hooks and named subagent presets — none of which exist here. What is portable is the
prompt content, not the plumbing.

Upstream: commit `d262ab3882952a59312ff3537cd86d894523c5ab` (2026-10-13).

| Skill | Upstream path | What was worth taking |
|---|---|---|
| `caveman` | `skills/caveman` | The terse voice: no filler, every technical fact kept. |
| `ultracave` | `skills/ultracave` | Maximum compression of the same voice. |
| `caveman-review` | `skills/caveman-review` | One line per finding — location, problem, fix. This is the reviewer payload shape. |
| `cavecrew` | `skills/cavecrew` | Output contracts for delegated children, so a summary costs a fraction of prose. |
| `caveman-explore` | `skills/caveman-explore` | `path:line` replies, keeping reads out of the caller's context. |
| `caveman-compress` | `skills/caveman-compress` | Shrinking a file that is re-read every turn. **Rewritten as prompt-only**: upstream ships 1,834 lines of Python wired to an Anthropic provider; this version compresses in place with the agent's own model. |
| `surgical-patch` | `skills/surgical-patch` | Fix at the narrowest layer, no drive-by cleanup. |
| `verify-and-stop` | `skills/verify-and-stop` | Smallest sufficient proof set; stop at acceptance. |

Rewritten, not copied: Claude-Code frontmatter dropped; the hook-driven `Caveman mode: <mode>` relay
removed (no hook host, so there is no mode to track); the named subagent presets replaced by
`delegate_task` with a literal output contract in the child's goal, because a child cannot see a
skill; `Read`/`Glob`/`Grep` replaced by `read_file`/`search_files`.

### Not taken

| Rejected | Because |
|---|---|
| `caveman-evidence-review`, `-setup`, `-discover`, `-manage`, `-optimize`, `-stats`, `-learn`, `-help` | Bound to the Caveman Cloud CLI and its MCP tools. Nothing here calls it. |
| `megacave` | Classical Chinese register; not a token win for English bots. |
| `lean-build` | Feature building. The council reviews and fixes; it does not build product slices. |
| `investigate-first` | `systematic-debugging` owns establishing a mechanism before editing. |
| `safe-refactor` | `simplify-code` is the cleanup path; nothing here restructures for its own sake. |
| `migration` | No skill here performs schema, data or protocol migrations. |

## addyosmani/agent-skills — 1 skill

Upstream is a builder-oriented teaching document (~17.6 KB); what is portable is the checklist, the red
flags and the falsifiable check.

| Skill | Upstream path | What was worth taking |
|---|---|---|
| `web-app-security` | `security-and-hardening` (MIT) | Web security had no owner here: the council's `reviewer-security` rubric is Nix-scoped, with no XSS, CORS, sessions, SSRF, PII or LLM surface. |

No revision is pinned: the file was condensed by hand rather than copied, and the parts that matter
(OWASP categories, the SSRF and destructive-path rules) are stable upstream. Re-read it before
extending. It is loaded on demand — the council names it in the reviewer's skill list, so a Nix-only
review never pays for it.

### Not taken

| Rejected | Already owned by |
|---|---|
| `code-review-and-quality` | the council — its five axes are the council's five dimensions |
| `code-simplification` | `simplify-code` (both carry Chesterton's Fence) |
| `context-engineering` | `writing-for-agents` |
| `documentation-and-adrs` | `domain-modeling`, which owns the three-test ADR rule |
| `planning-and-task-breakdown` | `to-tickets` |
| `spec-driven-development` | `to-spec` |
| `using-agent-skills` | router class; the conventions forbid router skills |

## Updating

1. Read the upstream diff: `git -C <clone> diff v1.3.1..<new-tag> -- skills/`
2. Re-adapt the changed parts by hand. **Do not overwrite** — the local files carry Hermes-specific
   tool names, no tracker dependency, and local-file defaults that a straight copy loses.
3. Update the pinned revision here and in the skill's `metadata.hermes.source`.