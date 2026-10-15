---
name: obsidian-bases
description: "Use when authoring or debugging Obsidian Bases views."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [obsidian, bases, views, kanban, dashboard, verification, cdp]
    category: note-taking
    related_skills: [obsidian, hermes-knowledge-pipeline]
---

# Obsidian Bases views

Bases is an Obsidian **core plugin** that renders database-like views — table, list, cards,
kanban — over notes and their properties. A `.base` file is YAML describing filters, formulas
and one or more views; the same syntax embeds in a note as a ` ```base ` code block or as
`![[File.base#View]]`. Enable it under Settings → Core plugins.

Use this skill when a vault needs a visual surface over its own notes: a work board, an
activity timeline, a review queue, a source listing. The views read the notes directly, so
nothing is duplicated and nothing can go stale — provided you verify by rendering.

`obsidian` owns vault file operations; `hermes-knowledge-pipeline` owns the pipeline that
produces the notes. This skill owns the **view layer**: what a base can express, and how to
prove it works.

## When to Use

- "Make me a board / dashboard / overview of what is being worked on" in a vault.
- Adding a filterable, sortable surface over a vault's notes: a review queue, an activity
  timeline, a source listing, a status board.
- A `.base` file exists and does not render, renders empty, shows an error in a cell, or will
  not let cards be dragged.
- Any request to filter, sort or group notes by their properties or file metadata for a human
  to read.
- You are about to say a view works. Load this before that claim, not after.

## Prefer ONE note with inline blocks over a directory of `.base` files

A ` ```base ` code block renders in place inside a note, so every view a human needs can live
in a single dashboard note (`HOME.md`). That is usually the right shape: six `.base` files in a
`views/` folder is six places to look, and the reader has to know which one answers their
question. One note read top to bottom is one place.

Use separate `.base` files only when a view is embedded from several notes, or when a note would
grow past readability. Embedding is `![[File.base#View]]` for a file, or a ` ```base ` fence
inline — both are supported, and the inline form needs no second file to keep in sync.

## Procedure

1. **Decide the axes before writing YAML.** What is one row? Which property is the state that
   should be *editable* (that is the kanban group)? Which columns answer the reader's question?
2. **Write the views** — a `.base` file, or ` ```base ` fences inline in a dashboard note. Order
   the file `filters`, `formulas`, `properties` (display names), `views`. Those five top-level
   keys are the only valid ones.
3. **Give every `order` entry a prefix** — `file.name`, `note.status`, `formula.age_days`. An
   unprefixed entry is silently dropped from the column list. Note Obsidian may rewrite
   `note.status` to bare `status` when it saves; both are valid.
4. **Render it and read the DOM** with `scripts/verify_bases_render.py <vault>`, *before*
   saying anything about whether the view works.
5. **Order the note by what the reader needs first** — a "needs you" list above a status board
   above reference material. The first screen is the whole point of a single-file dashboard.

## Always-On Rules

- **A rendered artefact is not verified until you have read what it rendered.** Valid YAML,
  correct view types and a clean parse prove nothing: a broken formula renders as an error
  string *inside* an otherwise well-formed view. Run the verifier, or state plainly that the
  view is unverified. "It parses" is not "it works".
- **Age arithmetic must use `.days`.** `now() - <date>` yields a `Duration`, not a number: it
  has no `.round()`/`.toFixed()`, dividing it by 86400000 does not coerce it, and `number()`
  refuses it. Use `(now() - updated).days.round(1)`; `date.relative()` gives *"18 hours ago"*.
  See `references/formula-patterns.md` for the full verified/failing table.
- **Group a kanban on a note property, not on a formula or a file property.** Only a note
  property — or `file.folder` — produces draggable cards; anything else makes the board
  read-only. That single choice is the difference between a report and a control surface.
- **`userIgnoreFilters` is a results filter too.** A folder excluded in `.obsidian/app.json` is
  removed from Bases results as well as from search and the graph, so a base over it returns
  zero rows with no error at all. Un-exclude any folder a view must see.
- **Filter on a property, not on a label.** A topic or tag label catches the pages *describing*
  the subject as well as the records *of* it. Require something only a real record carries
  (`file.hasProperty("run_id")`) instead of trusting the label.
- **Obsidian rewrites the file it renders** — comments stripped, quoting normalised, and it
  may shorten `note.x` to `x`. This applies to a note carrying an inline ` ```base ` fence too:
  opening the dashboard re-serialises the fence. Put the reasoning in prose (outside the fence)
  or in a sibling README, never in comments inside the block.
- **Keep a generated, machine-local corpus out of the knowledge corpus.** A view may
  legitimately read notes that are not knowledge (agent activity, session logs). Give them their
  own directory and exclude it from any indexer or lint walk so they cannot pollute a report or
  a link graph, and gitignore it when it is per-machine.
- **Check a property's coverage before adding it as a column.** A property that is null on every
  note renders as a permanently empty column — sample the data first.
- **Do not hand-maintain a dashboard a view can generate.** If the same state is written twice,
  once as a markdown table and once as a base, the two will disagree.

## Verification

```bash
python scripts/verify_bases_render.py <vault>              # exit 1 on any formula error
python scripts/verify_bases_render.py <vault> --keep-open  # leave Obsidian on the debug port
```

It restarts Obsidian with `--remote-debugging-port`, opens **every `.base` file and every note
carrying an inline ` ```base ` fence**, reads each rendered view's type, result count and error
text, then restarts Obsidian *without* the port so the debug endpoint does not outlive the check.
Needs a `websockets` client and Obsidian installed.

Three things it gets right that a naive version does not, each learned the hard way:

- **It drives the vault you asked for, by name.** Obsidian restores whichever vault was last
  focused, so on a multi-vault machine a check that does not confirm the vault reports a
  cheerful "0 failures" for the wrong one — a false pass. If the target vault is not open the
  script opens it by URI and retries, and refuses to report a pass if it cannot.
- **It counts fences, not mentions.** Prose saying "inline ` ```base ` blocks" is not a view.
- **It says what it could not check.** Obsidian mounts base blocks lazily, so a long note may
  only render the top of itself; the report prints `(N block(s) never mounted - NOT checked)`
  rather than implying the whole note was verified. Treat that marker as "look at this by hand".

A zero result count is not automatically a failure — an empty source directory is legitimate —
but it is the shape an exclusion bug takes, so check `userIgnoreFilters` and the filter itself
before accepting it.

## Support files

- `references/formula-patterns.md` — the verified/failing formula table, the syntax contract,
  view types, file properties, and the by-hand CDP recipe.
- `scripts/verify_bases_render.py` — renders every base and fails on formula errors.
