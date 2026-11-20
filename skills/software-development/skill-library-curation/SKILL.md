---
name: skill-library-curation
description: "Curate the skill library: sourcing, overlap, conflicts."
version: 1.11.0
author: user, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
category: software-development
metadata:
  hermes:
    tags: [skills, curation, refactoring, overlap, provenance, audit]
    related_skills: [hermes-agent-skill-authoring, writing-for-agents]
---

# Skill Library Curation

Auditing and optimizing the installed skill library **as a set** — finding and
fixing overlap between skills, contradictory instructions, stale rules, and
verbosity — and deciding what to take in from outside it. Skills are LLM
instructions: every line is paid for on every load, and a
rule stated in two places drifts out of date in one of them.

Three adjacent skills, each with a distinct job:

- **this one** — the library as a *set*: provenance, overlap, conflicts, mirroring.
- `hermes-agent-skill-authoring` — the *format* of a single Hermes SKILL.md
  (frontmatter fields, body section order, tests and docs for in-repo skills).
- `writing-for-agents` — the *writing craft*: context pointers, the two loads, and
  how a pointer's wording decides whether it ever fires.

## When to Use

- "Go over the skills and make them shorter / less redundant / non-overlapping."
- A skill contradicts the code it describes, or contradicts another skill.
- A rule was updated in one skill but siblings still restate the old version.
- Skills need to be made portable / free of machine-local paths.
- **"Make this library usable by any agent"** — which members are host-bound, and how to label
  them without moving them (*Host scope is a label, not a directory*).
- **"Make this library independent of every other project"** — what counts as coupling rather
  than provenance, and the clean-clone proof (Step 2, *Independence*).
- **"Add this external skill" / "keep it updated" / "I don't want to maintain it
  myself"** — choosing which of a source's skills to adopt, and whether to
  reference it or vendor it (Step 9).
- **"Learn everything from this repository, then delete it"** — mining a foreign tree
  for rules rather than skills, then retiring the source safely (Step 10).
- **"Review this source's skills and tell me what is worth taking"** — decide by class
  rather than file (router, micro-skill split, host-specific fields, rules no owner here
  states), per Step 9's router subsection.

## Step 1 — Establish provenance before touching anything

Three classes of skill live under `$HERMES_HOME/skills/`, and they need **opposite**
treatment.

| Class | How to identify | Editable? |
|---|---|---|
| Bundled | listed in `.bundled_manifest` (`<name>:<hash>` per line) | **No** — `hermes update` refreshes it; edits are clobbered |
| Hub-installed | an `installed` entry in `.hub/lock.json`, whose `identifier` carries the source (`skills-sh/<owner>/<repo>/<skill>`) | **No** — upstream's; `hermes skills update` maintains it |
| Locally authored | every dir with a `SKILL.md` in neither record | Yes — and only this class may be promoted into the repo |

```bash
cd "$HERMES_HOME/skills"
for f in $(find . -name SKILL.md -not -path './.hub/*'); do
  n=$(basename "$(dirname "$f")")
  grep -q "^$n:" .bundled_manifest && continue
  grep -q "\"$n\"" .hub/lock.json 2>/dev/null && { echo "hub: $n"; continue; }
  echo "local: $n  ($f)"
 done
```

`.curator_ledger.jsonl` records an `actor` per change (`curator` / `agent`) — useful
for confirming who owns a skill.

**A hub skill is invisible to the manifest.** `.bundled_manifest` lists only what
shipped with Hermes, so a two-class check calls every hub-installed skill "local" —
and that misclassification is exactly what turns "promote my local skills" into
vendoring somebody else's (Step 9, item 7). Confirm ownership from the identifier in
`.hub/lock.json`, never from absence in the manifest.

Report the bundled count and skip them explicitly. Silence reads as an oversight.

## Step 2 — Separate repo-sourced skills from author-in-place ones

Some skills are **copies** pushed from a source repo by a sync script. Editing the
installed copy is lost on the next sync.

- Find the sync script (commonly `<repo>/scripts/sync-to-skill.sh`) and read which
  paths it copies.
- Edit the **repo source**, then run the sync.
- If the sync has no `--check` mode, add one: compare instead of copy, print each
  drifted path, exit non-zero. That gives copy-based distribution the same guarantee
  as a symlink, without symlink portability problems (elevation on Windows, and a
  symlink into a repo breaks the skill for anyone who installs without the repo).

### When the gate says the copy drifted

The report is usually right — an unsynced copy is stale — but three causes wear the same
message, and they are settled cheapest first because ordinary `diff` conflates them.

1. **Content.** `diff --strip-trailing-cr copy/x source/x`. Whatever remains is real drift,
   and it is read *before* re-syncing: the copy may hold a lesson the source never received,
   which a sync deletes (pitfall below).
2. **Line endings.** A file differing only by CR is the generator's normalisation, not drift.
3. **A missing final newline.** One byte at EOF is not content. A generator documented as
   `sed 's/\r$//'` *that also terminates the last line* can never match a source whose last
   line is unterminated; `cmp -l` showing one byte, and a `diff` hunk whose only change is
   `\ No newline at end of file`, is the entire diagnosis. **Terminate the source; never
   weaken the claim to absorb it** — the generator was masking a real defect, and a
   byte-exact claim is worth keeping exact.

Two further defects the copy's own suite finds, both fixed in the generator rather than the
installation:

