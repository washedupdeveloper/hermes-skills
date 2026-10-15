# Upstream skills and their sync behaviour

Eighteen skills in this library were adapted from three external sources. This file
records where each came from, and — the question that matters operationally —
**whether they update themselves**.

Nine are from `mattpocock/skills` (`handoff`, `domain-modeling`, `to-spec`,
`to-tickets`, `wayfinder`, `retro`, `wizard`, `writing-for-agents`, `wait-what`),
eight from `JuliusBrussee/caveman` (`caveman`, `ultracave`, `caveman-review`,
`cavecrew`, `caveman-explore`, `caveman-compress`, `surgical-patch`,
`verify-and-stop`), and one from `addyosmani/agent-skills` (`web-app-security`). All
eighteen live in this repo because they were **rewritten for Hermes** and the
rewritten version is ours. This file is their
provenance record: it is what makes them re-pullable rather than orphaned. Treat the
upstream as the owner of the *idea* and this repo as the owner of the *file* — pull a
newer upstream deliberately (see **Updating**), never by overwriting.

## Answer: they are local snapshots. Nothing updates automatically.

Every one of them is a **one-way copy** taken at a recorded revision. Once installed,
a skill is an ordinary file on this machine that no upstream can reach into. Updates
happen only when someone deliberately pulls them.

That is by design, and it is also the safer default: an auto-updating skill is
unreviewed code running with the agent's permissions.

### The sources, and how each actually delivers

