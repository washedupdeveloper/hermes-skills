# Proof-carrying claims

A verdict that rests on prose is an opinion with a score attached. This file is the shape that
replaces prose with a check the gate re-runs: a closed vocabulary, a per-claim control, three
admission classes, and a third verdict state for claims that could not be settled.

Use it when designing the claim half of a gate — a code review, a compliance check, an audit that
must say "this is wrong" about an artifact — or when a reviewer's findings are being trusted
because nobody has asked what would falsify them.

## Three outcomes, no fourth

| Outcome | Means | What it may do |
|---|---|---|
| `supported` | the check passed | count as evidence; block only with a control |
| `refuted` | the check failed | drop the claim, and charge the producer in the metrics |
| `unrunnable` | the check could not run | keep the claim **open** — never a pass, never a failure |

`unrunnable` is the state that decides whether the whole design works. Fold it into `refuted` and a
missing browser certifies a web app; fold it into `supported` and a broken toolchain certifies
everything. It has its own reason string and its own place in the verdict.

## The vocabulary is data, and closed

One file declares every kind; the executor loads it and refuses a kind it does not find there; a
test asserts the two agree in both directions. A kind added in code only, or declared only, fails
the gate rather than failing at run time in an image.

| Kind | Proves | Refuses |
|---|---|---|
| `absent` | no file matches a pattern outside an exclude set (dead export, no call site) | an unbounded walk: over the file budget it is `unrunnable`, never truncated |
| `present` | a cited line exists and says what was claimed | the hallucinated citation — the highest-frequency false finding |
| `command` | a command's exit status or output (test fails, build breaks, analyzer hits) | any executable outside the project's toolchain or a script inside the repo |
| `dom` | a page, loaded headless, has or lacks an element | a missing driver: unproven, not "the app is broken" |
| `http` | a **loopback** endpoint answers as claimed | any non-loopback host — a proof that reaches the network is not reproducible |
| `json` | a value at an RFC 6901 pointer | a pointer-only claim with no expected value: that proves nothing |
| `diff` | a line is part of this change | a run with no base revision — unproven, not "inherited" |

Every parameter is typed and defaulted in the contract. An unknown key is `unrunnable`: a proof
must not accept a field its executor ignores, because that is how a reviewer adds a knob that does
nothing and believes it took effect.

**A kind whose executor can only return `unrunnable` is not a kind.** Shipping `dom` while the
image contains no browser made every such claim unprovable by construction: the vocabulary promised
a capability the artifact did not have, and the failure read as a property of the repository.
Either ship the capability — and measure its cost, a browser is ~600 MB in the image — or drop the
kind and let the claim be proven by a `command` that runs the project's own test. Assert
`set(PROOF_KINDS) == set(EXECUTORS)`, and delete a kind whose executor is a stub returning "not
implemented".

**`command` asks the toolchain a narrower question than "is this path inside it?"** A nix
`symlinkJoin` — the usual shape of a pinned analyzer set — makes `<prefix>/bin/gitleaks` a symlink
to `/nix/store/<hash>-gitleaks-8.30.1/bin/gitleaks`, which is *not* under `<prefix>`. An
`is_relative_to(prefix)` test therefore refuses every tool in a working toolchain, and the failure
arrives as `unrunnable` on an individual claim rather than as a configuration error. Ask the
inverse: does `<prefix>/bin/<name>` resolve to this executable? A bare name is allowed when
`which <name>` resolves to something the toolchain provides — and a hand-maintained allowlist of
analyzer names goes stale the first time one is added.

**Validation and execution must resolve a tool by the same rules.** Accepting a name in the
allowlist and then failing to *find* it produces the worst message in the system: an approved,
present, working analyzer reported as "not installed", and the claim left `unrunnable` for a reason
that is false. The usual cause is that resolution consults only an environment variable — a property
of the caller, not of the installation — so the same proof runs inside the shipped image and fails
outside it. Resolve the way the rest of the CLI resolves (its own toolchain resolver, cached), and
let the environment variable be the first candidate rather than the only one. Measured: six passes
proved a complexity defect with `ruff`; three came back "`ruff` is not installed" because the caller
had not exported the variable, and resolving through the CLI's own resolver took confirmation from
3/6 to 5/6 without touching the producer.

## Does the proof reach the claim?

