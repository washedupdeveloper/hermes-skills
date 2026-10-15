# Bases: the contract, and what actually works

Everything below was verified by rendering in Obsidian, not read off the documentation. Where
the docs and a rendering disagreed, the rendering wins.

## File shape

Top-level keys — these five, nothing else:

| key | purpose |
|---|---|
| `filters` | which files are in the result set; applies to every view in the file |
| `formulas` | calculated properties, referenced elsewhere as `formula.<name>` |
| `properties` | display config, e.g. `displayName` |
| `summaries` | custom summary formulas; `values` is the list of values across the result set |
| `views` | a list; each entry is one view over the same data |

View keys: `type`, `name`, `limit`, `groupBy`, `filters`, `order`, `summaries`. A view-level
`filters` is ANDed with the file-level one. `order` is the column list and **every entry needs a
prefix** (`file.`, `note.`, `formula.`) — an unprefixed entry is dropped silently.

Filters nest as `and:` / `or:` / `not:` over a list of nested groups or statement strings:

```yaml
filters:
  and:
    - file.inFolder("work")
    - 'topic == "council"'
    - file.hasProperty("run_id")
```

A base with no `filters` includes **every file in the vault**, attachments included. An empty
`.base` file is valid and shows all of them — that is what Obsidian writes for a freshly created
base before a view is added.

## View types

| type | layout | needs |
|---|---|---|
| `table` | rows = files, columns = properties | — |
| `list` | bulleted / numbered list | — |
| `cards` | grid, optional cover image | — |
| `kanban` | columns from a grouped property | Obsidian 1.14+, and a `groupBy` |
| `map` | pins on a map | the **Maps community plugin**, not installed by default |

## Grouping, and when a board is interactive

```yaml
views:
  - type: kanban
    name: Board
    groupBy:
      property: note.status
      direction: ASC
```

**Cards can only be dragged when the group is a note property.** Grouping by a formula, or by a
file property other than `file.folder`, makes the board read-only. Only Markdown notes move
between columns, except under `file.folder`, where a move relocates the file. This is the reason
to group a board on an editable state property: dragging rewrites that property in the note's
frontmatter, which is what turns the board from a report into an input.

**A phantom column appears at the left of every Kanban view.** It is not caused by the base
file: a minimal two-line kanban shows it too, and it follows whichever property is grouped. Its
card has no `data-property` and is not draggable, unlike real cards. It is Obsidian's internal
template column — ignore it.

## Formulas: the pattern that bites

`now() - <date>` yields a **Duration**, not a number.

| expression | result |
|---|---|
| `(now() - updated).days.round(1)` | **works** — `.days` is a decimal |
| `(now() - updated).round(1)` | `Cannot find function "round" on type Duration` |
| `((now() - updated) / 86400000).round(1)` | same error — division does not coerce it |
| `number(now() - updated)` | `Unable to convert "Duration" to a number` |
| `(now() - updated).toFixed(1)` | `Cannot find function "toFixed" on type Duration` |
| `(now() - updated) / duration("1d")` | `Invalid operator between Duration and Duration` |
| `updated.relative()` | works — `"18 hours ago"` |
| `file.ctime.relative()` | works — for ingestion age |

The documentation's example — `(now() + "1d") - now()` returning milliseconds — does **not**
generalise to a subtraction between two dates. Found by rendering 14 candidates side by side and
reading which produced a value; do the same before trusting any new date formula.

Working patterns, all verified:

```yaml
formulas:
  age_days: (now() - updated).days.round(1)
  age: updated.relative()
  source_count: list(sources).length      # list() tolerates a single value vs a list
  kind: file.folder.split("/")[1]         # sub-folder name; empty at the vault root
  kb: (file.size / 1024).round(1)
  rank: if(priority == "P0", 0, if(priority == "P1", 1, 2))
  heat: if(status == "blocked", formula.rank + 0.5, formula.rank)
```

`file.size.round(0)` works. `if(condition, a, b)` is a global function. Formulas may reference
other formulas as `formula.<name>`, but not circularly.

## File properties

`file.name`, `file.basename`, `file.path`, `file.folder`, `file.ext`, `file.size`, `file.tags`,
`file.links`, `file.ctime`, `file.mtime`, `file.properties`. Functions: `file.hasTag(...)`,
`file.inFolder(...)`, `file.hasLink(...)`, `file.hasProperty(...)`, `file.asLink()`.

These are the axis for filtering on **metadata rather than content** — a source listing built
from `file.size` / `file.ext` / `file.folder` / `file.ctime` needs no properties on the notes at
all.

## Two ways an exclusion hides a base's rows

1. **`userIgnoreFilters`.** A folder in `.obsidian/app.json` → `userIgnoreFilters` is excluded
   from Bases results as well as from search and the graph. A base over such a folder returns
   zero rows and no error. Keep archive and generated-state folders excluded; un-exclude any
   folder a view needs to read.
2. **A filter that matches the wrong rows.** Filtering on a topic label catches the pages
   *describing* the topic as well as the records *of* it. Require a property only a real record
   carries — `file.hasProperty("run_id")` — rather than trusting the label.

## Obsidian rewrites the file

Opening a base re-serialises the `.base` file: **comments are stripped** and quoting is
normalised (`'single quoted'` comes back bare). Hand-editing works, but expect Obsidian to
reformat on the next open — so put the reasoning in a sibling `views/README.md`, never in
comments inside the `.base` file.

## Verifying by hand

1. Quit Obsidian (it holds config in memory and rewrites `.base` files), then relaunch with
   `--remote-debugging-port=9222`.
2. `GET http://127.0.0.1:9222/json` → the `type: "page"` target's `webSocketDebuggerUrl`.
3. `Runtime.evaluate` a promise that calls `app.workspace.getLeaf('tab').openFile(file)`, waits
   ~2 s, then reads `leaf.view.containerEl.innerText` and the `[data-view-type]` attributes.
4. Assert no error text, and that the result count and view type are what you intended.
5. Relaunch Obsidian **without** the port so the debug endpoint does not outlive the check.

The page title reveals which vault is open (`<file> - <vault> - Obsidian <version>`), which is
how to confirm the right vault is loaded before believing a zero-result view. Obsidian opens the
vault it last had open, and `getAbstractFileByPath` fails for every path in the wrong vault.
