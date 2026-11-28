---
name: grilling
description: "Use when a plan or idea needs a relentless interview."
version: 1.1.0
author: "Matt Pocock (mattpocock/skills, grilling) + Hermes Agent"
license: MIT
platforms: [linux, macos, windows]
category: software-development
metadata:
  hermes:
    tags: [planning, interview, decision-tree, alignment, adversarial]
    source: mattpocock/skills@main
    related_skills: [grill-me, grill-with-docs, domain-modeling]
writes: [none]
side_effects: [none]
scope_answers: ["how to interview a plan relentlessly"]
scope_triggers: [interview a plan, relentless questioning]
scope_out: [the verdict on it (critical-verdict), grilling with repo docs (grill-with-docs)]
---

# grilling

Interview the user relentlessly until you share one understanding. This is the
interview primitive; `grill-me` and `grill-with-docs` are entry points that call
it, and `domain-modeling` is what `grill-with-docs` adds.

## The design tree

Every decision branches into the decisions that hang off it. Work the tree in
**rounds**. The **frontier** is every decision whose prerequisites are already
settled: the questions you can ask *now* without guessing at answers you have not
heard yet.

Ask the whole frontier in one round, numbered, each question carrying your
recommendation. Then wait for the answers before the next round.

**Round size is the user's call.** If the user asks for one question at a time,
ask exactly one and stop; do not batch the frontier. Confirm any answers they
volunteered, then take the first unresolved decision. "Go with your
recommendations" accepts the recommendation on the table; it does not delegate
the remaining decisions, so keep the cadence until the frontier is empty.

```
❓ Q1 — <question title>: <question body, options if relevant>
➡️ Recommendation: <your answer + one line on why>

❓ Q2 — <question title>: <question body>
➡️ Recommendation: <...>
```

Word each question so that "yes" accepts your recommendation. A question whose
answer depends on another question still open in this round belongs to a **later**
round, not this one.

Each answer reshapes the tree: settled decisions push the frontier outward and
unblock what depended on them. Recompute the frontier, ask the next round.

**Facts are your job; decisions are the user's.** When a question needs a fact
from the environment, find it yourself with `search_files`, `read_file`,
`terminal` or `skill_view`, or dispatch a subagent with `delegate_task` for heavy
exploration. Never ask the user for something you could look up. Do not block the
whole round on an exploration: only the questions downstream of it wait; ask the
rest now.

**A design question whose viability is a measurement is not yet a question.** When
the recommendation rests on a number nobody has taken — will the subset actually
catch these cases, how often does the fallback fire, what does the current thing
cost — take that measurement before the round and put it *in* the question. The
same proposal is a different conversation at 2% and at 20×, and asking the user to
decide on an unmeasured premise spends a round on something that may be worthless.
If the measurement kills the idea, say so and withdraw it; that is a better
outcome than a well-run interview about a bad option.

## 1-3-1, when it is asked for

Some users want the proposal before the interview: **one problem, three options,
one recommendation**. It is the shape that makes a decision legible in one screen.

- One **problem** in a sentence, with the number that makes it a problem.
- Exactly **three** viable options, each naming its kind — instrument, objective or
  workaround — and its cost. A dominated option is named as dominated and left off
  the menu.
- One **recommendation**, with the reason in a line.

The 1-3-1 picks the *direction*; the round that follows picks the *details* of the
chosen direction, which the 1-3-1 cannot settle. Run both, in that order, and do not
let the 1-3-1 stand in for the questions it leaves open.

## Grilling an implementation

The tree is the same; the questions are aimed at decisions already made. A system
that runs is a decision inventory before it is anything else: every default,
boundary, retry count and ordering was chosen by someone, and the ones nobody
remembers choosing are the ones that need sign-off.

1. **Read the artifact before asking anything.** Source, tests, packaging, and the
   docs that describe them. Questions cite `file:line`; a question about behaviour
   you have not read is a guess wearing a question mark.
2. **List the decisions, including the implicit ones.** Defaults, retry policies,
   merge keys, trust boundaries, vocabulary. Mark each `user-decided`,
   `agent-decided` or `inherited`, and say which the user has never seen.
3. **Ask the frontier in one round.** For each: what it does now with the line that
   does it, what it costs, the options, and your recommendation. Lead with the
   decisions the user never made.
4. **Separate defect from preference, and say which you are raising.** A defect
   gets fixed; a preference gets asked. Presenting a preference as a defect to win
   it is the failure mode of this interview.
5. **Write nothing until the round is answered.** The deliverable is the decision
   record; code follows the answers.

A decision taken on the user's silence is still the agent's decision. It is not
the user's design until they have seen it stated and had the chance to reject it.

## Question coverage

Work these branches into the tree, not into a checklist read aloud:

- **Understanding** — the real objective; what is explicitly in and out of scope;
  constraints (time, tech, team); who the users are.
- **Technical** — why this approach and not X; what happens when Y fails; the worst
  case; how to roll back; whether the codebase already has a pattern for this.
- **Edge cases** — what if the user does Z; what if a dependency is down; what if
  volume is 100×; what are the security implications.

## Synthesis

When the frontier is empty:

1. Summarise every decision in bullets.
2. List what is still open and what is explicitly out of scope.
3. Ask: "Aligned? Should I start, or adjust anything?"

Do not act until the user confirms shared understanding.

## Pitfalls

1. **Asking out of dependency order.** A question that depends on an unanswered
   question is a guess wearing a question mark.
2. **Skipping the artifact.** Find facts with tools instead of asking the user.
3. **Accepting "I don't know" as final.** Offer options, explain trade-offs,
   recommend one.
4. **Writing code during the interrogation.** Alignment only.
5. **Being too agreeable.** If everything looks fine, look harder.
6. **Not adapting to the user's language.** Interview in the language they use.
7. **Treating a one-word answer as settled when the question was ambiguous.** A
   bare "no" to "should X be able to …" and a bare "yes" to "do we keep …" can each
   mean the opposite of the recommendation attached to it. Restate your reading,
   implement it, and mark it for correction.
8. **An answer that changes the question is a new branch,** not a decision on the
   old one. Record it, ask its design questions next round, and keep it out of the
   batch the answered questions unblocked.
9. **Asking in internal vocabulary.** A choice stated as "user verb" or "module
   owner" is unanswerable to the person deciding — they have to ask what it means,
   which costs a round. State the concrete difference: what they type, what they
   see, what changes in the artifact. If a term needs a gloss to be answered, it is
   the wrong term for the question.
10. **Batching after the user asked for one at a time.** The default round is the
    whole frontier, but the user's cadence overrides it. A second question in the
    same message reads as not listening, even when both are good questions.
11. **Offering a dominated option as a peer.** If an option is worse on every
    axis the user cares about, do not put it on the menu. Name it as dominated
    and leave it out; a menu with a known-bad choice costs a round and makes the
    recommendation look unconsidered. Options are viable alternatives, not a
    completeness display.
12. **Asking about a premise you could have measured.** A round built on "this
    should be faster" or "the subset should catch it" spends the user's attention
    on an assumption. Measure the decisive number first; if it invalidates the
    idea, say so and drop it. A question is for a choice between viable things.

## Verification

- [ ] Every question had its prerequisites settled
- [ ] Each question carried a recommendation
- [ ] Facts were looked up, not asked
- [ ] Frontier empty before synthesising
- [ ] A summary of decisions and open items was produced
- [ ] The user confirmed alignment before acting