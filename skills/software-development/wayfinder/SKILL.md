---
name: wayfinder
description: "Chart work too big for one session as a decision map."
version: 1.0.0
author: Matt Pocock (mattpocock), adapted by user, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
category: software-development
metadata:
  hermes:
    tags: [planning, decisions, map, fog-of-war, frontier, scoping]
    source: mattpocock/skills@v1.3.1
    related_skills: [grill-me, domain-modeling, to-spec, to-tickets]
---

# wayfinder

A loose idea has arrived that is too big for one session and wrapped in fog: the
route to the **destination** is not visible yet. Wayfinding finds that route — it
does not charge at the destination.

Chart the route as a **map**, then work its **decision tickets** one at a time until
nothing is left to decide.

## Plan, don't do

Wayfinder is **planning** by default: each ticket resolves a *decision*, and the map
is done when the way is clear. The pull to just do the work is usually the signal
you have reached the edge of the map and it is time to hand off.

## The map

A single file (default `docs/wayfinder/<slug>.md`; a GitHub issue if the repo uses
them) holding:

```markdown
# <destination>

## Destination
What this effort is finding its way to. Named first — it fixes the scope.

## Notes
Backend, conventions, skills each ticket should load.

## Decisions so far
- [<closed ticket title>](link): <one-line gist>
<!-- an INDEX, not a store: gist + link, never the detail -->

## Not yet specified
<!-- in-scope fog: real but not yet sharp enough to ticket -->

## Out of scope
<!-- ruled beyond the destination; never graduates -->
```

The map is an **index, not a store**. A decision lives in exactly one place — its
ticket. The map gists and links; it never restates.

**Refer to tickets by name, not id.** A wall of `#42, #43, #44` is illegible. The id
rides inside the link.

### Tickets

One file per ticket (default `docs/wayfinder/<slug>/<ticket>.md`). Each holds a
`## Question` — the decision it resolves — sized to one session, plus the tickets
that **block** it. A ticket is **unblocked** when everything blocking it is closed.
The **frontier** is the open, unblocked, unclaimed tickets: the edge of the known.

A session **claims** a ticket before doing any work on it, so a concurrent session
skips it. In files, a `status: claimed` line is the claim.

### Ticket types

Every ticket is **HITL** (worked *with* a human who speaks for themselves) or
**AFK** (the agent alone). A HITL ticket resolves only through that exchange — an
agent answering its own grilling questions has broken this.

- **research** (AFK) — read docs, APIs or local knowledge to surface a fact a
  decision waits on. Use when the knowledge lives outside this working directory.
- **prototype** (HITL) — raise fidelity with a cheap rough artifact to react to.
  Use when "how should it look / behave" is the question.
- **grilling** (HITL) — conversation; the default. See `grill-me`.
- **task** (HITL or AFK) — work that must happen before a *decision* is possible:
  nothing to decide, but discussion is blocked until it is done. Earns its place by
  unblocking a decision, not by delivering the destination.

## Fog of war

The map is *deliberately* incomplete: do not chart what you cannot yet see. Beyond
the live tickets lies the **fog** — decisions you can tell are coming but cannot
phrase yet, because they hang on open questions. Resolving a ticket clears the fog
ahead of it, graduating what is now specifiable into tickets.

**Fog or ticket?** The test is whether you can state the question precisely *now*,
not whether you can answer it now.

- **Ticket** when the question is already sharp — even if it is blocked.
- **Not yet specified** when you cannot phrase it that sharply. Do not pre-slice fog
  into ticket-sized pieces; one patch may graduate into several tickets, or none.

## Out of scope is not fog

Fog only ever gathers *toward* the destination. Work beyond it is **out of scope**
and gets its own section. Scope, not sharpness, lands it there. Out-of-scope work
never graduates — if the destination is redrawn, it becomes a fresh effort.

Ruling something out is a scoping act, not a step on the route: close the ticket and
leave one line in **Out of scope** with the gist and the reason. It does not belong
in **Decisions so far**, which records the route actually walked.

## Charting a map

1. **Name the destination.** Grill (`grill-me`) to pin down what this map finds its
   way to — a spec, a decision, or a change. The destination fixes scope, so it is
   settled first.
2. **Map the frontier, breadth-first** — fan across the whole space rather than deep
   on one thread, surfacing open decisions and what is takeable now.
   **If this surfaces no fog** the route is already clear and one session would do:
   stop and say so rather than building a map nobody needs.
3. **Create the map**, then the tickets you can specify now, wiring blockers in a
   second pass (a ticket needs an identity before another can reference it).
4. **Fire the AFK research tickets** as parallel subagents (`delegate_task`).
5. Stop. Charting is one session's work and hand-resolves nothing.

## Working through a map

1. Load the map — the low-resolution view, not every ticket body.
2. **Choose one ticket** (the user's pick, else the first frontier ticket in order)
   and **claim it before any work**. Never resolve more than one per session, except
   research tickets.
3. Resolve it. Zoom into related or closed tickets on demand.
4. Record the answer in the ticket, close it, and append a one-line pointer to
   **Decisions so far**.
5. Graduate any fog the answer made specifiable; add newly-surfaced tickets. If the
   answer shows a ticket sits beyond the destination, rule it out of scope rather
   than resolving it. Update or delete tickets the decision invalidated.

## Verification

- [ ] The destination is named and the scope derives from it
- [ ] The map holds no decision detail — only gists and links
- [ ] Tickets are referenced by name, never by bare id
- [ ] Every fog entry fails the "can I phrase it sharply now?" test
- [ ] Out-of-scope work is in its own section, not in fog or decisions
- [ ] One ticket resolved per session, claimed before work
