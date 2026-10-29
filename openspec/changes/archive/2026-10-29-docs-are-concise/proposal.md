# Proposal

## Why

The prose had grown by accretion: a README that narrated its own history, an `AGENTS.md` whose
first sentence called the mount read-only while rule 4 said the opposite, a milestone document
carrying a 26-line log of closed defects, and an upstream record that said "five of its skills were
taken" and then listed eight.

The comments had the same problem — 118 comment lines in `ci.yml`, four of which said the same thing
about `permissions`, and a paragraph explaining why a job exists twice over.

## What Changes

- README 293 → 214 lines; AGENTS 108 → 80; milestone 103 → 62; upstream 188 → 123.
- Accuracy, not only length: the mount is described as readable-not-protected everywhere; the caveman
  source is credited with eight skills, not five; the description ceiling is 57 characters, which is
  what the gate enforces; the milestone's CI row states no count it cannot derive.
- `ci.yml` comments 118 → 78 lines, and two defects fixed: the comment describing the **specs** gate
  had ended up above the `cost` job when that job was inserted, and `openspec` was the only job with
  no `permissions:` block, so it inherited the workflow-level `{}`.
- Every string `claim-audit` parses is preserved verbatim; the audit still reads the same five claims
  out of the README.

## Capabilities

No behaviour change: documentation and comments only. `skip_specs: true`.

## Impact

README.md, AGENTS.md, docs/milestone.md, docs/upstream.md, `.github/workflows/ci.yml` (comments and
one permission block).
