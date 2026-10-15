---
name: caveman-compress
description: Use to shrink a memory file's tokens.
version: 1.0.0
author: JuliusBrussee/caveman, adapted by user
license: MIT
platforms: [linux, macos, windows]
category: communication
metadata:
  hermes:
    tags: [tokens, context, memory, compression]
    related_skills: [caveman, ultracave]
    source: https://github.com/JuliusBrussee/caveman @ d262ab3882952a59312ff3537cd86d894523c5ab
---

# caveman-compress

Compress a natural-language file that is re-read every turn — a memory file
(`MEMORY.md`, `USER.md`), an agent context file (`AGENTS.md`, `CLAUDE.md`), or a todo
list — so it costs fewer **input** tokens on every future turn.

Input tokens are the recurring cost: a file injected into context is paid for on every
turn, while the one-off compression is paid for once. This is the highest-leverage
compression in the system, and the opposite end of the skill family from `caveman`,
which compresses what you *write*.

Do the compression yourself, in place. Do not shell out to a compression service, and
do not send the file anywhere.

## Requires an explicit filepath

Ask for the file to compress. If the user pastes raw text instead, ask for the
filepath, or offer to save the text to a file first.

**Never write your own reasoning about the request into the compressed output.** A
line like "user passed text directly, not a filepath" is the exact failure this guards
against — commentary must never leak into a saved file.

## Process

1. Back up first: copy `<file>` to `<file>.original.md` **outside the tree the loader
   scans** — `$XDG_DATA_HOME/caveman-compress/backups/<parent-dir>/`. A backup sitting
   beside the source gets re-ingested as a live file and costs the tokens the
   compression just saved.
2. Read the file. Note what must survive verbatim (below).
3. Rewrite the prose. Leave code and structure alone.
4. Report the before/after character counts. If it did not shrink, say so and restore
   the original — a compression that grew the file is a failed compression.

## Remove

- Articles: a, an, the
- Filler: just, really, basically, actually, simply, essentially, generally
- Pleasantries: "sure", "certainly", "of course", "happy to", "I'd recommend"
- Hedging: "it might be worth", "you could consider", "it would be good to"
- Redundant phrasing: "in order to" → "to", "make sure to" → "ensure", "the reason is
  because" → "because"
- Connectives: "however", "furthermore", "additionally", "in addition"

## Preserve EXACTLY

- Code blocks (fenced and indented)
- Inline code (backtick content)
- URLs and links
- File paths, commands
- Technical terms (library, API, protocol, algorithm names)
- Proper nouns, dates, version numbers, numeric values
- Environment variables (`$HOME`, `NODE_ENV`)

## Preserve structure

- All headings, with their exact text — compress the body below, not the heading
- Bullet nesting level, list numbering, table structure
- Frontmatter / YAML headers

## Compress

- Short synonyms: "big" not "extensive", "fix" not "implement a solution for", "use"
  not "utilize"
- Fragments: "Run tests before commit", not "You should always run tests before
  committing"
- Drop "you should", "make sure to", "remember to" — state the action
- Merge bullets that say the same thing differently
- Keep one example where several show the same pattern

Anything inside ``` fences or backticks is copied exactly: do not remove comments,
spacing, or lines, reorder, or shorten. If the file mixes prose and code, compress
only the prose. Unsure whether something is code? Leave it.

## Boundaries

- Compress natural language only: `.md`, `.txt`, `.typ`, `.tex`, extensionless.
- Never rewrite `.py`, `.js`, `.ts`, `.json`, `.yaml`, `.toml`, `.env`, `.lock`,
  `.css`, `.html`, `.xml`, `.sql`, `.sh`.
- Skip `*.original.md` — never compress a backup.
- A memory file carries load-bearing facts (paths, conventions, corrections). If
  compressing would drop a fact or blur a distinction the file was written to make,
  leave that passage alone. A shorter file that loses a rule costs more than it saves.
