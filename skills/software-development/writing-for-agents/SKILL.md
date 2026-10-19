---
name: writing-for-agents
description: "Write documents agents read: skills, AGENTS.md, docs."
version: 1.4.0
author: Matt Pocock (mattpocock), adapted by user, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
category: software-development
metadata:
  hermes:
    tags: [writing, context, pointers, skills, agents-md, pruning]
    source: mattpocock/skills@v1.3.1
    related_skills: [retro, hermes-agent-skill-authoring]
---

# writing-for-agents

How to write any document an agent consumes: a skill, an `AGENTS.md`, a doc reached
by a pointer. The packaging differs; the writing does not. The agent takes the same
**process** each run, so the document must make that process predictable — not make
the output identical.

For Hermes-specific skill mechanics (frontmatter fields, the validator, the
description hardline, tests, docs regen), see the bundled
`hermes-agent-skill-authoring`. This skill is the **writing craft**; that one is the
packaging.

## Context pointers

A **context pointer** is a reference in the agent's context that names some
out-of-context material and encodes the condition for reaching it. A skill's
description is one; a line in `AGENTS.md` naming a doc is the same object.

The pointer's **wording**, not its target, decides when the agent reaches the
material and how reliably. A must-have target behind a weakly worded pointer is a
variance bug — **sharpen the wording first**, and inline the material only if
sharpening fails.

A pointer does two jobs: say what the material is, and list the **branches** that
should trigger reaching it. A branch is a distinct case the document handles, so
different runs take different paths through it.

Every word of an always-loaded pointer costs on **every** turn, so it earns even
harder pruning than the body:

- **Front-load the leading word** — that is where the triggering happens.
- **One trigger per branch.** Synonyms renaming a single branch are one branch
  written twice. Collapse them; keep only genuinely distinct branches.
- **Cut identity the body already carries.**

## The two loads

Every document and pointer spends one of two budgets:

- **Context load** — the cost of always-loaded material: an `AGENTS.md` line, a skill
  description, anything sitting in context every turn, spending tokens and attention
  whether or not it fires.
- **Cognitive load** — the cost on the human: which documents exist and when to reach
  for each. The human is the index.

Cognitive load is **not** a cost to minimise; it is the price of human agency. Spend
it where human judgement matters, remove it where it does not.

Material reached only through a pointer escapes context load at the price of the
pointer's own line. Material with no pointer at all rides entirely on the human.

## Applying it

1. **Decide the load.** Always-loaded (a pointer, a rule that must never be missed) or
   reached-on-demand (a doc behind a pointer). Default to the latter.

   **A standing instruction that must apply on every turn belongs in the always-loaded
   identity slot, not in a skill.** A skill is *chosen* per task by the model and may
   simply not be chosen, so a voice or contract living only in a skill is a suggestion.
   The one place the host guarantees injection is the agent-identity file (`SOUL.md`),
   which is paid for on every turn — so it carries the **condensed** contract and the
   skill becomes the on-demand long form. Do not duplicate the long form into the
   identity slot to make it "stick"; put the short version there and point at the rest.

   The slot is **per-instance**, not per-repo: it is read from the instance's own home
   directory, never the working directory. A sub-agent or profile that runs with its own
   home therefore does **not** inherit the global file and needs its own copy — the
   failure is silent, because the agent simply keeps the default identity. Ship the
   fragment in the repo (so it is version-controlled and portable) and have each
   consumer's installer copy it into its own home; verify by reading the installed
   file, not the repo source.
2. **Write the pointer before the body.** If you cannot state the trigger crisply, you
   do not yet know what the document is for.
3. **Give each branch one trigger.** Then read the pointer back and ask which of your
   branches it would actually fire on.
4. **Cut anything that does not change behaviour.** "Be careful", "use best practices"
   and restatements of the obvious are pure cost.
5. **Co-locate a rule with the concept it governs.** A rule filed under a different
   heading is a rule the agent will not find when it needs it.

## One home per fact

A fact written in two places is a fact that drifts in one of them. Give each fact one
home, and let every other document link to it:

| The fact is | Its home |
|---|---|
| a rule an agent needs every session | the standing orders file (`AGENTS.md`, the identity slot) |
| how the parts fit together | the architecture map |
| a type, a semantic, an interface | the subsystem or package reference |
| why a decision was made, and what it gave up | the decision record |
| a rule review enforces | the review checklist, one line each |
| the contract of one component | that component's README |