A proof has two independent coordinates: the **subject** it examines and the **reach** of the check
it runs. Both have to cover the claim before any outcome means anything.

| kind | names a subject as | reach is | fails to reach when |
|---|---|---|---|
| `present` | `path` (+ line) | that file | the path differs from the claim's |
| `absent` | `include`/`exclude` patterns | every file matching include, minus exclude | the claimed path is excluded, or include does not cover it |
| `command` | the tree as cwd | whatever its arguments address | only its control can tell — leave it there |
| `json` | `path` + pointer | that file and node | the path differs |
| `diff` | `path` + line | that file's changes against a base | no base revision, or the path differs |
| `dom`, `http` | a selector / a loopback URL | that page or endpoint | the observation is about another target |

Demote to `unsettled` — never `refuted` — when a proof misses its claim's location: the claim may
still be true, it is simply not what was proven, and calling it false charges the producer for your
matcher. Record the reason with the excluded or uncovered path in it, so the reader sees which of
the two coordinates failed.

**Reach is necessary and not sufficient.** A proof can examine the right file and still not observe
the property claimed: an `absent` check that the symbol appears nowhere else says nothing about how
complex the function is, even though the file matches. When the kind cannot observe the class of
claim, the honest state is again `unsettled` — and the durable fix is in the prompt, naming which
kind measures which property, because a producer that is not told will keep reaching for the check
it finds easiest.

## What counts as the change

A `diff` proof is only as honest as the patch it reads, and `git diff <base>` is neither complete
nor stable by default.

- **Untracked files are part of the change.** `git diff` omits them, so a secret in a new file has
  no hunk, every `diff` proof about it is refuted, and the run passes. Measured: a critical finding
  at `new.py:1` produced `PASS` while `git status` showed `?? new.py`. Synthesize a new-file patch
  (`--- /dev/null`, `+++ b/<path>`, one `+` line per line) from
  `git ls-files --others --exclude-standard`; skip binary and oversized files **by recording
  them**, because silently dropping a large untracked file reintroduces the same pass; and exclude
  the tool's own state directory, or the second run reviews the first run's artefacts.
- **Pin the patch's shape.** `diff.dstPrefix`, `color.ui`, `diff.external` and `diff.noprefix` are
  user configuration, and a parser keyed on `+++ b/<path>` breaks under them: measured,
  `diff.dstPrefix=new/` turned every path into `new/a.py`, so a proof about `a.py` was refuted and
  a real defect passed. Invoke `git -c color.ui=false -c diff.srcPrefix=a/ -c diff.dstPrefix=b/
  diff --no-color --no-ext-diff <base>`.

## Merging samples: union the evidence

Several samples of one producer report the same defect with different proofs. Key the merge on the
location `(dimension, file, line)`, but keep **every** distinct proof and run them all: take the
highest severity for the label, and let **any** proof that holds settle the finding. Keeping only
the highest-severity sample's proof leaves the other claims unbacked — a claim can outlive the
evidence that was actually run — and one refuted proof then clears a defect another sample proved.
Measured: two samples, one refuted and one proven, is a proven finding.


## Wiring the states into the verdict

`certified` requires three things at once: the score clears its threshold, no blocking claim is
still standing, and **no blocking claim is unresolved**. Two of those look alike from a distance
because both are "not a pass", and keeping them apart is what makes the verdict useful:

| what remains | decision | next action for the reader |
|---|---|---|
| a `confirmed` blocking claim | `unsatisfied` | fix the defect |
| an `unsettled`/`unrunnable` blocking claim, nothing confirmed | `unprovable` | settle it: add a proof, install the tool, or waive it in writing |
| neither, score short | `unsatisfied` | raise the score |

Three mechanics keep this honest:

- **The partition must gate.** Splitting into `still_blocking` and `unresolved` and then computing
  `satisfied` from `still_blocking` alone certifies a run whose only blocking claims were
  unsettled — the unresolved list gets recorded, printed, and consulted by nothing. Measured, and
  it passed the obvious test because the fixture had no blocking claims at all.
- **The reason must survive alone.** When the score-and-blocking verdict was clean, the unresolved
  note *is* the reason; appending it to "aggregate >= threshold and no blocking findings" leaves a
  sentence that contradicts itself in the one line a reader quotes.
