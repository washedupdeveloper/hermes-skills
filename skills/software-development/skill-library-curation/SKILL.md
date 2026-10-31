---
name: skill-library-curation
description: "Curate the skill library: sourcing, overlap, conflicts."
version: 1.3.0
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
- **"Add this external skill" / "keep it updated" / "I don't want to maintain it
  myself"** — choosing which of a source's skills to adopt, and whether to
  reference it or vendor it (Step 9).
- **"Learn everything from this repository, then delete it"** — mining a foreign tree
  for rules rather than skills, then retiring the source safely (Step 10).
- **"Review this source's skills and tell me what is worth taking"** — decide by class
  rather than file (router, micro-skill split, host-specific fields, rules no owner here
  states), per Step 9's router subsection.

## Step 1 — Establish provenance before touching anything

Two classes of skill live under `$HERMES_HOME/skills/`, and they need **opposite**
treatment.

| Class | How to identify | Editable? |
|---|---|---|
| Bundled / hub-installed | listed in `.bundled_manifest` (`<name>:<hash>` per line) | **No** — refreshed periodically; edits are clobbered |
| Locally authored | every dir with a `SKILL.md` *not* in the manifest | Yes |

```bash
cd "$HERMES_HOME/skills"
for f in $(find . -name SKILL.md); do
  n=$(basename $(dirname "$f"))
  grep -q "^$n:" .bundled_manifest || echo "local: $n  ($f)"
 done
```

`.curator_ledger.jsonl` records an `actor` per change (`curator` / `agent`) — useful
for confirming who owns a skill.

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
library: the tuned 31-query set read 0.87 → 0.97, while 30 held-out queries read 0.57 → 0.63.
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

**Point the validator at every tree the loader sees, not just one.** `validate-skills.py`
resolves `related_skills` against the union of the roots it is given, so a repo-only run
reports every bundled sibling as unresolved and buries the real failures among false ones:
`validate-skills.py <repo>/skills "$HERMES_HOME/skills"`.

After a promotion, run the repo's own gate before touching any prose a test measures — a repo
that asserts its counts in tests fails on the addition and tells you the right numbers. **Stage
the new skill first.** A Nix check copies only git-visible paths, so an untracked `SKILL.md`
reads as absent: the counted total stays old and the README number you just corrected is
reported FALSE. `git add` the new directory, then gate.

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

Migrate a live library in this order, because a wrong path is skipped silently (a
non-existent entry gets only a debug log):

1. `hermes config set skills.external_dirs '["~/<clone>/skills"]'`
2. Prove it resolves: `hermes skills list` must show `Source=external`.
3. Promote local-only work FIRST: copy the newer file, plus any support file it
   references — a promoted SKILL.md whose `references/` file stayed behind is a
   dangling link.
4. Back up, then delete only the local copies of locally-authored skills. Bundled
   skills stay — they are Hermes's, refreshed by `hermes update`.
5. Re-verify; the count must not drop. A skill missing afterwards may be
   platform-filtered (`platforms: [linux]` on Windows) — read the frontmatter
   before calling it lost.

- **LF only.** `.gitattributes` sets `eol=lf`, and a CRLF shebang fails on Linux
  and WSL2 with `bad interpreter ...^M`. `Path.write_text()` translates `\n` to
  `os.linesep`, so a generator emits CRLF on Windows unless it passes
  `newline="\n"` — the same inputs must produce the same bytes everywhere.
- **Edit the repo, not the mount.** The mount is a reference, so a change made
  through it lands in the repo — but it is also *found* there by any other writer,
  so treat the mounted tree as shared state and check `git status` before trusting it.
- **Verify the working tree, not the index.** Git stores LF under `eol=lf` while a
  Windows checkout can still hold CRLF, and the working tree is what the agent
  reads through the mount.

## Step 9 — Take skills from an external source

Intake is a different entry point from auditing your own library: the question is
*which* of someone else's skills to adopt. Full procedure in
`references/external-sources.md`.

1. **Read the truth, not the landing page.** Fetch the repo tree and the raw
   `SKILL.md` files; judge by the body. A marketing page describes intent.
2. **Determine sync semantics before recommending adoption.** A source that copies
   files in is a snapshot you own; a managed plugin updates itself and is
   unreviewed code running with the agent's permissions. Say which it is.
3. **Redundancy-check against the installed library** first, using the Step 3
   owning-token search on the candidate's vocabulary. Most of a mature library will
   already be covered.
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

## Step 11 — Encode a repeated rule as a check

When you catch yourself writing the same instruction a second time, the instruction is the
symptom. Encode it once as a lint, a manifest flag, a runtime check, or a script, and delete the
prose copies. A rule that needs judgement cannot be encoded, and then the fix is to make the one
statement more prominent and add the failure mode beside it, not to add a third place it is
stated.
*Check:* the second statement of a rule either became a check or is a pointer to the owner.
*Boundary:* a check that cannot fail is worse than prose. Prove it fires before trusting it.

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
  was the ordinary word — `council calibrate --build-eval /tmp/ladder` names a graded
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
- **A cross-skill pointer written as a path is itself a dead reference.** Paths resolve
  against the *naming* skill's own directory, so `council/scripts/install_bots.py` cited from
  another skill names a path that does not exist under it — and repairing one dead reference
  this way creates the next. Write `install_bots.py` in `council`: skill plus filename, never a
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
  `$?` on the command itself, or redirect to a file and inspect that.
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
- [ ] No text file in the repo is CRLF, and every generator pins `newline="\n"`
- [ ] Each cross-cutting rule has exactly one owner; others point to it
- [ ] No skill contradicts the code or another skill
- [ ] `validate-skills.py` passes on every touched file
- [ ] Removed-lines diff reviewed: no substantive rule dropped
- [ ] Originals backed up and the change committed or otherwise recorded
- [ ] External skills adapted to local conventions, source revision pinned, and the
      sync semantics (snapshot vs subscribed) stated
- [ ] Rejected candidates recorded with a reason and the skill that already covers them
- [ ] A mined source is retired only after a per-file byte comparison against the copy
      kept, and only after confirming which directories have a remote
- [ ] Any secret-scan hits audited by reading them, not by count
