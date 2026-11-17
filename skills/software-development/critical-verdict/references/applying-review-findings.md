# Applying a review's findings

A review produces findings; someone has to act on them. The failure mode is treating the
review as an instruction set. Every finding is a claim about the artifact, and every
prescribed remedy is a **second** claim about the fix — verify them separately.

## 1. Verify each claim before editing anything

- Read the claim *and* the check the reviewer proposed, then confirm the claim against
the artifact. A finding can be real but located at the wrong line, or real but already
fixed since the review ran.
- **Confirm runtime claims on the running system, not from the configuration.** A config
that declares a firewall, a listener, or a user says what was *asked for*; the unit's
state, the listening sockets, the live addresses, and the evaluated option say what is
*true*. A large share of findings in a typical batch are about exactly that gap.
- Where a claim is about a relationship between two files, read both. Doc-accuracy
findings especially: the prose is wrong relative to a mechanism that has moved.

## 2. Test the prescribed remedy before applying it

- A remedy is a claim. Run it — in a scratch dir, on a copy, or against the extracted
fragment — and confirm it produces the stated result.
- A remedy that does not work is worse than the open finding: it converts a true
diagnosis into a new defect, under the authority of the review that produced it. When
it fails, find the working alternative and report both halves.
- **Prefer the fix that removes the class of the defect over the one that satisfies the
check.** If a better mechanism exists than the one proposed, use the mechanism and say
why.
- A finding can reveal something the review did not name. Fixing it honestly may expose
an adjacent defect that is worse than the original; repair it and report it rather than
passing it over.
- When a finding says a model is wrong, **fix the model, not only the prose.** A comment
corrected to match a stale diagram leaves the diagram wrong.

## 3. Edit with an assertion-checked script, preserving repo invariants

- One script that replaces exact multi-line blocks and dies unless the match count is
exactly 1. A silent no-match is the failure mode of an in-place edit.
- Re-assert any repo-wide invariant the edit could break — line endings above all. Read
the bytes before and after (`b"\r\n" not in data`); an editor or a formatter can
introduce CRLF on an LF-only repo, and `git status` will not show it when
`.gitattributes` normalises on comparison.
- Run the formatter and confirm it changed **nothing** in your files. A formatter that
reformats your edit means the diff no longer separates your change from pre-existing
drift.

## 4. Prove the change; do not assert it

- Run the repo's own gate **with building enabled**. An invocation that only evaluates
reports success while the builders that would fail never run.
- **Extract the changed fragment verbatim and run it.** For a script embedded in a
config file, pull the exact text out with an anchored range and execute it with the
declared inputs. That tests the text that will actually run, not a transcription of it —
and it is how a defect the review never named gets found.
- Read back each option you changed with the evaluator and show the value moved. A green
build does not prove an option took effect.
- Inspect the regenerated artifact, not just the exit code. A rendered output, a
diagram, or a generated file is the evidence that the model changed.
- **Re-run the gate after the last edit.** A green run that predates a later edit proves
nothing about what shipped.

## 5. Report per finding, and leave the commit to the owner

- Table the findings with a verdict each: real or not, and what was done. Say when a
finding was rejected, and why.
- **Lead with anything the review got wrong**, including its remedies — that is the part
the reader cannot get from the findings themselves.
- **Do not commit to someone else's repository unless asked.** Leave the tree dirty, say
so, and name the revision the change sits on.
- Report unrelated hazards noticed in passing as their own line — an untracked artifact a
`git add -A` would sweep in, a file missing from `.gitignore`. They are not part of the
change, but they are cheap to mention and expensive to discover later.