When a document needs a fact from another home, it links. Restating it buys one reader's
convenience and costs every later reader a stale copy.

**Name the mechanism, not a metaphor.** Write the exact check, type, API, field or
command. Words like *surface*, *seam*, *vocabulary* and *gate* read as precise and name
nothing a reader can find in the code; reserve them for a term the project defines, and
otherwise say `response fields`, `JSON validation`, `ESM exports`. A metaphor survives
review because it sounds like an answer.

**A pointer must name a target that already holds the fact — check, do not assume.**
Replacing a paragraph with "see X" is the cheapest compression and the easiest to get
wrong: the writer believes X covers it because X is the relevant doc. Measured on one
pass, six of sixteen rewritten module docstrings pointed at a `SKILL.md` that did not
contain the rule they deferred — "silent when healthy", a no-PyYAML constraint, an env
var. A false pointer is worse than the long paragraph it replaced, because the reader
stops looking. Grep the target for the specific claim before writing the pointer, and
when it is absent either keep the fact inline or add it to the target in the same edit.

## Compressing an existing document

Delegating "make this shorter" to a model reliably destroys facts, and the usual
metric hides it. Three rules, each learned by measuring the failure:

**Line count is a decoy.** A source hard-wrapped at 80 columns shrinks ~50% in lines
from unwrapping alone, with a 4% cut in words. Target **words**.

**A word target causes fact loss.** Asking for "cut 36%" produced rewrites that passed
every identifier check and still dropped measured numbers and whole sections, because
every sentence carries a fact. If a reduction target must be set, say plainly that
fact preservation outranks it and that the target may be reported as unreachable.

**Check three things, because each alone has a blind spot:**

| check | catches | blind spot |
|---|---|---|
| every integer, **1 digit and up**, plus every decimal | a dropped measurement | a manifest keyed on `\d{3,}` missed a measured `42` |
| every backticked identifier, flag, path, profile name | a dropped name | prose facts are not tokens |
| a **sentence matcher**: for each claim-bearing sentence of the original, the best token-overlap match in the rewrite | a vanished section or claim | thresholds are judgement; check the flags by hand |

Prefer the sentence matcher over a distinct-word count: a vocabulary count flags
every inflection as a loss (`prosecutor` → `prosecutes`, `Mitigation:` → `Mitigate`),
so it over-reports and cannot be a verdict. Spot-check each flag before acting on it —
reworded rules and comma-compressed lists also look like losses.

A section can disappear while all three token checks pass and every heading survives,
so also diff the **heading set**, and treat a heading turned into bold text as a
structural change: headings are link targets.

**A rewrite made from an earlier snapshot silently reverts later edits.** If the
original was edited after the rewriting agent read it, installing the rewrite restores
the old text — a "fact-preservation check" passes while the doc regresses. Grep the
rewrite for the specific text you added to the original before installing anything.

**Cut in this order, and stop when every remaining line carries a fact.** When this user
asks for shorter docs the bar is "only as long as it requires to bring up the necessary
points" — a judgement, not a percentage. Measured on a repo whose inline comments ran
717 lines across 23 files down to 426:

1. **Commentary describing code that no longer exists.** The single largest block was
   43 lines explaining a setting that had since been removed. Nothing goes stale faster
   than an explanation of a decision that was reversed, and the reasoning belongs in the
   decision record rather than beside an absent line. This is always the first thing to
   look for, and it is invisible in a diff that only adds.
2. **Restatement of the line below it**, and of what an upstream option or default does.
3. **History and evidence trails** ("verified with…", "this used to be…").
4. **Section banners stay.** They are navigation, not prose, and cost one line.

**Prove a comment-only pass mechanically; do not assert it.** Hash the parse tree before
and after — `nix-instantiate --parse f | sha256sum`, `ast.dump` for Python — because
comments vanish in the tree, so identical hashes are the evidence. The hash is also what
catches the one edit that is not comment-only: a comment inside a multi-line string is
that string's content, so changing it changes the artifact (in a secret-generating
script, it changes the inputs). The file whose hash moves when you believed you touched
only comments is the file with a string in it.

