#!/usr/bin/env python3
"""skill-audit.py — deterministic cost/duplication metrics for a SKILL.md corpus.

Run identically before and after a change; diff the JSON.

    python3 skill-audit.py <skills-root> > out.json

Measures, per skill and in aggregate: bytes and body tokens (the cost of loading
it), description length (the index-window cost — the only part loaded before the
skill opens), filler words, cross-skill n-gram redundancy, dead references, and
orphaned support files.

Nothing here judges QUALITY. A skill can be small and wrong; this measures cost and
duplication only.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
from collections import Counter, defaultdict

SUPPORT = ("references", "templates", "assets", "scripts")

# The caveman-compress "Remove" list, verbatim — the canonical filler definition.
FILLER = [
    r"\bjust\b", r"\breally\b", r"\bbasically\b", r"\bactually\b",
    r"\bsimply\b", r"\bessentially\b", r"\bgenerally\b",
    r"\bsure\b", r"\bcertainly\b", r"\bof course\b", r"\bhappy to\b",
    r"\bi'?d recommend\b", r"\bit might be worth\b", r"\byou could consider\b",
    r"\bit would be good to\b", r"\bin order to\b", r"\bmake sure to\b",
    r"\bthe reason is because\b", r"\bhowever\b", r"\bfurthermore\b",
    r"\badditionally\b", r"\bin addition\b", r"\bplease note\b",
    r"\bit is important to note\b", r"\bkeep in mind\b",
]

FENCE = re.compile(r"```.*?```", re.S)
INLINE = re.compile(r"`[^`\n]+`")
LINK = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")


def prose(text: str) -> str:
    """Body text with code and links removed, for word-level measures."""
    text = FENCE.sub(" ", text)
    text = INLINE.sub(" ", text)
    return LINK.sub(r"\1", text)


def norm_tokens(text: str) -> list:
    text = re.sub(r"[^a-z0-9\s-]", " ", prose(text).lower())
    return [t for t in text.split() if len(t) > 1]


def body_of(text: str) -> str:
    m = re.search(r"\n---\s*\n", text[3:])
    return text[m.end() + 3:] if m else text


def frontmatter(text: str) -> str:
    m = re.search(r"\n---\s*\n", text[3:])
    return text[3:m.start() + 3] if m else ""


def audit(root: pathlib.Path) -> dict:
    skills = {}
    for p in sorted(root.rglob("SKILL.md")):
        rel = p.relative_to(root).as_posix()
        if any(f"/{s}/" in rel for s in SUPPORT):
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        fm, body = frontmatter(text), body_of(text)
        d = re.search(r'^description:\s*"?(.*?)"?\s*$', fm, re.M)
        desc = d.group(1) if d else ""
        pr = prose(body)

        linked = {t.split("#")[0].strip() for _, t in LINK.findall(body)}
        linked |= set(re.findall(r"`((?:references|templates|assets|scripts)/[^`]+)`", body))
        dead = [l for l in linked
                if not l.startswith(("http", "//", "mailto:"))
                and not (p.parent / l).exists()]
        orphans = []
        for s in SUPPORT:
            sd = p.parent / s
            if sd.is_dir():
                for f in sorted(sd.rglob("*")):
                    if f.is_file() and not any(
                            l.endswith(f.name)
                            or l.endswith(f.relative_to(p.parent).as_posix())
                            for l in linked):
                        orphans.append(f.relative_to(p.parent).as_posix())

        lines = [ln for ln in body.splitlines() if ln.strip()]
        bullets = sum(1 for ln in lines if re.match(r"\s*([-*+]|\d+\.)\s", ln))
        skills[rel] = {
            "bytes": len(text),
            "body_bytes": len(body),
            "desc_len": len(desc),
            "desc_over_57": len(desc) > 57,
            "tokens": len(norm_tokens(body)),
            "filler": sum(len(re.findall(f, pr, re.I)) for f in FILLER),
            "dead_refs": dead,
            "orphans": orphans,
            "lines": len(lines),
            "bullets": bullets,
            "bullet_ratio": round(bullets / len(lines), 3) if lines else 0.0,
            "longest_line": max((len(ln) for ln in lines), default=0),
            "headings": len(re.findall(r"^#{1,6} ", body, re.M)),
            "has_platforms": bool(re.search(r"^platforms:", fm, re.M)),
            "has_category": bool(re.search(r"^category:", fm, re.M)),
        }

    # cross-skill redundancy: 6-grams appearing in 2+ skills
    grams = defaultdict(set)
    for rel in skills:
        toks = norm_tokens(body_of((root / rel).read_text(encoding="utf-8", errors="replace")))
        for i in range(len(toks) - 5):
            grams[" ".join(toks[i:i + 6])].add(rel)
    dup = {g: sorted(v) for g, v in grams.items() if len(v) > 1}
    mass = sum((len(v) - 1) * 6 for v in dup.values())
    by_skill = Counter()
    for v in dup.values():
        for r in v:
            by_skill[r] += 1

    agg = {
        "skills": len(skills),
        "bytes": sum(s["bytes"] for s in skills.values()),
        "tokens": sum(s["tokens"] for s in skills.values()),
        "desc_over_57": sum(1 for s in skills.values() if s["desc_over_57"]),
        "filler": sum(s["filler"] for s in skills.values()),
        "dead_refs": sum(len(s["dead_refs"]) for s in skills.values()),
        "orphans": sum(len(s["orphans"]) for s in skills.values()),
        "redundant_ngrams": len(dup),
        "redundant_token_mass": mass,
        "missing_platforms": sum(1 for s in skills.values() if not s["has_platforms"]),
        "missing_category": sum(1 for s in skills.values() if not s["has_category"]),
        "mean_bullet_ratio": round(
            sum(s["bullet_ratio"] for s in skills.values()) / max(len(skills), 1), 3),
    }
    return {"aggregate": agg, "per_skill": skills,
            "top_redundant": sorted(by_skill.items(), key=lambda x: -x[1])[:15]}


if __name__ == "__main__":
    root = pathlib.Path(sys.argv[1]).expanduser().resolve()
    print(json.dumps(audit(root), indent=2, sort_keys=True))
