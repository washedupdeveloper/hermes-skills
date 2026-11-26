# Design

## Context

This change was proposed before this repository had a written authoring loop. Re-run on
2026-11-26, its premises were checked against the tree rather than assumed, and the
decisions it made implicitly are recorded here. The tasks that remain are the ones whose
premises still hold.

## What the re-run changed

| decision | taken | rejected | would be falsified by |
|---|---|---|---|
| Re-audit rather than replay | Check each task's premise against the tree before working it | Executing the checklist as written | A task whose premise still holds would be skipped; none were |
| Evidence for finished work | Record the command that proves each ticked task | Trusting the original tick marks | A row whose command does not pass today |
| Scope stays in `scripts/scope.py` | One module, called from the single gate | A second checker in the gate | Two validators disagreeing on the same skill |
| `side_effects` stays a closed vocabulary | Nine tokens in `library/contract.json` | Free-form strings with a warning | A spawning skill that declares `[none]` and passes |

## Measurements taken on 2026-11-26

| claim | command | result |
|---|---|---|
| every skill declares its scope | `grep -l "^writes:" $(find skills -name SKILL.md) \| wc -l` | 70 of 70 |
| every skill declares its effects | `grep -l "^side_effects:" $(find skills -name SKILL.md) \| wc -l` | 70 of 70 |
| the domains carry a statement | `ls skills/*/CATEGORY.md \| wc -l` | 7 of 7 |
| the gate accepts the tree | `python scripts/validate.py` | 0 violations |

## Decisions still open

Task 11 (declare the true `side_effects` for skills that spawn something) is a judgement
call per skill, not a mechanical edit: 68 of 70 declare `[none]`, while 10 skill files
mention `systemctl`, 4 `podman run`, 3 `docker run`, 2 `nohup`, 3 `nix profile install`
and 5 `npm install -g`. Those mentions are mostly *instructions to the reader*, not
effects the gate performs, and the contract's rule is about what a skill does when it
runs. Separating the two needs a rule, not a find-and-replace; that is why it is still
open and why it is stated here rather than guessed at.