Measure the ceiling before promising a cut: code blocks, tables and headings are
locked, so the compressible fraction is the prose. On fact-dense technical docs that
ceiling is often **10-20%**, not 40%. A doc whose prose is one fact per clause has no
fat: aggressive targets buy their reduction with claims, and the tell is that the
agents asked to hit them report back that the target was unreachable.

The same arithmetic governs a **machine-generated artifact** an agent reads — a
findings file, a report, a JSON payload. There the structure is the larger half:
measured on one such file, keys, ids, locations and indentation were **62%** of the
bytes and the prose fields **38%**, so an instruction telling the model to write more
tersely can only reach the smaller half. Measure the composition before spending the
model's attention on wording; change the serialization (indentation, repeated keys)
first, and verify that change costs no recall before keeping it.

**A single-sample A/B is not evidence.** Two runs of the same prompt differ by more
than a small wording change moves, so a measured 3.9% gap at n=1 per arm sits inside
that variance and must not be reported as a saving. Use the repo's own ablation or
corpus when one exists; until then say the saving is unproven rather than quoting a
number from one pair of runs.

## Claims

A prose claim about system state, a count, a path, or a mechanism is a **claim**, and
it is the part of a document that can be silently wrong — an agent reads it as fact and
builds on it. A doc set that makes claims should carry a script that re-derives each one
and exits non-zero on a false one, so truthfulness is checkable rather than asserted.

Classify every claim, and keep the label visible:

- **PROVEN** — a command run at write time re-derived it.
- **FALSE** — fix it now; a wrong claim is a defect, not a nuance.
- **UNPROVEN** — no available command can settle it. **Label it** (`UNPROVEN:`) with what
  would settle it. Do not assert it, and do not delete it: deleting hides a real
  question, and asserting invites the next session to treat a guess as a measurement.
  Historical figures and machine-specific counts land here.

Three rules that each cost a wrong document:

- **Re-derive at the moment you write the claim.** A number measured before later edits
  describes the old state, and the document is then wrong in a way no reader can detect.
  Quote the number you just ran, not the one you recorded earlier.
- **Prefer a claim you can re-run over a claim you have to remember.** If a figure has a
  generating command, cite the command beside it so the next reader can re-derive rather
  than trust.
- **A false claim about *protection, permission or safety* is worse than a false
  number.** A number misleads one reader; a wrong statement that something is read-only,
  sandboxed, or already gated becomes the **enabling assumption** for the next mistake —
  nobody re-checks a boundary a document says is there. Audit those claims first.

## Verify it as the consumer receives it

**Reading the file back is not verification — load it the way the agent will.** A
document can be correct on disk and unreachable in context: a pointer whose target is
absent, a support file that exists but is untracked so the build never sees it, a skill
whose served copy is a cached older version. So after writing, fetch it through the same
path the agent uses and read what comes back.

For a Hermes skill, the two paths differ and the difference decides whether your edit is
checkable in-session:

- **`skill_view(<name>)` reads the file per call.** An edit to an existing `SKILL.md` is
  served immediately, so you can confirm the new `version:` and the new section in the
  same session that wrote them. Do not assume a stale cache hides it.
- **The skill *table* — `skills_list`, the index in the system prompt — is built at
  session start.** A brand-new skill is therefore absent from it until a new session or a
  reload, which is a display lag, not a failed write. Confirm the file and the table
  separately, and say which one you checked. (A packaging skill that warns "the loader is
  cached" means this table, not the content — do not read it as "my edit cannot be
  checked".)

For a support file (`references/`, `templates/`, `scripts/`) the risk is the opposite: it
is present on disk and absent from everything that consumes the tree. Where a repo's gate
checks for dead references, an untracked support file that a SKILL.md names **fails the
gate** — `git add` it before believing the pointer works.

## Verification

- [ ] The pointer states the trigger, not just the topic
- [ ] Each branch has exactly one trigger phrase; no synonyms for one branch
- [ ] Always-loaded lines are justified against their per-turn cost
- [ ] Nothing in the document restates what a linked artifact already holds
- [ ] Every line would change the agent's behaviour, or it is gone
- [ ] Every factual claim is PROVEN by a re-runnable command, or labelled UNPROVEN
- [ ] The document was fetched the way the agent receives it (`skill_view` for a skill,
      a real build for a tracked support file), not merely read back off disk
