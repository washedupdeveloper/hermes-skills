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

## Taxonomy: seven domains to ten

Task 8 moves the catalog from seven domains to ten, one commit per domain. `docs` moved
first (`820cc6d`); this is the decision for the other two.

The evidence for moving anything at all:

| measurement | value |
|---|---|
| `software-development` share of the catalog | 39 of 70 |
| `note-taking`, `productivity` | 1 skill each |
| routing after the `docs` move | 74/74, floor 100% — the taxonomy is routing-neutral |
| the test each domain is held to | its `CATEGORY.md` question, which its own skills must answer |

### Proposed

| domain | skills | question it states |
|---|---|---|
| `build` | `nix-flake-checks`, `nix-flake-packaging`, `oci-image-without-runtime`, `release-versioning` | how does this repository turn its source into an artifact? |
| `testing` | `cross-platform-test-portability`, `deterministic-quality-gates`, `verify-and-stop` | how do you know the artifact works, on every platform it claims? |

Both sets answer their question without borrowing from `devops` (runtime and host
services) or `software-development` (design, review, planning). `nix-declarative-config`
stays in `devops`: it declares a host, not an artifact.

### Rejected

| option | why not |
|---|---|
| merge the thin domains into one `workflow` domain | hides the real defect: `note-taking` asks how to structure a knowledge base, and its only skill answers how Bases views and filters work. Merging keeps the mismatch and adds a home for nothing |
| split by language or framework (`python`, `nix`) | no such axis exists in the catalog; several skills span both |
| leave seven and rely on triggers | triggers route per skill, so the score cannot see that one domain holds 39 skills — the taxonomy problem is invisible to the measure that would justify the move |

### Still open after these two

`note-taking` and `productivity` remain one skill each, and their `CATEGORY.md` questions
describe jobs their skill does not do. Two ways out, and this change does not pick one:

1. **Rewrite the questions** to match the skill (`note-taking`: how does an Obsidian Base
   express a query?), leaving the domains small but honest.
2. **Move the skills** to a domain whose question they answer, and delete the empty one.

Either is a one-commit change. What is not acceptable is leaving a question that its own
skills cannot answer, because that is the same defect the routing measure exists to catch.
