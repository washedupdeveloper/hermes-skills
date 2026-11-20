# Session vantage: auditing prose for leaked reasoning

Chain-of-thought leakage is prose whose **vantage is the authoring session rather than the
repository**. It cites an artifact only that session could see, narrates the change instead
of the state, or argues with a reviewer who has left. It is the most common form of prose
that passes a spell-check and fails a reader at `HEAD`.

Adapted from DeepSeek Harness's `dsh-trim-cot-leakage`
(`deepseek-harness@39163dd30f703a79079e2d2446545cff3c453738`), which earned it by running
a purge over a large repository three times and finding cases by reading, not by pattern.

## The one test

> **Could a reader at `HEAD`, with no access to any session transcript, PR thread or
> uncommitted draft, resolve every reference and verify every claim?**

If no → restate the surviving facts from the repository's vantage and delete the rest.

If yes → it is not leakage, however historical it sounds. But resolvability only clears
*this* bar: on current-state surfaces (READMEs, docs, API docs) a resolvable change story is
still change narration, and class 3 below applies.

## Taxonomy

1. **Dead design-session citations** — `(decision 7)`, `(audit C2)`, `design §4.7`,
   `plan §1.4`, phase labels (`T4`, `W3`, `P-I`), "the design ledger". If the decision has a
   committed owner, cite it **by name and path**; otherwise delete the citation and restate
   its factual clause so it stands alone.
2. **Stack and PR vantage** — "a later PR in this stack", "this PR adds", "the previous
   commit". State the shipped mechanism or the extension point; deferred work becomes a
   `TODO` with an issue reference.
3. **Change narration and version stamps** — "used to", "no longer", "the old X", and
   indexical stamps ("v1", "this cut", "today", "now" contrasting with a past state). State
   the present behaviour. A fixed regression becomes a present-tense counterfactual —
   "without X, Y happens" — never "it used to Y".
4. **Review choreography** — "Rejected in review:", "the reviewer confirmed", draft ordinals
   ("v5 of this note"), round attributions. Keep the decision and the rationale as plain
   fact; delete who said it and when.
5. **Reviewer-addressed justification** — "the cast is safe — it simply…", "this is correct
   because…". A comment arguing its own correctness addresses a reviewer, not a maintainer.
   State the invariant that makes the code safe, or delete the comment if the code shows it.
6. **Restatement and derivation transcripts** — control-flow narration ("first we X, then we
   Y"), test walkthroughs, proofs of obvious branches. Delete; keep only a non-obvious
   contract or invariant.
7. **Hedges and planning residue** — "probably fine for now", "should be enough", deferrals
   with no marker. Promote to `TODO`/`FIXME`, or restate the actual bound; delete the hedge.
8. **Authoring-language slips** — an untranslated working fragment in prose that is otherwise
   in another language, or a private separator left in a public document. Translate or
   delete.

## What is not leakage

An unaided purge fails in **both** directions: it deletes durable references and keeps dead
ones. Apply these keeps as written.

- **Issue references** — `#1470`, `TODO(name):`, "issue #N owns the follow-up" resolve at
  `HEAD`; keep them on any surface.
- **Suppression justifications** — `# noqa` reasons, lint-disable comments, coverage-ignore
  reasons, empty-catch explanations are *required* prose. Fix a false reason; never delete
  one.
- **Counterfactual-present regression pins** — "without X, Y happens", "a naive X would…".
- **Measured bounds** — `(measured: 512 nests ≈ 0.15s)` calibrating a constant. The word
  "measured" is load-bearing.
- **Runtime old/new states** — "the old connection drains before the new one accepts" is
  runtime lifecycle, not change history.
- **External references that resolve outside the repository by design** — a standard's
  section number (RFC 9110 §10.1.5), an upstream API name. The §-ban covers uncommitted
  internal drafts, not external specifications or committed docs that own their numbering.
- **Project voice** — "we" as the project's voice, and a decision record's
  "Alternatives considered" section.
- **A decision record's own history — while its subject exists.** An ADR, a postmortem or an
  agent note *is* the change story; that is its artifact, and a record explaining a rule the
  repository still follows is kept whole. The exemption ends with its subject: an ADR whose
  subject has been removed preserves a name, a project and a history nobody can act on, so it is
  deleted alongside the thing it described. Deleting it is half the job — then sweep for the
  assertions still pointing at the absent thing (a `related_skills` entry, a spec requirement,
  prose deferring detail to it). A removal is complete when a grep for the name finds only
  worked examples.

## Workflow

1. **Require an explicit scope.** "Audit the docs" is not a scope; name the directories. Do
   not touch vendored trees, archives, or recorded fixtures — a fixture is a derivative:
   change the owning source or scenario and regenerate.
2. **Audit read-only first.** Use `search_files` for the class markers above, calibrate each
   probe against a known positive and a near-miss negative before trusting its output, then
   **judge every hit semantically**. The patterns are probes, not the definition: every
   review round of the original purge found cases the batteries missed. Also read the densest
   prose in scope — module docstrings, READMEs, design notes — without a pattern in hand.
3. **Fix owner-first, per surface.** A generated page → fix the source it was generated from
   and regenerate; a copied block → fix the copy's owner, then re-copy. Fixing the derivative
   alone is a change the next build deletes.
4. **Before deleting, enumerate the passage's propositions** and check the overcorrection
   traps: a trim that flips an obligation into an endorsement, promotes a hypothetical to a
   shipped feature, deletes a true fact, or drops the evidence source.
5. **Verify by re-running the probes**, expecting only the sanctioned keeps plus the
   document that owns this taxonomy. Confirm every remaining citation resolves at `HEAD`.

## Overcorrection traps

| Trim | What it loses |
|---|---|
| Deleting "must not" from a sentence about a removed check | The obligation survives the check |
| Deleting a caveat because it reads like a hedge | The bound it stated |
| Deleting a `@see`-style pointer because it names a decided-against option | The reason nobody re-proposes it |
| Rewriting a measured number to "fast" | The evidence word |
| Deleting a suppression's reason to shorten the line | The next reader removes the suppression |