| Source | Delivery | Syncs? |
|---|---|---|
| [mattpocock/skills](https://github.com/mattpocock/skills) via `npx skills add` | Copies **editable files into your project** | **No.** The README states it plainly: "Nothing updates behind your back; pull my latest changes when you want them with `npx skills update`." |
| mattpocock/skills as a [CC] plugin | Managed, read-only bundle | Yes — but that path is Claude Code only and does not apply to Hermes. |
| [agentskills.codes](https://agentskills.codes) | A one-time `.zip` download per skill | **No.** No update mechanism exists. |

So for Hermes: **snapshots, both sources.** The `npx skills update` command is not
part of this library and was not used — the skills below were adapted by hand, which
means an upstream update must be re-adapted rather than merged.

## Upstream: mattpocock/skills

Upstream: **mattpocock/skills @ v1.3.1** (tag `v1.3.1`, 2026-10-04;
commit `6fd947921b935b7e1e69293a200400f0fdd5c15f`).

| Skill | Upstream path | Why it was worth taking |
|---|---|---|
| `handoff` | `productivity/handoff` | Nothing else covered writing a resume point for a fresh session. |
| `domain-modeling` | `engineering/domain-modeling` | Glossary + ADR discipline. The three-test rule for when an ADR is warranted is the load-bearing part. |
| `to-spec` | `engineering/to-spec` | Conversation → spec, with the "test seams" concept. |
| `to-tickets` | `engineering/to-tickets` | Tracer-bullet vertical slices, blocking edges, and expand–contract for wide refactors. |
| `wayfinder` | `engineering/wayfinder` | Planning work too big for one session as a map of decision tickets. |
| `retro` | `engineering/retro` | Reviewing the *agent's environment* rather than the code. |
| `wizard` | `engineering/wizard` | Generating a script for steps only a human can perform. |
| `writing-for-agents` | `productivity/writing-for-agents` | The craft of context pointers and the two loads. |
| `wait-what` | `productivity/wait-what` | Re-pitch in Simplified Technical English. |

Every one was rewritten, not copied: descriptions cut to ≤60 chars, [CC]-specific
frontmatter (`disable-model-invocation`, `argument-hint`) dropped, the
`/setup-matt-pocock-skills` and issue-tracker dependencies removed in favour of local
files by default, and shell prose replaced with Hermes tool names.

## What was deliberately not taken

**Redundant with skills already present:**

| Rejected | Because |
|---|---|
| `grill-me`, `grilling` | `grill-me` is already here (itself derived from this source). |
| `grill-with-docs` | A two-line router — "call `grilling` and `domain-modeling`". The authoring conventions forbid router/index skills; composing two existing skills adds an indirection hop and no content. |
| `tdd` | `test-driven-development` covers it. |
| `code-review` | `requesting-code-review` covers it. |
| `diagnosing-bugs`, `diagnose` | `systematic-debugging` covers it. |
| `prototype` | `spike` covers it. |
| `research` | `grounded-citations` covers it. |
| `pr` | The bundled `github` skill covers PR bodies. |
| `improve-codebase-architecture`, `codebase-design` | `simplify-code` plus the council's architecture rubric cover it. |
| `implement`, `implement-spec` | Hermes delegates natively; the council already drives an implement-and-re-review loop. |
| `frontend-design` (agentskills.codes) | `claude-design` and `popular-web-designs` already cover avoiding the generic AI look. |

**Out of scope — tied to another ecosystem:**

`setup-matt-pocock-skills` (writes his config format), `ask-matt` (a router),
`git-guardrails-claude-code`, `claude-handoff`, `migrate-to-shoehorn`,
`setup-ts-deep-modules`, `scaffold-exercises`, `setup-pre-commit` (all [CC]/TypeScript
specific), and the `in-progress/` and `writing-*` entries (book-writing, unreleased).

**From agentskills.codes — nothing.**

It is a scraped aggregator of ~6,343 skills, the large majority at 0–1 installs. Two
concrete reasons to decline it as a source:

1. **Third-hand provenance.** Its `effective-go` is a copy of a file from
   `openshift/hypershift/.claude/skills/`. Installing from the aggregator means
   trusting its copy over the original — and losing the ability to check the original.
2. **Thin content.** That same skill largely says "follow the official guide at
   <URL>" — a pointer dressed as a skill, which the writing conventions above
   explicitly treat as a pointer that should be sharpened rather than shipped.

The genuinely useful entries there (framework guides for Next.js, Drizzle, React)
duplicate documentation the framework itself maintains, and would go stale in a
snapshot.

## Upstream: JuliusBrussee/caveman

A token-compression pack. Five of its skills were taken as local snapshots and
rewritten for Hermes. Upstream lists `hermes` among its targets (`skills/registry.json`,
`native_pack.targets`), but its delivery is a compiled plugin pack with session hooks
and named subagent presets — none of which exist here. What is portable is the prompt
content, not the plumbing.

Upstream: **JuliusBrussee/caveman @ commit
`d262ab3882952a59312ff3537cd86d894523c5ab`** (2026-10-13, `chore: sync SKILL.md
copies [skip ci]`).

| Skill | Upstream path | Why it was worth taking |
|---|---|---|
| `caveman` | `skills/caveman` | The terse output voice: kills filler, keeps every technical fact. Applies to every message a bot emits. |
| `ultracave` | `skills/ultracave` | Maximum-compression variant of the same voice. |
| `caveman-review` | `skills/caveman-review` | One line per finding — location, problem, fix. This is the reviewer-to-harness payload shape. |
| `cavecrew` | `skills/cavecrew` | Output contracts for delegated children, so a child's summary costs a fraction of a prose one. |
| `caveman-explore` | `skills/caveman-explore` | `path:line`-only localization replies, keeping reads out of the caller's context. |
| `caveman-compress` | `skills/caveman-compress` | Shrinks a memory or context file, which is re-read on every turn. **Rewritten as prompt-only** — upstream ships 1834 lines of Python under `scripts/` wired to a Claude/Anthropic provider; this version compresses in place with the agent's own model and no extra provider call. |
| `surgical-patch` | `skills/surgical-patch` | Fix at the narrowest layer, no drive-by cleanup, stop when the regression proof passes. |
| `verify-and-stop` | `skills/verify-and-stop` | Smallest sufficient proof set; distinguish pass/fail/unavailable/blocked exactly; stop at acceptance. |

Every one was rewritten, not copied:

- [CC]-specific frontmatter dropped (`tools:`, `model:`, `disable-model-invocation`).
- The hook-driven `Caveman mode: <mode>` status relay removed — no hook host here, so
  there is no mode to track and the skill is invoked by name like any other.
- The named subagent presets (`cavecrew-investigator`, `cavecrew-builder`,
  `cavecrew-reviewer`, `Explore`) replaced with `delegate_task` plus a **literal output
  contract in the child's goal**, because a child cannot see a skill.
- `Read`/`Glob`/`Grep` replaced with `read_file`/`search_files`.

### What was deliberately not taken

| Rejected | Because |
|---|---|
| `caveman-evidence-review`, `caveman-setup`, `caveman-discover`, `caveman-manage`, `caveman-optimize`, `caveman-stats`, `caveman-learn`, `caveman-help` | Bound to the Caveman Cloud CLI and its MCP tools. Nothing here calls it. |
| `megacave` | Classical Chinese (wenyan) register. Not a token win for English bots. |
| `lean-build` | Feature building. The council reviews and fixes; it does not build product slices. |
| `investigate-first` | `systematic-debugging` already owns establishing a mechanism before editing. |
| `safe-refactor` | `simplify-code` is the cleanup path here, and nothing in this library restructures for its own sake. |
| `migration` | No skill here performs schema, data, or protocol migrations. Add it if that changes. |

## Upstream: addyosmani/agent-skills

One skill, taken as a local snapshot and condensed for review use. Upstream is a
builder-oriented teaching document (~17.6 KB); what is portable is the checklist,
the red flags and the falsifiable check.

Upstream: **addyosmani/agent-skills** (`security-and-hardening`, MIT). Recorded
without a pinned revision: the file was condensed by hand rather than copied, and
the parts that matter (OWASP categories, the SSRF and destructive-path rules) are
stable upstream. Re-read it before extending.

| Skill | Upstream path | Why it was worth taking |
|---|---|---|
| `web-app-security` | `security-and-hardening` | Web-app security had **no** owner in this library: the council's `reviewer-security` rubric is Nix-scoped (no XSS, CORS, sessions, SSRF, PII or LLM surface). |

**Loaded on demand, not always.** It is an *optional* skill: the council declares it
in the reviewer's `skills` list, so it is resolved by name from this library and
loaded only when a diff touches a web project. A Nix-only review never pays for it.
The seven sibling skills from the same upstream were rejected as redundant — see
the note below.

### What was deliberately not taken from that upstream

| Rejected | Already owned by |
|---|---|
| `code-review-and-quality` | the council — its five axes *are* the council's five dimensions |
| `code-simplification` | bundled `simplify-code` (both carry Chesterton's Fence) |
| `context-engineering` | `writing-for-agents` + hermes-agent's `references/project-context-files.md` |
| `documentation-and-adrs` | `domain-modeling` — which owns the three-test ADR rule |
| `planning-and-task-breakdown` | `to-tickets` — vertical slices, blockers |
| `spec-driven-development` | `to-spec` — specs, test seams |
| `using-agent-skills` | router class; the authoring conventions forbid router skills |

## Updating

To pull a newer upstream revision:

1. Check the upstream diff: `git -C <clone> diff v1.3.1..<new-tag> -- skills/`
2. Re-adapt the changed parts by hand — **do not overwrite** the local files. The
   local versions carry Hermes-specific changes (tool names, no tracker dependency,
   local-file defaults) that a straight copy would lose.
3. Update the pinned revision in this file and in each skill's
   `metadata.hermes.source`.