- **The mode belongs in the run's metadata.** The gate, the ladder and a manual re-run all
  recompute. Record `require_proof` (or its equivalent) where the harness records the other run
  facts and have each of them read it back, or an audit recomputes under the default and reports a
  mismatch that is really a mode difference.

A missing report is not a pass. With enforcement on and no adjudication file present, every
blocking claim is unresolved by definition — return them all as unsettled and let the run be
`unprovable`. An enforcement path that passes because its input is absent is a back door.

## Admission: the control is what makes a claim blockable

`adjudicate()` runs the proof, then the claim's **control** — a second proof the gate requires to be
refuted.

| Control result | Admission | May lower the score | May block |
|---|---|---|---|
| refuted | `proven` | yes | **yes** |
| supported | `control_did_not_fail` | no | no |
| unrunnable | `uncontrolled` | no | no |
| absent | `uncontrolled` | no | no |

`control_did_not_fail` is the vacuity detector: a check that supports the claim and its negation
alike has told you nothing. Keep the three admission classes separate from the three outcomes —
admission is a policy about consequences, outcome is a fact about execution.

## Teaching the producer to write one

A producer told to "attach a proof" writes *something*; whether it writes something usable depends
on which part of the instruction is pinned.

- **Pin the invariant, not the intent.** "The control is the same check applied where the claim is
  false" produced controls with the expectation flipped — `expect: zero` run against the clean tree
  — so every control passed and every claim came back `control_did_not_fail`. Restating it as *keep
  `expect` identical to the proof's and change only what it looks at* turned the same model on the
  same repository into 4 of 7 `proven`, both blocking claims included. A goal statement gets
  interpreted; an invariant gets followed.
- **Show one worked example per kind, side by side with its outcome** (`proof: … -> passes`,
  `control: … -> FAILS`). Structure is copied far more reliably than intent is reasoned about.
- **Say where the paths point.** A `command` proof runs with the repository as its working
  directory; a producer that writes absolute `/repo/app.py` arguments emits proofs that are
  `unrunnable` everywhere else.
- **A prompt is code.** Assembled with `.format()`, every literal brace is a substitution field — a
  JSON example pasted in unescaped raises at construction, and the failure lands as every
  prompt-dependent test failing at once. Escape the braces and keep one test that builds the prompt
  and asserts on its content.
- **Measure the settlement rate on a real producer turn, never on a fixture.** The number that
  decides whether the wording works is how many blocking claims come back `proven` in one run of the
  real model against a real repository; 0 of 5 then 4 of 7 is that signal, and no unit test can
  produce it.

### What actually comes back

The model does not always answer in the message body, and three transports break a strict parser:

- **A tool transcript.** The producer may write the JSON to a file and return the tool's output —
  `│ +{"sections": …}`. Parse the **first complete object** from the text
  (`JSONDecoder().raw_decode`), not `text[find("{"):rfind("}")]`: the last brace may belong to a
  second object and the slice then fails with "Extra data". The schema check after it is unchanged.
- **Literal control characters.** Multi-line claims arrive with unescaped newlines inside strings;
  `json.loads(..., strict=False)` accepts them, and the bytes are unambiguous.
- **Truncation.** A long answer is cut mid-string and no parser recovers it — cap what you ask for
  ("each claim under 160 characters"), and let a truncated sample fail as `unrunnable` rather than
  parsing a fragment into a finding nobody wrote.
- **Redaction.** An agent harness redacts credentials in the output (`AKIA…` → `***`), so a
  `present` proof that quotes the secret cannot round-trip: the string ends at `***` and the sample
  is unparseable. Never instruct the producer to echo a secret; cite the file and line and prove it
  with `diff`.
- **Keep what it said.** Store the raw answer on a failed sample (a few KB is enough). Without it,
  "not valid JSON" is the only diagnosis available, and the retry repeats the same defect.

## The verdict document

```yaml
verdict:
  sha: <exact identity the run was made from>
  claims:
    - id: C-014
      claim: "unused export `parse_scope`"
      severity: high
      proof: {kind: absent, pattern: "parse_scope\\(", exclude: ["src/scope.py"]}
      observed: {supported: true, control: refuted, artefact: <path>}
      admission: proven
  score: {aggregate: 88.4, threshold: 87.1141, from: admitted_claims}
  decision: certified | unsatisfied | unprovable
  termination: threshold_met | stalled | unprovable | budget
```

