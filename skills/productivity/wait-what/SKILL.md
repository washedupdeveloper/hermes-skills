---
name: wait-what
description: "Re-pitch the last message in plain, simple English."
version: 1.0.0
author: Matt Pocock (mattpocock), adapted by user, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
category: productivity
metadata:
  hermes:
    tags: [communication, clarity, plain-language, re-pitch]
    source: mattpocock/skills@v1.3.1
    related_skills: [domain-modeling]
---

# wait-what

The user is telling you the last message did not land. Do not apologise, do not
re-explain the same way, and do not add more detail — **re-pitch it**.

## How

1. **Give a little context first.** One or two lines on where this sits, so the
   re-pitch is not itself context-free.
2. **Rewrite in ASD-STE100 Simplified Technical English:**
   - One idea per sentence.
   - Short sentences. Active voice.
   - One word, one meaning — no synonyms for the same thing.
   - No idiom, no metaphor, no jargon you have not already defined.
   - Concrete nouns and verbs over nominalisations.
3. **Use the project's own vocabulary.** If a `GLOSSARY.md` exists, use its terms
   exactly (follow `GLOSSARY-MAP.md` if the repo has more than one context). A
   re-pitch in a private dialect has not helped.
4. **Cut, do not expand.** The usual cause of a failed message is length and
   nesting, not missing information. If something is genuinely missing, add it —
   but assume the problem is density.

## Do not

- Restate the same paragraph more slowly.
- Add caveats, hedges, or a summary of the summary.
- Explain what you are about to do instead of doing it.

The measure of success is that the user understands on this reading, without asking
a second time.