- **Ship the data, not only the code.** A sync that copies `scripts/` and `tests/` but not the
  directory those scripts open at runtime produces a deployment that looks complete and cannot
  work: dozens of failures with one cause (`FileNotFoundError: protocol/…`, "the contract is
  missing"). Ship every file the shipped code reads beside the code that reads it.
- **When the copy runs the source's suite, ignore only what it cannot carry.** A deployment
  ships the tool, not the project, so a test importing a module left behind cannot run. Derive
  the ignore list from pytest's own collection errors and fail on every error whose reason is
  not `No module named`, so a syntax error is never skipped as "not ours". The reason lives in
  the `ImportError while importing test module '<path>'` block; the `-q` summary prints only
  `ERROR tests/x.py`, so a parser reading that line finds nothing at all.

### When the generator is being replaced

A copy is only as good as its generator. When the upstream project is rewritten and the
rewrite cannot deploy a skill yet — no `setup skill` verb, a different layout, a thinner skill
of its own with nothing to ship — the copy is a fork with no future. **Remove it from the
library rather than keep it in step with a repository nobody will run**, and install it
locally in `$HERMES_HOME/skills/` so the command keeps working while the rewrite catches up.
An artifact that leaves takes its checks with it, and each one is a place the copy was still
described:

- the claim comparing it to its source — **delete it**, do not leave it reporting `UNPROVEN`:
  a claim about an absent thing is noise in a ledger whose only value is that every line is evidence;
- the tests whose subject was its code, including any that ran its suite;
- the README counts and the layout-tree row — a copy is usually the only skill carrying support
  `SKILL.md`s, so `N SKILL.md across N skills`, the platform figure and the rubric sentence all
  move at once;
- a marker exempting a file *inside* it (a formatter's golden fixture) **and** the assertion that
  the fixture exists, which now fails closed on its absence;
- any reader that hardcoded its on-disk layout.

**Delete the removal record with the thing, when the library states only what is.** A tombstone
ADR — "X left the library", "X is a generated copy, withdrawn" — is itself a reference to the
deleted thing: it keeps the name in the index and in every reader's head. This owner's standard
is that the tree describes the present, so the ADR that justified publishing the artefact and
the one that recorded its removal both go, with their rows in the ADR table; and the records
that reasoned *by citing* them are rewritten, because the argument usually stands without the
example ("a copy drifts from its source and nothing notices"). Withdrawing is right only where
the repo treats decision records as immutable history — ask once, and never assume a label like
"withdrawn" makes a tombstone harmless.

**The records are the smallest half of a removal.** What outlives an artefact is everything that
*asserts* it: frontmatter names a gate resolves, a spec requirement binding this library to
another project, a sentence deferring its detail to the removed skill, archived change records
describing files that no longer exist, and data files that baked its paths in.
`references/removal-audit.md` is the sweep — where each survives, the grep order, how to tell an
assertion from an illustration, and the evidence a finished removal reports.

### Independence — prove it from an empty directory

A library that publishes artefacts from other projects drifts into depending on them, and the
drift is invisible while those checkouts sit on the same disk. **Independence is a property of
execution, not of prose:** the question is not "does the tree mention another project" but "does
it still work when that project is gone". Prove it from a clone with nothing beside it.

```sh
git clone <repo> /tmp/independent/lib && cd /tmp/independent/lib
python3 scripts/validate.py && python3 -m pytest tests/ -q && python3 scripts/claim-audit.py
./install.sh /tmp/independent/agent-skills --nested   # the install path, not only the gate
nix flake check                                       # the optional second engine
grep -rn 'R\.parent\|/home/\|/Users/\|~\(/projects\)' --include='*.py' --include='*.sh' .
grep -rln '<other-project>' --include='*.py' --include='*.sh' --include='*.nix' .
```

- **Sibling-checkout arithmetic is coupling.** `REPO.parent / "<other-repo>"` makes a rule about
  *this* tree depend on what someone cloned beside it, and a clean clone flips its claim from
  `FALSE` to `UNPROVEN` — which reads as a pass. Delete the check with the artefact.
- **Search data and caches before counting, or the count is noise.** A tracked fixture can carry
  `/home/<user>/…` in a recorded field, and an untracked cache (`.hypothesis/constants`,
  `__pycache__`) embeds the checkout path in dozens of files — a name search over the tree then
  reports a deleted project everywhere and means nothing. Delete or exclude caches, search
  `fixtures/` and `*.json` as well as code (`search_files`, or `grep -rn` in a shell), and quote
  the count only after that.
- **An adapter to one project's on-disk layout is coupling, not a feature.** A reader that
  hardcodes another tool's state directory, its dimension names and its verdict filename only
  works for that project. Move it out of the library, or generalise it to "read whatever that
  tool recorded" and drop the names: keep the rule it taught, not the schema.
**Rename the vocabulary, then delete the old spelling.** A data schema keeps a project's name
long after its code is gone (`owner: <project>`, a `<project>_run` property). Rename to the
neutral term and remove the old key outright: one spelling, judged as written. A read alias
plus a duplicated key is a stopgap for pages already on disk — offer it once, name it in the
report as temporary, and retire it when the owner says nothing should be left behind, which
is this owner's bar. After the alias goes, a page still carrying the retired value lints as
wrong, and that is the honest report: the value is wrong, not the rule.
- **Provenance is not dependency.** A ledger of upstream sources with pinned revisions is what a
  republishing library owes the licences it shares them under, and nothing executes it. Keep it,
  and state that it was deliberately left alone.
- **The working tree hides the last coupling.** Untracked files and local checkouts let a dirty
  tree pass checks a stranger's clone would fail — and the clone is the only tree that proves
  the installer works without the author's layout.

### Being consumed: the integrator resolves, the library stays silent

A library that another tool *uses* needs no knowledge of that tool, and this direction costs
the library nothing — a consumer reads `library/contract.json` and
`skills/<category>/<name>/SKILL.md`, both of which already exist. Keep it that way.

- **Resolve the library by structure, never by name.** `--library`, else `$SKILLS_LIBRARY`, else
  the nearest ancestor holding `library/contract.json`. A directory that is renamed, vendored or
  cloned elsewhere is still found; one that merely shares the name is not.
- **The destination is a directory shape, not an agent.** Anything laid out as `<name>/SKILL.md`
  is a destination: `--dest`, else `$SKILLS_DIR`, else the directory an `--agent` name maps to.
  Agent names are a convenience table, so the verb must **refuse to invent** a directory that is
  not already on disk — a machine without that agent gets a message, not a stray tree. That is
  what lets one implementation serve every host, including whichever one replaces this one.
- **Install semantics that cannot lose work:** a byte-identical copy reports `unchanged`; a
  differing copy is refused unless `--force`; `--dry-run` writes nothing; a refusal exits
  non-zero and says how to force it.
- **A verb that parses and documents is not a verb that runs.** Add one test through the real
  entry point (`main([...])`, not the helper it delegates to): wiring is exactly what a
  module-level suite bypasses, and a missing dispatch branch survives a green unit suite, a
  declared-command check and every frontmatter test at once.

## Step 3 — Find overlap by owning token

Overlap is invisible from inside one file. Pick a distinctive token from a
cross-cutting rule and search the whole tree for it:

```bash
grep -rn "outputHashMode\|cygpath\|bash_logout" "$HERMES_HOME/skills" --include=SKILL.md
```

Any hit outside the owning skill is a duplicate that will drift. Fix by deleting the
copy and leaving a pointer to the owner.

**One owner per rule.** For every cross-cutting rule, exactly one skill states it
whole; every other skill that needs it names that skill. A pointer costs one line; a
copy costs a future stale rule. Aim for skills that behave like pure functions —
near-zero overlap, no hidden side effects — and where a skill genuinely depends on
another, say so in its `## When to Use` or intro so the dependency is visible.

## Step 4 — Resolve conflicts against the source of truth

When a skill and the code disagree, **the code wins**. Find the discrepancy, fix the
skill, and do not leave both standing.

Prefer **deleting** a false instruction over softening it. An unenforced spec inside
a skill — a formula nothing reads, a flag nothing accepts, a step nobody implements —
reads to a future agent as required work. Remove it and state who owns that concern.

## Step 5 — Measure before cutting, then cut

**Measure first: the ceiling on prose trimming is low, and guessing at it wastes a
pass.** Two independent measurements on real corpora — deleting every duplicated
6-gram plus all filler across a 34-skill library (32k body tokens) recovers **1.3%**,
and across a 58-skill bundled set (56k tokens) **2.6%**. A separate A/B on an agent
prompt returned −3.9% at n=1 per arm, which is inside sample variance. Skill and
prompt bodies are mostly *payload* — code, commands, paths, tables — and the prose
around them is a rounding error.

So never mass-rewrite a library for verbosity. Fix what is unambiguously broken — a
dead reference, a description past the index window, a rule stated twice — and report
the **measured** recovery instead of claiming an improvement you did not verify. Report
shape: verdict, numbers, what was deliberately left alone and why — no process narration,
minimal markdown, and no adjective where a count belongs.

**When the owner asks for a library-wide rewrite, the measurement is the answer.** Run the
audit first and report what it says: filler lands near 0.2% of the corpus and duplicated 6-gram mass
between 1.3% and 2.6% — frontmatter included, so quote it as n-gram mass, never as prose
redundancy, so editing prose has almost nothing to recover and every cut risks a
fact. Name the one structural candidate you can defend, such as a maximum-compression variant
of a brevity skill, with its cost (a user-facing command, an index line), and leave the delete
to the owner.
`scripts/skill-audit.py` produces the numbers (bytes, body tokens, description
lengths, filler, cross-skill n-gram redundancy, dead refs, orphaned support files):
run it before and after, and diff the JSON.

**Know what that audit counts.** It takes one root (extra arguments are ignored).
`redundant_token_mass` includes frontmatter, so shared `version/author/tags` inflate it —
on a 44-skill, 68k-token library the real prose duplication was 11 sentences, 122 words
(0.23%). `dead_refs` flags a valid `script.py <arg>`; `orphans` flags files whose directory
the prose names. Read every hit. Compile with `compile()`, not `py_compile`: the latter
writes `__pycache__` and inflates `orphans` on the next run.

**Freeze the instrument.** Hash the harness (`sha256sum`) and confirm the hash matches
for both runs. A metric script edited between runs measures the edit, not the change.

**Hash the corpus too, and attribute any delta before believing it.** A background
writer — the self-improvement review, a curator pass, another agent — can edit the
tree *between* your two runs, so a changed total may be entirely theirs. A second run
that grew the corpus while you only removed bytes is the tell. Re-run the audit on a
fresh copy and diff the per-skill `bytes` map: a file that changed and that you never
touched names the third party. Until the corpus hash matches, the before/after is not
a measurement.

Having measured, cut without losing the point:

- **Merge overlapping sections.** A skill often lists the same commands under two headings.
- **Drop provenance narration and design history.** Keep the operative constraint, not the story of how it was discovered.
- **Move bulk detail into `references/`** — the procedure, and the orphan trap that follows
  it, are below.
- **Prefer tables and checklists** over paragraphs — same content, fewer tokens.

### Moving a section into `references/`

Tiering is the only cut that lowers the load cost without deleting a fact: the section moves
whole and the skill keeps a pointer. Four steps, in order.

1. **Measure the share first.** `scripts/section-share.py <root>` prints each skill's largest
   H2 section and its percentage — that share is exactly what the load cost falls by, so it is
   the number to report, quoted from that run rather than from a previous one. Routing and load are a second measurement: `scripts/skill-bench.py <root>
   assets/skill-queries.json` routes a frozen query set against the descriptions and reports
   accuracy, MRR and the mean body-token cost of the skill it chose. Run it on a worktree of
   HEAD and on the working tree, or the delta is not attributable to the pass.
   It measures lexical overlap between your query text and the description — **not** whether
   an agent selects the skill — so treat the number as a smoke test for wording, never as
   evidence that a skill performs better.

**A behavioural claim needs a control arm, not a better metric.** No text measure shows that
a skill changes what an agent does. Run two arms on one task — the skill in the workspace for
one, absent for the other, identical prompt — and pre-register three outcomes before any agent
starts: the pristine fixture fails only for the planted reason, a gold solution passes, and the
tempting naive fix fails on *content* while still evaluating cleanly. A trap that crashes
teaches nothing; the wrong answer has to look right. Score the artifacts, never the reports.
Equal arms is a real result: a strong model often solves the task from priors, so report "no
measurable difference" rather than re-cutting the task until it separates. Recipe, fixture
traps and the ceiling case: `references/benchmarking-a-skill.md`.
2. **Move the body byte-for-byte.** Split on `\n## <heading>\n`, write the tail to
   `references/<topic>.md`, then assert the original body is a substring of the new file. The
   assertion is the proof that nothing was deleted; a word count is not.
3. **Replace it with a trigger list, not a pointer.** A line that only says "see the
   references file" does not fire. List the operations the bullets cover — `mkForce`/`mkDefault`,
   taking a version from a flake input, adding an output, copying out of `/nix/store` — so a
   reader matches their task
   against the list before acting.
4. **Re-name whatever the moved text was the only mention of.** Every reference file that
   section cited becomes unreachable the moment it leaves, and the next audit reports it as an
   orphan. Name them at the top level, or the move silently costs a hop nobody takes.

**A routing number is evidence only if the queries were written blind.** Choose the query
set before reading the descriptions, or draw it from real session requests — writing queries
while looking at the text you are about to change measures your own fitting. Measured on one
library: the tuned 31-query set read 0.87 → 0.97, while 30 held-out queries read 0.43 → 0.47.
The first run of the bench reported 0.57 → 0.63 because it scored `metadata.hermes.tags` as
well; the loader never reads that field, so half the effect was a signal the model does not
receive. Score only what the prompt shows — name and description — or the number measures
an easier problem than routing.
Quote the held-out delta as the effect size; the tuned figure only shows the set was too easy.

**Score a candidate description in memory before writing it.** Substitute the string into the
loaded row, re-run the router on both sets, and keep it only when held-out rises and nothing
falls. A wording that wins one phrasing can lose another: deleting "turn" from a description
lost a query the old text had won, and no size or duplicate metric sees that.

**Count the trigger list against the bullets.** Eight triggers against 31 pitfalls leaves 23
with no signal, so the move costs a hop for most readers. Raise coverage or add a catch-all
line — "if a change fails in a way you did not predict, the answer is here" — because an
enumeration can never name every case and a catch-all costs one line.

Say the trade out loud in the report: the facts are one hop away, and a reader who ignores the
trigger list will work without them. A pitfalls or rules block is usually why the skill exists
— a large share is a reason to read the section before moving it, not a verdict.

## Step 6 — Validate every file you touched

**Read the target repository's gate before you draft, because "done" is per-repo.** One
in-repo skills tree demands a per-skill pytest, a regenerated docs page and a sidebar row;
another enforces a contract file — required frontmatter, an index window, a category set —
through one `nix flake check`, then proves the loader with a live-discovery script and the
prose with a claim audit. Importing the first tree's artefact list into the second writes a
test nobody runs; importing the second's into the first skips a gate. Enumerate the gate
(the agent instructions, the contract file, every test that parses the docs), then say which
command you ran and what it printed.

```bash
python "<skill_dir>/scripts/validate-skills.py" "$HERMES_HOME/skills"
```

For the cost and duplication half — description lengths, dead refs, orphaned support
files, cross-skill redundancy — run `scripts/skill-audit.py` on the library root and
on any source repo; it is deterministic, so before/after is a valid comparison:

```bash
python3 "<skill_dir>/scripts/skill-audit.py" <skills-root> > audit.json
```

Checks what breaks loading or discoverability: leading `---`, required frontmatter,
description ≤ 60 chars ending in a period, `name` matching the directory, and every
`related_skills` entry resolving. Exit 0 = clean.

**A skill's scripts are covered by no metric — compile and run them.** The audit counts
bytes, descriptions, dead references and orphans; a promoted or freshly written Python file
under `scripts/` with a syntax error passes all of those and ships dead, while the SKILL.md
tells the reader to run it. Before calling a skill validated: parse the tree in memory (`compile(p.read_text(), str(p),
"exec")` per file) — `py_compile` writes `__pycache__` into the tree you are measuring, which
the next audit reports as orphaned support files — and run each script's `--help`, plus its
real mode on a throwaway input. A script nobody can execute is a
claim like any other — a dead reference the audit cannot see.

**Count what the check actually examined.** A `while read … done < <(find …)` loop hands the
child its file list on stdin, so one `python … --help` that reads stdin consumes the remainder
and the loop exits early — a sweep reported 4 of 65 scripts and read as a clean run. Redirect
the child (`</dev/null`) and assert the items checked against `find … | wc -l`; a check that
silently skipped most of the tree is a pass you cannot quote.

**A reference check must read fenced blocks, not only prose spans.** A dead path inside a
fenced block is a command a reader runs, and a span-only scan never sees it — a retired
install script sat that way through three audits. Scope the check to a directory the skill
actually ships: a `scripts/<file>.py` in a skill with no `scripts/` names another repository
and cannot be verified here, so skipping it is correct, not lenient. Then prove the check by
injection: append a command naming a file that does not exist, watch the test fail on that
exact path, remove the line, watch it pass. A check that has only ever passed is an untested
claim.

**A rule exercised through a different entry point is not controlled.** A validator with a
single-file mode and a tree sweep runs its pointer rule only in the sweep, so a "must pass"
control written against the single-file mode passes whatever the rule does — and it reads as
coverage while proving nothing. Pair every must-pass control with a must-fail control on the
same path; the paired failure is what tells you the rule still fires.

**One defect, one line.** Two rules can catch the same problem — a per-file check sees a CRLF
`SKILL.md`, and the tree sweep sees the same file again — so the report lists it twice and a
reader chases a count that is one file. Dedupe at the reporting point (an ordered set of
`<where>: <what>`) rather than deleting whichever rule happens to be reached first.

**Point the validator at every tree the loader sees, not just one.** `validate-skills.py`
resolves `related_skills` against the union of the roots it is given, so a repo-only run
reports every bundled sibling as unresolved and buries the real failures among false ones:
`validate-skills.py <repo>/skills "$HERMES_HOME/skills"`.

After a promotion, run the repo's own gate before touching any prose a test measures — a repo
that asserts its counts in tests fails on the addition and tells you the right numbers. **Stage
the new skill first.** A Nix check copies only git-visible paths, so an untracked `SKILL.md`
reads as absent: the counted total stays old and the README number you just corrected is
reported FALSE. `git add` the new directory, then gate.

The asymmetry is what bites: a **modified tracked** file is copied with its working-tree
content, but an **untracked** one is absent entirely. So a tracked `SKILL.md` whose edit cites
an untracked `references/<topic>.md` fails as a dead reference with the file sitting on disk
beside it — and every later commit inherits the failure, because the citation is tracked and
the target is not. When the failure is the other writer's, `git worktree add --detach <dir>
<sha>` gives a clean tree at your own commit, so your verification does not depend on their
uncommitted state.

**A generated file the gate compares against a registry is part of the change, not a follow-up.**
A claim ledger, a docs table, a manifest: the check compares the file to the registry, so adding
an entry fails as drift the author never wrote (`does not match the registry: run … --write`).
Regenerate it with the repo's own verb in the same commit, and read that message as the
instruction it is rather than as a mystery failure.

**When the repo ships a test suite, that suite is the before/after.** `git stash push -u`, run
the tests, `git stash pop`, run them again; equal counts on both sides is the reliability claim.
A doc edit that moves a phrase a test measures fails here and nowhere in the audit — and the
suite is usually found one level deeper than the obvious glob (`tests/unit/`), so enumerate
before concluding a repo has none.

## Step 7 — Bulk rewrite mechanics

When re-writing many files in one pass:

- **Back up originals first** (`cp` the tree into the scratch dir). A failed bulk
  edit is otherwise unrecoverable, and the skills directory may not be under version
  control.
- **Stage each new body in the scratch dir, then copy it into place** with
  `terminal`. `write_file` refuses to overwrite a file whose most recent read was
  paginated (`offset`/`limit`) — the guard's state is sticky, so even a later read
  that returned the file whole does not clear it. Staging and copying is the
  reliable path; it also keeps the batch uniform and makes backing out trivial.
  **The target can be unreachable outright.** A path in another filesystem
  namespace — a WSL mount from a Windows host (`\\wsl.localhost\...`), a container
  volume, a network share — fails at `mkdir` with a read-only-filesystem error, and
  both `write_file` and `patch` give up on it with the same message. Same dance:
  write where the tools can reach, then `tr -d '\r'` the file into place with
  `terminal`.
- **Diff afterwards and read the removed lines.** That diff is the review: confirm
  every removal is a duplicate, a false instruction, or pure verbosity.
- **Prefer one `patch` per file over a script that edits many.** Each patch is
  independently approvable and reviewable and a refusal costs one file; a multi-file
  `execute_code` batch is one all-or-nothing approval, and its refusal freezes the whole
  edit set at once.
- **A refused batch is recorded, not re-routed.** When the approval gate refuses a batch
  ("silence is not consent"), write the unapplied edits into the decision record — target
  file, anchor, replacement — and stop. Re-issuing the same outcome through another tool is
  what the refusal forbids; the next session applies them from the record.

## Step 8 — Make the repo the source of truth, mounted not copied

The repo is **referenced** via `skills.external_dirs`; machines do not push their
library into it. A copy-back script (`rm -rf skills/ && cp -r`) is the
anti-pattern — with two machines whose skill sets are disjoint it deletes the
other's. If you find one, delete it.

**A reference is not read-only, and believing it is costs you the repo.**
`external_dirs` makes the tree *readable* by Hermes; the background self-improvement
review patches an existing skill **in place, wherever it is found**, so an unattended
agent can write into a source-of-truth repo. A symlink does not fix it either —
`skill_manage` follows symlinks, so the write is *redirected* through the link rather
than prevented. Only a Nix **store** path is genuinely immutable. For a git-tracked
repo the gate is **git**: a stray write shows in `git status` / `git diff`, which is full
coverage at zero friction — prefer it to `skills.write_approval`, and set that only where
the tree is untracked. Run `git status` before committing anything you did not write
yourself.

**Never `git checkout -- <file>` to undo your own experiment.** It restores HEAD and
silently discards whatever the background review appended since, with no copy and no
warning; a dirty file was dirty before you touched it. `cp` it aside first and restore
from the copy, or `stash` and read what the stash holds before dropping it.

**Stage explicit paths, never `git add -A`, in a tree another writer touches.** A blanket add
folds the background review's uncommitted edits into your commit and destroys attribution:
stage the files you changed by name, and give the foreign edits their own commit after
reading them.

**An explicit `git add` is not enough when the index was already loaded.** `git commit`
commits every staged path, not the ones you just named, so a second writer's staged work
rides along even when every `add` named a file of yours: a commit meant to be 138 files
landed 155, seventeen of them not mine, and the tell was `--stat` after the fact. Check
`git diff --cached --name-only` against the set you intend and abort on **any difference in
either direction**: a stray path, and equally a file you meant to stage that is missing. A
guard that rejects only strays passes on a commit carrying one file of the three you edited,
and the two lost edits look committed because the commit itself succeeded.
When it has already happened, `git reset --soft HEAD~1 && git reset` puts the tree back
byte for byte — nothing on disk moves — and leaves the foreign work unstaged for its author.

**A file the other writer has dirtied is often one you must change too, and `git add` would carry
their work.** Stage your line and nothing else by staging a *constructed* version: `cp` the working
file aside, `git show HEAD:<path>` back over it, apply your edit with the anchor-checked script,
`git add`, then restore the copy you set aside. The commit then holds exactly your change while
their edit stays uncommitted in the working tree. Read `git show --stat HEAD -- <path>` afterwards:
one insertion is your line, sixty is their edit folded in by mistake.

**Check shared ancestry before merging into a default branch.** `git merge-base --is-ancestor
origin/<default> <feature>` and `git merge-tree --write-tree origin/<default> <feature>` answer
"fast-forward?" and "conflicts?" without checking anything out. Unrelated histories are a
different product rather than a merge — welding them adds and deletes a few hundred files to no
purpose — and replacing the default branch is the owner's decision, not the agent's. Landing it
— fast-forwarding the remote ref from the feature branch so no checkout is needed, then deleting
the branch — is `ci-workflow-verification` step 7: the mechanics have one owner and are not
restated here.

**Attribute a change you did not make before you carry it.** A dirty file or an unfamiliar
commit is the background review or a second agent, and the evidence names it: `git status
--porcelain`, `git reflog -8` for who committed and when, `git log -1 --format='%h %ci %s'
-- <file>` for the commit that last touched that file, and `stat` for the write time. Read the
diff whole and gate it on the current tree before carrying it, then commit it as that writer's
work and name it in the message. A commit that landed between your last check and your report
is also a claim about the report: say the state changed, rather than restating the older one.

**Precedence: `project > local profile > skills.create_dir > external_dirs`.** A
name present both locally and in the mount resolves to the LOCAL copy, silently —
so an installed duplicate shadows the repo and edits to the repo appear to do
nothing. Keep names unique across the two, or delete the local copy when a skill
moves in.

**A locally-authored skill living only on the profile is a finding, not a state to
leave.** It is invisible to every other machine, and the day the repo gains a skill of
that name the local copy silently wins. When the owner says the repo is the source of
truth, the promotion is part of finishing the work — and the report says which skills
moved and which stayed behind because they are not ours (Step 1).

**Same name is a comparison, not a copy.** Diff the two before promoting, newest version
field first, then the headings: the repo copy is often the later one, and copying the
profile's older file over it replaces a maintained skill with a stale one — through the
mount, where the result looks like an ordinary edit. Keep the newer file and port
whatever the older one had that the owner lacks before deleting it.

**A different name for a subject the repo already owns is a merge, not a sibling.** Two
skills for one question route against each other, and the weaker one wins queries it
should lose. Take only the delta the owner lacks — a rule plus a reference — then delete
the local copy. The test is Step 9 item 3's: zero new skills is a legitimate promotion
result.

Migrate a live library in this order, because a wrong path is skipped silently (a
non-existent entry gets only a debug log):

1. `hermes config set skills.external_dirs '["~/<clone>/skills"]'`
2. Prove it resolves: `hermes skills list` must show `Source=external`.
3. Promote local-only work FIRST: copy the newer file, plus any support file it
   references — a promoted SKILL.md whose `references/` file stayed behind is a
   dangling link.
4. Back up, then delete only the local copies of locally-authored skills. Bundled
   and hub-installed skills stay — they are not ours to hold. **Assert each target
   exists before removing it** (`[ -d "$d" ] || { echo "MISSING $d"; bad=1; }`) and
   assert the count afterwards: `rm -rf` exits 0 on a path that is not there, so a
   loop pointed at the wrong root deletes nothing and prints a success line per item.
5. Re-verify; the count must not drop. A skill missing afterwards may be
   platform-filtered (`platforms: [linux]` on Windows) — read the frontmatter
   before calling it lost.

**Renaming the clone is a config change on every machine, in that machine's own path
form.** One mount has two literals — `/home/<user>/projects/<repo>/skills` to the host
that owns it, `//wsl.localhost/<distro>/home/<user>/.../skills` to a client — so a rename
is two edits, and a missed one is skipped silently exactly like a wrong path at setup. Back
both config files up, replace the string, then prove it by **name-set diff**: read the
catalog's skill names and diff them against the loader's list. A count can match while two
skills swapped places, and the loader's table truncates long names, so grepping for one name
proves nothing either way.

- **LF only.** `.gitattributes` sets `eol=lf`, and a CRLF shebang fails on Linux
  and WSL2 with `bad interpreter ...^M`. `Path.write_text()` translates `\n` to
  `os.linesep`, so a generator emits CRLF on Windows unless it passes
  `newline="\n"` — the same inputs must produce the same bytes everywhere.
- **Edit the repo, not the mount.** The mount is a reference, so a change made
  through it lands in the repo — but it is also *found* there by any other writer,
  so treat the mounted tree as shared state and check `git status` before trusting it.
- **Verify the working tree, not the index.** Git stores LF under `eol=lf` while a
  Windows checkout can still hold CRLF, and the working tree is what the agent
  reads through the mount. `git add` therefore warns "CRLF will be replaced by LF"
  and normalises the **blob only** — the file on disk keeps its CRLF, so a gate that
  reads the working tree still fails and the warning reads as a fix. Normalise by
  **content, not by extension**: an allowlist of `.md/.sh/.py/.json` misses `.vbs`,
  `.service`, `.toml` and a shebang-less template, and each miss is one more gate
  round-trip. Re-scan the working tree after staging instead of trusting the warning.

## Host scope is a label, not a directory

A library that runs anywhere still holds members that only make sense inside one host. Keep them in
their subject category and *label* them — a `skills/<host>/` directory costs the subject grouping
and teaches nothing, while an unlabelled host-bound skill makes the whole library look host-bound.

- **Declare it once, in frontmatter:** `targets: [<host>]`. Absence means host-neutral, which is the
  default and needs no field, so the label is additive and a neutral skill stays untouched.
- **List every labelled skill in one README table** with what ties it to that host. The table is the
  half a human reads; the frontmatter is the half a loader can.
- **Enforce both directions, or the label rots.** A name prefixed with a host (`<host>-*`) must
  declare that host, or a rename silently produces an unlabelled host-bound skill; and a table row
  whose skill declares nothing must fail, or the table stops describing the tree.
- **Do not genericise what is a mechanism.** A skill whose procedure drives that host's own
  internals — its profile store, its server, its process wrapper — cannot be made neutral without
  deleting the procedure, so the honest result is the label, stated per skill rather than implied.
  **Then prove the label changed nothing else:** `git show --stat` over the labelled files should
  read one insertion each, which turns "works identically" from a claim into a check.

## Step 9 — Take skills from an external source

Intake is a different entry point from auditing your own library: the question is
*which* of someone else's skills to adopt. Full procedure in
`references/external-sources.md`.

**Read the library's own decision record before you open a candidate.** A source that
was evaluated before has a ledger — a table of what was taken, a table of what was
refused and why — and, for a source mined as a design document, an ADR per pass. Read
it first. On a library with three prior passes over one repository, every candidate in
the current batch had already been adjudicated, and half were refusals whose reason had
to be either honoured or overturned in writing; evaluating them cold re-litigates
decisions and reaches a different answer than the tree already holds.

That record is often **machine-checked**, and that decides how you may edit it: a test
resolves every `taken` row against a real skill and every `rejected` row against the
absence of one. Overturning a refusal therefore means **moving the row** between the
tables and stating why the old reason no longer holds — never adding the skill while
leaving the refusal standing, and never deleting the refusal quietly. "Refused because
the bundled skill covers it" is a claim about the bundled skill, so check it before
overturning; two refusals read that way, and neither bundled skill covered the subject.

1. **Read the truth, not the landing page.** Fetch the repo tree and the raw
   `SKILL.md` files; judge by the body. A marketing page describes intent.
2. **Determine sync semantics before recommending adoption.** A source that copies
   files in is a snapshot you own; a managed plugin updates itself and is
   unreviewed code running with the agent's permissions. Say which it is.
3. **Redundancy-check against the installed library** first, using the Step 3
   owning-token search on the candidate's vocabulary. Most of a mature library will
   already be covered.

   **A subject already bought from another source is a merge, not a second skill.** When
   a new source covers ground an earlier intake already paid for — four test skills, one
   of them the same subject as a reference file adopted a pass earlier — the deliverable
   is the delta: move the rules the existing owner lacks into it, point the new source at
   that owner, and record the source as contributing to an existing file rather than as
   refused skills. **Zero new skills is a legitimate intake result** and belongs in the
   report as the finding; the failure mode is one skill per source, which is how a library
   ends up with four answers to one question.
4. **Prefer the original over an aggregator's copy.** A third-hand file cannot be
   diffed against its source and cannot take upstream fixes.
5. **Adapt, never copy** — local description ceiling, host-specific frontmatter
   dropped, upstream-only dependencies replaced with self-contained defaults, shell
   prose replaced with the host's tool names, and the source revision pinned in
   `metadata.hermes.source`.
6. **Record the rejections** in a file, with the reason and the skill that already
   covers each. That is what stops the next session re-evaluating the same list.
7. **Reference it, do not vendor it, unless you rewrote it.** A skill you did not
   adapt stays upstream-owned: register the source and install it, so `hermes skills
   update` maintains it. Vendoring an unmodified external skill into your own repo
   gives one file two owners and makes `hermes skills diff` / `reset` meaningless.
   The command surface and the identifier pitfalls are in
   `references/external-sources.md` §7.

   **This is the standing policy for this library, not a preference to weigh per
   case:** the repo holds skills we authored or genuinely adapted; everything upstream
   is registered as a source and installed, so its owner keeps maintaining it. Treat
   "I don't want to maintain this myself" as an instruction to reference, not vendor —
   and when a skill is already vendored that way, say so rather than leaving it.

### Price the pack before taking any of it

An external pack's descriptions are injected before any tool call, so the aggregate
frontmatter is the recurring cost of importing it — and it is the number nobody quotes.

- **Sum the descriptions.** `awk '/^description:/ {sub(/^description:[ ]*/, ""); t += length($0)}
  END {print t}' skills/*/SKILL.md`, ÷4 for tokens. Measured: a 153-skill pack carried ~53k
  characters ≈ 13k tokens of index. Compare against the library's own total before calling
  a pack "free to install".
- **Count collisions by family, not by name.** Grep the candidate's skill list for the
  library's dominant families (review, quality, delegation, ops). Eleven review-family
  skills in one pack compete with the single review owner for the same trigger words, and
  the router cannot know which one is measured.
- **Check the ownership model against Step 8.** A pack that copies into `$HERMES_HOME/skills`
  and polices edits to its "managed" copies is the opposite of the mounted-repo model.
  Running both gives one namespace two owners; say which model wins before installing.

### A source that is mostly a trigger table is a router

Some sources are an operating system rather than a skill pack: one `SKILL.md` holding a
trigger table, an autonomy policy and a reply contract, pointing at dozens of micro-skills and
playbooks. Take the leaves and refuse the frame.

- **Refuse the router.** This library already routes per skill through `description` and
  `## When to Use`; a second index duplicates every trigger and adds a hop.
- **Refuse the micro-skill split.** One rule per file reads pure and costs an index line and a
  load decision each. Adopt the rule, not the packaging.
- **Refuse host-specific frontmatter** (an invocation switch, `icon`, `color`) and any policy
  that restates the system prompt: autonomy, sycophancy, pause rules.
- **Take the leaves the library lacks, into their owners.** Owning-token search first, so a
  rule that already has an owner gets a pointer at most. A rule with no owner becomes a short
  section in the skill that owns its subject, not a new skill.
- **Record the refusals by class**, per item 6 above: router, split, fields, duplication.

## Step 10 — Mine a repository as a design document, then retire it

The source is not a skill pack here, it is a whole tree of rules, review standards and
incident write-ups. The transferable artifact is usually the **rule format**, not the rules:
a statement of *what must hold, the defect it prevents, the check that can fail, and the
boundary past which it does not apply* survives translation into another language and
another harness. The instances do not, and porting them produces a document about someone
else's codebase.

1. **Triage by size before reading.**
   `find . -name '*.md' -not -path './.git/*' | xargs wc -l | sort -n`. The small files are
   usually the decisive ones — the review standard, the testing policy, the postmortems; the
   largest is often generated (a config catalog, a module graph) and yields nothing a summary
   would not.
2. **Read the enforcement documents, not the marketing.** The agent instructions, the review
   skill, the incident postmortems and the defensive-pattern pages state what the project
   actually requires. A README states intent.
3. **Sort every candidate into adopted or refused, and write the refusals down** with the
   cost that made each a refusal. A decision record is the cheapest home: what was taken,
   what was not, and why. Without it the next session re-evaluates the same list and
   reaches a different answer.
4. **Port into the skill that already owns the subject**, not into one new skill per source.
   A rule about proving acceptance belongs in the acceptance skill; a bug class belongs in
   the review skill. A new umbrella only when the source supplies a class nothing covers.
5. **Say which rules have no seam in your harness**, and what implementing them would cost.
   A mapping table asserting a mechanism that does not exist is worse than an empty section,
   because the next session builds on it.
6. **Retire the source only after proving its content exists elsewhere.**

### Proving a directory's content before deleting it

```sh
# Per DIRECTORY: a clone is re-clonable, an untracked snapshot is not.
git -C "$D" remote -v
git -C "$D" rev-list --left-right --count origin/HEAD...HEAD

# Per FILE: compare against the counterpart path, not the basename.
for f in $(cd "$A" && find . -type f -not -path './.git/*'); do
  cmp -s "$A/$f" "$B/$f" || echo "UNIQUE $f"
done | tee /tmp/unique.txt
```

- **Check the remote per directory, never by project name.** A clean clone of a published
  repo and an untracked snapshot of the same project sit side by side under near-identical
  names, and only the first is recoverable.
- **Compare against the flattened counterpart.** A snapshot often drops a repo's layout
  (`docs/x.md` becomes `x.md`), so a basename comparison reports every file as unique and
  hides that all of them match.
- **A count is the verdict, a resemblance is not.** "356 files byte-identical, 21 present
  only here, and all 21 match their counterpart under `docs/`" is evidence; "looks like a
  copy of the clone" is a guess with a file listing behind it.
- **Confirm an irreversible delete in full sentences, naming which directories are
  recoverable and which are not**, before running it.

### Retiring a product line, not just a directory

Abandoning a project is a remote operation as much as a local one, and stopping halfway leaves
the retired line alive under another name.

- **Settle the shape first: step 8's ancestry check decides it.** If `git merge-base
  --is-ancestor origin/<old-default> <new-line>` fails, the two lines cannot be merged at all —
  the operation is a replacement, not a merge, and saying so once beats discovering it half way
  through.
- **Change the default branch before deleting it.** `gh api -X PATCH repos/<owner>/<repo> -f
  default_branch=<new>` first; deleting the default branch otherwise leaves the repository
  pointing at something that no longer exists. Then delete, and verify the branch list from the
  API rather than from the push's exit status.
- **Tags keep a retired line reachable.** Deleting the branch is not enough: release tags still
  resolve, still list in the UI, and still let anyone check out the abandoned code. Delete them
  in the same operation and count before and after.
- **A clone of the retired line can hold the successor's own early commits.** Compare *branch
  tips* against the successor's object store — `git -C <successor> cat-file -e <sha>` — not
  files, and not merely the successor's default branch. A rewrite is often developed as
  branches inside the repository it replaces before it gets a fresh history, so those commits
  exist in neither the old remote nor the new repo, and deleting the clone destroys them.
- **Bundle before deleting a line.** `git bundle create <file> --branches --tags`, then
  `git bundle verify <file>` — the "records a complete history" line is the proof, and one
  file makes the delete reversible. Report its path and say plainly that it is the last copy.
  **Verify from inside a repository, while the source still exists:** `git bundle verify` needs
  one, and a verify run against the bundle itself after the clone is gone fails with "need a
  repository to verify a bundle" — a scare that costs a session its confidence at the worst
  moment. `git bundle list-heads <file>` works anywhere, so use it for the later re-checks.

## Step 11 — Encode a repeated rule as a check

When you catch yourself writing the same instruction a second time, the instruction is the
symptom. Encode it once as a lint, a manifest flag, a runtime check, or a script, and delete the
prose copies. A rule that needs judgement cannot be encoded, and then the fix is to make the one
statement more prominent and add the failure mode beside it, not to add a third place it is
stated.
*Check:* the second statement of a rule either became a check or is a pointer to the owner.
*Boundary:* a check that cannot fail is worse than prose. Prove it fires before trusting it.

### Two engines, one rule

When a gate has to run in more than one environment — an evaluator tier and a bare checkout,
a CI image and a developer's laptop — move the rules into the engine that runs everywhere and
have the other **call it**. Two implementations of one rule drift, and the drift is invisible
because each gate is green in its own environment.

- **Port the negative control with the rule.** A rule moved without the test that watches it
  fail is a rewrite that proves nothing, and a port is exactly where coverage disappears
  while the count of checks looks unchanged.
- **Expect to give up the better diagnostics.** An evaluator that names both values beats a
  script's one-line message; record that cost in the decision log rather than claiming
  nothing changed.
- **A checker that reads through a newline-translating reader cannot detect CRLF.**
  `Path.read_text()` turns `\r\n` into `\n`, so the rule passes on every file it exists to
  catch. Read bytes for that rule, and build the negative-control fixture with
  `newline=""` or the fixture normalises the defect away before the check sees it.

## Pitfalls

- **Editing a bundled skill.** Hash-tracked and refreshed; the change disappears.
  Identify the class first (Step 1).
- **Editing the installed copy of a repo-sourced skill.** Overwritten on the next
  sync, with no error and no backup — edit the repo source and re-run the sync. The
  copy is also where an *unattended* writer (the background review, another agent)
  lands a lesson, so a sync you run can delete someone else's fix: diff the copy
  against the repo before syncing and port anything that exists only in the copy back
  into the generator first. A lesson that survives only in a copy has no home.
- **Deleting a copy before confirming the owner still states the rule.** Verify the
owning skill has it whole *before* removing the duplicate, or the rule is lost.
- **Deleting content something reads.** Grep tests, scripts and docs for a
  distinctive string from the block before removing it.
- **A same-word collision is not a citation, and an earlier session's note is not
  evidence.** "Unreferenced" has to be re-derived against the *tracked* tree for the
  exact identifier, then each hit read: a 29 MB corpus directory was nearly kept
  because a handoff note recorded that committed run reports cited it, and every hit
  was the ordinary word — `<tool> calibrate --build-eval /tmp/ladder` names a graded
  eval ladder built at runtime, not that directory. A note from a previous session is
  a claim to check, not a finding.
- **Regenerable is deletable; shared bookkeeping is not.** Caches (`__pycache__`,
  `.mypy_cache`, `.pytest_cache`, `.ruff_cache`), run output and tool temp dirs come
  back on demand, so delete them without ceremony. An append-only ledger or the tool's
  own process records is not yours to falsify — leave it, and say that you did.
- **A `## References` section promising a file that was never written.** Distinct
  from a bad `related_skills` entry: the skill cites `references/<topic>.md` (often
twice, so it looks load-bearing) and the file does not exist. Found twice in one
pass over a 34-skill library. Fix by removing the pointer — **do not invent the
content** — and say plainly that the missing depth is a real gap worth writing.
  Detect with the audit script's `dead_refs`; ignore its false positives from
  command arguments (`<url>`, `link` placeholders) by reading each hit.
- **Your own prose can create a dead reference.** A backticked path is read as a pointer
  whether or not you meant one, so an explanatory sentence naming a file *class* —
  a `scripts/` glob, a `references/` placeholder — trips a repo's dead-reference test. The usual
  escape is a write verb on the line (`write`, `create`, `add`), and it does not match
  "written": name the directory (`scripts/`) or lead with the verb. The escape cuts both
  ways — a genuine dead pointer on a line that happens to say "add" is silently skipped, so
  neither a pass nor a failure from that test is evidence until you have read the line.
  **A path being transformed is an illustration, not a pointer.** Teaching a string-handling trap
  means writing the bad path literally — `lstrip("./")` strips characters, so `../a.py` becomes
  `a.py` — and a bare backticked `../…` matches the escape detector, naming no file the skill
  expects to have. Do not delete the example to make the gate green: a correct illustration is the
  content. Teach the check that a line showing a transformation (`becomes`, `turns into`, `->`, `→`)
  is describing a value, not referencing a file, and pin it with the illustration itself.
  **Exempt placeholders in every rule that parses a path, not just in the one that flagged you** —
  `../…`, `../<name>` and `../*` name no file. A checker whose reference rule skips `<`/`>` but
  whose escape rule does not will flag the very sentence that documents the exemption, and the
  tempting repair is to delete a correct example: give both loops the same placeholder test instead.
  Treat `*`, `?` and `[` as path metacharacters in **every** rule, not only in the placeholder
  test: a glob names a class of files and cannot be dereferenced, so a rule that skips `<`/`>`
  alone reports `scripts/*.sh` — a glob in ordinary prose — as a dead pointer.
- **A cross-skill pointer written as a path is itself a dead reference.** Paths resolve
  against the *naming* skill's own directory, so `<tool>/scripts/install_bots.py` cited from
  another skill names a path that does not exist under it — and repairing one dead reference
  this way creates the next. Write `install_bots.py` in `<tool>`: skill plus filename, never a
  relative path.
- **Declaring a suite absent from a one-level glob.** `ls tests/*.py` returns nothing when the
  tests live in `tests/unit/`, and the next step is a hand-built harness that proves less than
  the repo's own gate. Enumerate with `find tests -name 'test_*.py'` and read the runner before
  writing a check of your own.
- **A CLI verb a skill teaches that the tool does not have.** `hermes pm install` reads like
every command around it and fails only when a reader runs it. Extract every `hermes <verb>` the
tree names, diff the set against `hermes --help`, and read each miss: prose like "hermes is…"
is a false positive, a command in a code block is a dead instruction — unless the dispatch
table registers it as a hidden or dev verb, which `--help` never lists, so read the table
before calling it dead. Replace it with the verb that exists (`hermes update`), then re-grep
for the retired string.
- **Descriptions over 60 characters.** The window and its cost belong to
  `hermes-agent-skill-authoring` (the index truncates); past it, a trigger never fires.
- **`related_skills` naming a skill that does not exist** in the scanned tree — a
  dead reference the reader cannot follow.
- **A drift check that has never fired.** A `--check` reporting clean is
  indistinguishable from one that cannot detect anything. Perturb a mirrored file,
  confirm it names the path and exits non-zero, re-sync, confirm clean.
- **Validating a skill in isolation.** A validator that resolves `related_skills`
  against the tree it was handed reports every sibling as unresolved when pointed
  at a single skill directory. Point it at the library root; a lone failure is only
  real when the whole tree agrees.
- **A duplicate name never merges — the nearest layer wins outright** (project > custom >
  user > bundled), and identity is exact: a typo resolves to nothing, not to a similar
  skill. Name the winner per collision instead of assuming a blend.
- **Grepping `hermes skills list` and concluding a skill is missing.** The table
truncates long names (`nix-declarative…`), so a grep for the full name returns
nothing while the skill is present and loading — a false negative that reads as
"the mount did not take". Read the Source column with the table rendered wide
(`COLUMNS=200`), or better, ask `skill_view(name)` and read its `_source_path`:
that names the exact file the resolver chose, which is the only authoritative
answer to "which copy is in play" when a local copy could be shadowing the mount.
- **Reading a check's result through a pipe.** `cmd | tail` reports the *pipe's*
  exit status, not the command's, so a failing check looks like it passed. Check
  `$?` on the command itself, or redirect to a file and inspect that. `tail -N`
  also hides earlier output: a command that prints one summary line per item, read
  from its last line, looks like the earlier items were skipped and gets reported
  as a defect. `grep` the summary lines instead of tailing a fixed count.
- **`rm -rf` on a directory you assumed was a clone.** Run `git remote -v` *in that
  directory*: a clean clone and an untracked snapshot of the same project can sit side by
  side, and only the first comes back. Step 10 has the per-file comparison that proves
  nothing unique is lost.
- **Treating a secret-scanner's own pattern as a finding.** A probe that detects a
  private-key header contains that literal, so a naive grep over the tree flags the
  detector itself. Audit each hit by reading it: a token-shaped placeholder in
  documentation (a short example, well under real credential length) is not a
  credential. Never block or clear a publish on a raw hit count.

## Verification

- [ ] Every edited skill is locally authored (not bundled / hub-installed)
- [ ] Repo-sourced skills edited at the source and re-synced; drift check passes
- [ ] Drift check proven to fire: perturb a file, see it reported, re-sync, see clean
- [ ] No local copy shadows a mounted skill — `hermes skills list` shows
      `Source=external`, not `local`, for every repo-owned skill
- [ ] No locally-authored skill remains only on a profile: promoted, or reported with the
      reason it is not ours; a name collision kept the newer copy and ported the loser's
      unique content into it before deleting
- [ ] A bulk delete asserted every target existed and checked the count afterwards, not
      the exit status of `rm -rf`
- [ ] No text file in the repo is CRLF, and every generator pins `newline="\n"`
- [ ] Each cross-cutting rule has exactly one owner; others point to it
- [ ] No skill contradicts the code or another skill
- [ ] `validate-skills.py` passes on every touched file, and the target repo's own gate ran
      (its command and its output quoted), not a sibling repo's checklist
- [ ] Removed-lines diff reviewed: no substantive rule dropped
- [ ] Originals backed up and the change committed or otherwise recorded
- [ ] External skills adapted to local conventions, source revision pinned, and the
      sync semantics (snapshot vs subscribed) stated
- [ ] Rejected candidates recorded with a reason and the skill that already covers them;
      a refusal is overturned by moving the row and stating why, not by adding the skill
- [ ] A mined source is retired only after a per-file byte comparison against the copy
      kept, and only after confirming which directories have a remote; branch tips were checked
      against the successor's object store, and a line existing only locally was bundled first
- [ ] A retired product line lost its old default branch *after* the new one was made default,
      and its release tags went with the branch
- [ ] Any secret-scan hits audited by reading them, not by count
- [ ] A claim that a skill improves outcomes is backed by an arm/control run with a
      pre-registered negative and positive control, or is labelled unproven