`decision: unprovable` is the state most gate designs lack. Without it, an unsettled blocking claim
silently becomes a lower score or an open finding, and the run reports a number instead of telling
the reader it cannot certify — which is the only sentence that helps them.

## Determinism checklist

- Recompute the gate inside the builder; a passed-in verdict is compared, never believed.
- Report the recomputed value, not the caller's — a summary that echoes the caller beside a
  recomputed judgement is the bug that survives review.
- Sort attempts numerically (`round-2` before `round-10`).
- Resolve the run root by walking to the marker file; accept any depth.
- Distinguish absent / unreadable / empty evidence with three reasons.
- No timestamps, no set iteration, no locale-dependent formatting in the payload.
- Assert byte-identical output across two builds of one tree.

## The exit contract for a pipeline

Strict by default (any blocked rung → non-zero), with an explicit opt-in to the rung a caller needs:

```bash
<tool> claims --run <dir> --require merge_ready
```

A caller that names its requirement gets exit 0 exactly when that rung is reached; a caller that
names nothing gets 1 on any block, so a partial ladder never reads as a pass. Both behaviours from
one flag, and the reasons stay in the text output rather than in the exit code.

## When the producer writes no control

A control the producer writes about its own check is a promise, and the producer often writes none
at all. Derive it from the proof instead:

| proof kind | synthesised control | what it establishes |
|---|---|---|
| `absent`, `present`, `command`, `json` (reads the tree) | the same check against the **base revision** | it discriminates *this change*: holds here, not there |
| `dom`, `http` (observes a running system) | same observation, **opposite expectation** | the observation can come out the other way |
| `diff` | same line, **opposite mode** (`added` ↔ `removed`) | the diff reading is not one-sided |

The base-revision control is the strong one, and it has a second use the fixed control never had: a
check that fails on both the branch and the base is evidence about the *repository*, not about the
change, and lands in `control_did_not_fail` — which is the right verdict, stated instead of missed.

Three mechanics decide whether it works:

- **Rebase the paths.** A `command` proof carries `["<repo>/check.sh"]`. Run verbatim against the
  base tree it executes the **defective** tree's script and proves nothing, while still returning a
  confident verdict. Rewrite every absolute path under the root into the base root; leave relative
  paths and anything outside the tree alone (a toolchain binary is not the project's).
- **Materialise the base with `git archive`, not a worktree.** The base tree must not carry `.git`,
  or a proof that runs `git` there answers questions about the wrong repository. Extract to a temp
  directory, pass it through the same adjudication entry point, delete it afterwards.
- **Never replace a control the producer did supply.** Synthesis fills a gap; it does not audit.
  Record which happened on every finding (`control_source`: `producer` vs `orchestrator:<shape>`),
  so a reader can tell a demonstrated control from an asserted one — the state is identical
  otherwise, which is exactly the ambiguity the control exists to remove.

With no base revision supplied, a tree-reading claim stays `uncontrolled` and its reason says so:
the absence of a control is not a control. Wire the base revision through the **CLI path the users
run**, not only the function — see the verification rule on flags that are parsed and never passed.

## Say these limits out loud

- **Not a sandbox.** `command` restricts *which* executables may run, not what a permitted one does.
  The reviewer already has the invoking user's access; pretending otherwise is worse than the gap.
  A default list that contains an interpreter (`python3`) or a build tool (`nix`) is a **trust
  list**, not a control: `python3 -c` executes anything, and `nix build` runs the flake — which is
  inside the diff under review. Removing one interpreter while keeping the build tool changes the
  spelling of the hole, not its size. Either call it a trust list in the docs, or run proofs in a
  real sandbox; do not let a default make it look like a boundary.
- **A producer-written control is trusted when it is offered.** Synthesis covers the four
  tree-reading kinds when a base revision is available; it does not audit a control the producer
  did write, and a vacuous one (an empty fixture) still reads as refuted. `control_source` on every
  record is what keeps the two distinguishable.
- **Score provenance is a separate decision.** Admitting proofs without moving the score off the
  producer's self-assigned number leaves the most consequential figure still taken on faith. That
  switch invalidates any calibrated threshold, so it is its own measured change — not a detail of
  wiring proofs in.
