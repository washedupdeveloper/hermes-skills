# Upstream skills

Skills here were adapted from five external sources. This file records where each came from —
and the question that matters operationally: **whether they update themselves.**

They do not. Each is a **one-way copy at a recorded revision**, rewritten for Hermes, and the rewritten
file is ours. The upstream owns the *idea*; this repo owns the *file*. That is the safer default too:
an auto-updating skill is unreviewed code running with the agent's permissions.

| Source | Delivery | Syncs? |
|---|---|---|
| [mattpocock/skills](https://github.com/mattpocock/skills) via `npx skills add` | Editable files copied into your project | **No.** Upstream: "Nothing updates behind your back." |
| the same repo as a Claude Code plugin | Managed, read-only bundle | Yes, but Claude Code only — it does not apply to Hermes. |
| [agentskills.codes](https://agentskills.codes) | A one-time `.zip` per skill | **No.** No update mechanism exists. |
| [pingdotgg/t3code](https://github.com/pingdotgg/t3code) and the trees it vendors (`effect`, `alchemy-effect`) | Skills checked into the repository under `.agents/skills/` | **No.** Copied by hand at a recorded revision. |
| [sst/opencode](https://github.com/sst/opencode) | Skills checked into the repository under `.opencode/skills/` | **No.** Copied by hand; the rules landed in an existing reference. |
| DeepSeek Harness | A design document, read three times — see [ADR-0004](adr/0004-adopt-dsh-harness-rules.md), [ADR-0006](adr/0006-dsh-second-pass.md), [ADR-0007](adr/0007-dsh-third-pass.md) | **No.** Rules, not files. |

So: snapshots from every source, re-adapted by hand. An upstream change must be re-adapted rather than
merged.

## mattpocock/skills

First read at **v1.3.1** (2026-10-04, commit `6fd947921b935b7e1e69293a200400f0fdd5c15f`); re-read
unchanged in substance for the 2026-11 pass at commit `5863806dd4e15c63174bee4e7515a4256792ecfa`.

| Skill | Upstream path | What was worth taking |
|---|---|---|
| `handoff` | `productivity/handoff` | A resume point for a fresh session. |
| `domain-modeling` | `engineering/domain-modeling` | Glossary + ADR discipline; the three-test rule for when an ADR is warranted is the load-bearing part. |
| `to-spec` | `engineering/to-spec` | Conversation → spec, with test seams. |
| `to-tickets` | `engineering/to-tickets` | Tracer-bullet slices, blocking edges, expand–contract for wide refactors. |
| `wayfinder` | `engineering/wayfinder` | Work too big for one session as a map of decision tickets. |
| `retro` | `engineering/retro` | Reviewing the agent's environment rather than the code. |
| `wizard` | `engineering/wizard` | A generated script for steps only a human can perform. |
| `writing-for-agents` | `productivity/writing-for-agents` | Context pointers and the two loads; later the audit for prose written from the session's vantage. |
| `wait-what` | `productivity/wait-what` | Re-pitch in Simplified Technical English. |
| `grill-me` | `productivity/grill-me` | The single-question interview entry point. |
| `grilling` | `productivity/grilling` | The interview primitive both entry points share. |
| `grill-with-docs` | `engineering/grill-with-docs` | Grilling that records the decisions it extracts. |
| `codebase-design` | `engineering/codebase-design` | Deep modules, the deletion test, the seam vocabulary. |
| `zoom-out` | *(prose from the same source)* | One layer above the code when the map is missing. |
| `request-refactor-plan` | *(prose from the same source)* | Interview, scope and tiny commits before a refactor. |
| `improve-codebase-architecture` | `engineering/improve-codebase-architecture` | Shallow modules, named, with a deep-refactor proposal. |
| `two-axis-review` | `engineering/code-review` | Standards **and** spec as two axes that are never merged, plus the smell baseline. |
| `pr-description` | `engineering/pr` (crediting `humanlayer/show-me`) | The body as evidence: one view, before/after, door and blast radius. |
| `issue-triage` | `engineering/triage` | The state machine, and a brief an agent can act on. |

All were rewritten: descriptions cut to the 57-character index window, Claude-Code frontmatter
(`disable-model-invocation`, `argument-hint`) dropped, the `/setup-matt-pocock-skills` and issue-tracker
dependencies replaced by local files, and shell prose replaced with Hermes tool names.

**Two refusals were overturned, with the reason stated, because the earlier reason did not survive
contact:**

- **`code-review`** was refused as "covered by `requesting-code-review`". That bundled skill is the
  mechanical pre-commit pass; it does not ask whether the change matches its spec, and it carries no
  smell baseline. The two questions are different, and the axis that reports second buries the first —
  hence a skill whose whole content is keeping them apart.
- **`pr`** was refused as "the bundled `github` skill covers PR bodies". It covers `gh pr create`; it
  says nothing about what the body contains. Here the body has a shape — a view instead of prose,
  before/after evidence, and the door classification — that no skill stated.

`triage` and `to-questionnaire` did not exist at the first read; `triage` is adopted as `issue-triage`.

### Not taken

| Rejected | Because |
|---|---|
| `tdd`, `prototype`, `research`, `diagnosing-bugs` | Covered by `test-driven-development`, `spike`, `grounded-citations`, `systematic-debugging`. The one rule worth keeping from `diagnosing-bugs` — a missing test seam is itself a finding — is in `surgical-patch`. |
| `implement`, `implement-spec` | Hermes delegates natively, and `hermes-kanban-orchestration` owns the durable multi-agent variant. A third orchestration procedure would compete with both. |
| `to-questionnaire` | Elicitation is not in this library's scope yet; `wizard` covers the human-driven procedure next door. |
| `ask-matt`, `setup-matt-pocock-skills` | Router and configuration. The conventions forbid router skills. |
| `chief-of-staff`, `loop-me`, `software-factory`, `claude-handoff` | In-progress autonomous loops with side effects and a Claude Code host. |
| `git-guardrails-claude-code`, `migrate-to-shoehorn`, `setup-ts-deep-modules`, `scaffold-exercises`, `setup-pre-commit` | Tied to Claude Code, TypeScript, or a Husky/lint-staged toolchain. A commit-time gate is `deterministic-quality-gates`' subject, not a JS recipe. |
| `writing-beats`, `writing-fragments`, `writing-shape` | Book-writing craft, not software development. |
| `teach` | A learning-workspace system, not software development. High quality, out of scope here. |

## DeepSeek Harness

Read as a design document three times; the passes and their refusals are recorded in
[ADR-0004](adr/0004-adopt-dsh-harness-rules.md), [ADR-0006](adr/0006-dsh-second-pass.md) and
[ADR-0007](adr/0007-dsh-third-pass.md). The fourth read added one skill and one extension:

| Skill | Upstream path | What was worth taking |
|---|---|---|
| `failure-semantics` | `.agents/skills/dsh-error-handling` | Typed failures with stable codes, never routed by message text; the four conditions for an empty catch; what makes a retry sound; the success-shaped failure distinction. |

`deterministic-quality-gates/references/test-reliability.md` gained the process-cost and wall-clock
rules from the same pass (below).

### Not taken

| Rejected | Already owned by |
|---|---|
| `agent-experience` | `agent-harness-design` — the model-facing surface section, and `writing-for-agents/references/tool-surface.md`. |
| `dsh-prose-standard` | `writing-for-agents` — one home per fact, and the complete-proposition rule. |
| `dsh-find-simplifications` | `improve-codebase-architecture` and `simplify-code`. |
| `cordis-styling-nitpicking` | The three lifecycle rules have homes: a registration is an effect (`agent-harness-design`), quiescent teardown and unreversed side effects (`defensive-patterns`). A fourth statement would be a fourth home. |
| `dsh-pre-push-checks` | `verify-and-stop` — check selection, and never repeating a passing check for a push. |
| `dsh-ci-test-reliability` | Already adopted as `deterministic-quality-gates/references/test-reliability.md` (ADR-0007); this pass extended it rather than forking it. |
| `dsh-merging-stacked-prs` | No stacked-PR workflow here, and the procedure depends on a `gh stack` feature that would rot unpinned. |
| `dsh-archive-agent-notes`, `dsh-doc-writing`, `dsh-translate-docs`, `dsh-pr-description`, `dsh-create-upgrade-guide`, `dsh-official-plugin-artwork`, `record-browser-gif`, `dsh-client-ui-ux`, `dsh-responsive-ui`, `dsh-cua-macos-signing` | Repository-, host- or product-specific: the note lifecycle, the bilingual pair workflow, DSH's own PR template, plugin artwork, and recording browser GIFs. |

## pingdotgg/t3code

An agent control surface that controls other agents; its own skills are thin, and the interesting ones
are the trees it vendors under `.repos/`. Read at commit
`e5d757f51b342a5ebc50312790e39a1baca61194`.

| Skill | Upstream path | What was worth taking |
|---|---|---|
| `api-docs` | `.repos/effect/.agents/skills/jsdocs` | The public-declaration doc block: one practical paragraph, a present-tense action verb, optional sections in a fixed order, and a Gotcha that names a failure mode. |
| `workflow-security` | `.repos/effect/.agents/skills/ci-maintenance` | The trust-boundary audit for a workflow: which untrusted value reaches which sink with which credential. |

### Not taken

| Rejected | Because |
|---|---|
| `contribution-triage`, `test-t3-app`, `test-t3-mobile` | T3 Code's own contribution eligibility policy and app-test recipes; both depend on its GitHub App and its monorepo. |
| `audit`, `pr-queue`, `prepare-release`, `release-blog`, `release-overnight` | Provider-suite loops bound to `alchemy` accounts and infrastructure. |
| `alchemy-domain`, `alchemy-provider`, `harden` | Provider-specific. The one portable rule from `harden` — two consecutive full runs plus a leak census — is in `test-reliability.md`. |
| `changesets`, `dependency-maintenance`, `jsdocs` (the checker), `package-development`, `migration-guidance`, `ai-docs`, `effect-development`, `test-development`, `bundle-analysis`, `vendored-assets` | Effects, TypeScript and pnpm toolchain. Dependency rotation here is a Nix pin the gate already checks, and this repo's one generated copy is the council skill, whose rule is [ADR-0003](adr/0003-the-council-skill-is-a-generated-copy.md). |
| `performance-analysis` | A single unpaired run is not evidence — already the rule in `verify-and-stop/references/controlled-comparison.md`. |

## sst/opencode

Skills under `.opencode/skills/`, read at commit `0e447fce1623813d8af9bd5d1b511e8e2b4f4f81`. Nothing was
adopted as a skill: the four test skills are one subject — a suite that stays green under CI load — and
that subject already has an owner since ADR-0007. Their rules were merged into it.

| Reference | Upstream path | What was worth taking |
|---|---|---|
| `deterministic-quality-gates/references/test-reliability.md` | `.opencode/skills/unit-tests`, `app-e2e-tests` | Count spawns rather than wall time; start independent children together; never assert wall-clock speed; advance a fake clock to the next timer, not in fixed steps; `--isolate` is not a fix for one leaking test; two consecutive runs plus a leak census. |

### Not taken

| Rejected | Because |
|---|---|
| `component-tests`, `tui-tests` | Bound to opencode's Playwright-on-stories and OpenTUI renderer harnesses. |
| `opencode-dev`, `sample-skill`, `effect` | Repository conventions, a fixture, and Effect-TS. |
| `rtl-aware-development` | Right-to-left UI work; no user interface is in this library's scope. |

## JuliusBrussee/caveman

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

## addyosmani/agent-skills

Upstream is a builder-oriented teaching document (~17.6 KB); what is portable is the checklist, the red
flags and the falsifiable check.

| Skill | Upstream path | What was worth taking |
|---|---|---|
| `web-app-security` | `security-and-hardening` (MIT) | Web security had no owner here: the council's `reviewer-security` rubric is Nix-scoped, with no XSS, CORS, sessions, SSRF or PII surface. |

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

## agentskills.codes

**Nothing taken.** It is a scraped aggregator of ~6,300 skills, most at 0–1 installs, and two things
disqualify it: its provenance is third-hand (`effective-go` is itself a copy from
`openshift/hypershift`), and its content is often a pointer — "follow the official guide at <URL>" —
rather than a skill. The framework guides it does carry duplicate documentation the frameworks
maintain, which a snapshot would fossilise.

## Updating

1. Read the upstream diff: `git -C <clone> diff <pinned>..<new-revision> -- skills/`.
2. Re-adapt the changed parts by hand. **Do not overwrite** — the local files carry Hermes-specific
   tool names, no tracker dependency, and local-file defaults that a straight copy loses.
3. Update the pinned revision here and in the skill's `metadata.hermes.source`.
4. A rule that already has an owner gets a pointer at most. Check before writing: a second statement of
   a rule is how the library acquires two answers to one question.