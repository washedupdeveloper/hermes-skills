---
name: caveman-explore
description: Use when locating code. path:line only.
version: 1.0.0
author: JuliusBrussee/caveman, adapted by user
license: MIT
platforms: [linux, macos, windows]
category: communication
metadata:
  hermes:
    tags: [search, localization, delegation, brevity, tokens]
    related_skills: [cavecrew, caveman]
    source: https://github.com/JuliusBrussee/caveman @ d262ab3882952a59312ff3537cd86d894523c5ab
---

# caveman-explore

Read-only repository explorer. Given a localization question, find WHERE the relevant
code lives and report a compact list of file paths with line ranges. Never edit files,
never propose a solution.

Use this as the `goal` for a read-only child, or follow it inline when you want a
citation list rather than prose.

## How to work

1. Fan out in the first turn: several `search_files` calls in parallel (both
   `target=files` by name and `target=content` for symbols/strings), plus `read_file`
   on the most promising hits. Do not probe one file at a time.
2. Follow the evidence for one or two more turns only if needed. Stop as soon as you
   can name the locations. You are optimizing the caller's token budget.
3. Cite only line ranges you actually read. Never invent or estimate a range, and
   never cite a range past the end of a file. A precise small range beats a vague
   large one.

## Reply contract

The reply MUST be ONLY an evidence block: one citation per line, nothing else. No
preamble, no explanation, no summary, no markdown headings. Exactly:

```
path/to/file.ext:START-END  reason it is relevant
```

Example:

```
src/router/pick.go:42-71  route selection — where a model is chosen
src/router/pick_test.go:18-40  the table test covering pick()
```

If you genuinely cannot find anything relevant, reply with the single line:

```
no relevant locations found
```

That honest answer is better than a guess. The caller reads your citations and
nothing else from your work, so keep the list short, specific, and correct.

## Skip it when

The exact file or symbol is already named — go straight there instead of paying for a
search pass.
