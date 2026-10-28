# Proposal

## Why

Three claims in the audit could not be settled by any clone, and one of them was not a limitation
at all — it quoted a README sentence that had already been rewritten out of the file:

    claim("README: that set is the one Hermes documents", ...)   # grep documents README.md: no match

The other two were counts: `23 here, 4 there, zero overlap` described two machines that no longer
exist, and `bundled (~59)` counts an installed Hermes' bundled set, which this repository cannot see
(no `.bundled_manifest` is tracked). Both appeared in the README as figures a reader would take as
facts about the tree.

A claim that cannot be measured should not be stated as a number. The prose stops stating them, and
the audit stops carrying them.

## What Changes

- README: `bundled (~59)` becomes `bundled`; the historical sentence keeps its point ("disjoint, no
  overlap") without the two counts.
- `claim-audit.py`: the ghost claim is deleted; the section that held the two counts now explains
  what used to be there and why it was retired, keeping `UNPROVEN` in the vocabulary for the next
  honest limitation.
- `docs/milestone.md`: the CI row said "six jobs" and the status cited `68b7a81` and nine check
  runs. It now says seven jobs / ten check runs on `88896ec`, records the three changes that landed
  after it was declared reached, and names the current contract (11 requirements, two capabilities).

## Capabilities

No behavior changes: no script output besides the audit's own claim count, no API, no shipped file.
`skip_specs: true` — this is prose and an audit that stop asserting what they cannot measure.

## Impact

README.md, scripts/claim-audit.py, docs/milestone.md. `gate-integrity`'s requirement "Enforcement
prose states only what is checked" is what this change applies to the README; no requirement needs
to change for it.
