# Tool and result surfaces

A tool definition, a parameter schema and a tool result are documents an agent reads. They
are written for a consumer that pays for every token on every turn of every session, and
that cannot ask a clarifying question. The craft below is from DeepSeek Harness's
`agent-experience` guidance, mapped onto Hermes' hook and skill mechanics.

## What the model is given, and when

| surface | when it is read | what it costs |
|---|---|---|
| tool name, description, parameter schema | every turn, in the tool list | every token, always |
| a skill's `description` | every turn, in the skill index | every token, always |
| a skill's body | only when the skill is opened | once, on use |
| a tool result | on the turn that produced it, then in history | until compaction |

So the rule that follows is structural: **a fact belongs on the surface that is read when
it is needed.** A constraint that only matters when the tool is called belongs in a
parameter description, not in the tool description; a procedure belongs in the skill body,
not in its description.

## Tool definitions

- **Delete obvious constraints.** Omit rules the model learns from the call result — a
  missing file fails to read, a failed send is not delivered. They spend context to teach
  something the world already teaches.
- **Describe behaviour, not implementation.** What the tool does and what it returns.
  Internal mechanisms, enforcement details and the output markers the model already sees in
  results are cost with no decision attached.
- **Put parameter rules on the parameter.** Defaults, ranges, pairing, and when-to-set
  rules belong in that parameter's own description. A tool description that varies with
  configuration usually means the varying part is a parameter.
- **Say each fact once.** Not the tool definition again in the prompt section, not a
  parameter description again in the tool description, not one tool's rules in another's.
- **Name the boundary the caller must respect.** Permissions, destructive effects, and
  required validation go *before* the relevant action, in the surface read before the call.
- **Measure the change.** `harness_audit(action="requests")` reports input tokens and
  system-prompt bytes per request. A definition change quoted without a before/after number
  is an impression.

## Results

- **Prefer bounded output with a retrievable pointer.** Return the concise result plus an
  identifier or path for the detail. Do not dump a whole log when four lines and a path
  answer the question.
- **Use locality.** Include a bounded amount of the adjacent context the next step is
  likely to need — a few preceding messages with a reply, the lines around a match.
- **Mark omissions explicitly.** Every truncation states that it happened, how much was
  cut, and how to get the rest. Silent truncation reads as a complete answer.
- **Evaluate total work, not context saved.** Saving tokens is a win only if it does not
  cause more searches, repeated reads, or mistakes. A pointer the model cannot follow is
  worse than the text it replaced.

## Skills, as a surface

- **The description is the pointer; the body is the payload.** The description must carry
  the trigger — the condition under which this skill is the right one — because it is the
  only part loaded before the decision to open it.
- **The body is read whole and read again later.** It must make sense from any section,
  since a later session may reach it by heading. No "as described above" compression.
- **An edit to the body is served on the next read; an edit to the description waits for a
  reload**, because the index is built at session start. Confirm the two separately, and say
  which one you checked.
- **A support file is not a skill.** Anything under `references/`, `templates/`, `assets/`
  or `scripts/` is read only when a body names it — so a file nobody names is invisible, and
  a name pointing at an absent file is a broken pointer.

## Verification

- [ ] Every parameter's rules are on that parameter, not in the tool description
- [ ] No fact is stated twice across the tool surface
- [ ] Each truncation or omission says so, and says how to get the rest
- [ ] The skill description states the trigger, not the topic
- [ ] A tool-definition change carries a before/after token measurement
