#!/usr/bin/env python3
"""Audit a skill library as a set: category histogram, description budget,
description overlap, cross-name mentions.

    python3 scripts/domain-audit.py <skills-root> [--window 60] [--top 12]

The output is a *report*, not a verdict. Overlap by description similarity finds
candidates; the only hard rule is that two skills may not claim the same trigger.
Read every pair before acting on it: shared vocabulary ("review", "commit")
produces false positives, and a genuine conflict usually shows one skill's
out-of-scope line missing.

Stdlib only, no writes unless --json is given.
"""
import json
import os
import re
import sys
from collections import Counter, defaultdict
from itertools import combinations

STOP = set("""a an and are as at be by can do does for from has have if in into is it
its must not of on or should so than that the their them then there these they this
to use used uses when which will with without you your skill skills task tasks""".split())


def parse_frontmatter(path):
    text = open(path, encoding="utf-8", errors="replace").read()
    fields = {}
    m = re.match(r"^---\n(.*?)\n---", text, re.S)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line and not line.startswith((" ", "\t")):
                k, v = line.split(":", 1)
                fields[k.strip()] = v.strip().strip('"').strip("'")
    return fields


def tokens(text):
    return {w for w in re.findall(r"[a-z0-9-]+", text.lower())
            if w not in STOP and len(w) > 2}


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__.strip())
        return 2
    root = args[0]
    opts = dict(a[2:].split("=", 1) for a in argv[1:] if a.startswith("--") and "=" in a)
    window = int(opts.get("window", 60))
    top = int(opts.get("top", 12))

    skills = []
    for dirpath, _dirnames, filenames in os.walk(root):
        if "SKILL.md" not in filenames:
            continue
        p = os.path.join(dirpath, "SKILL.md")
        fields = parse_frontmatter(p)
        rel = os.path.relpath(dirpath, root)
        parts = rel.split(os.sep)
        skills.append({
            "name": fields.get("name") or os.path.basename(dirpath),
            "category": parts[0] if len(parts) > 1 else "(root)",
            "description": fields.get("description", ""),
            "path": rel,
        })

    print(f"skills: {len(skills)}")
    hist = Counter(s["category"] for s in skills)
    print("\ncategory histogram")
    for cat, n in hist.most_common():
        share = 100.0 * n / len(skills) if skills else 0
        flag = "  <-- junk-drawer risk" if n > 15 else ("  <-- single-skill domain" if n < 3 else "")
        print(f"  {cat:<28} {n:>3}  {share:5.1f}%{flag}")

    over = [s for s in skills if len(s["description"]) > window]
    print(f"\ndescriptions over {window} chars: {len(over)}")
    for s in sorted(over, key=lambda x: -len(x["description"]))[:top]:
        print(f"  {len(s['description']):>4}  {s['name']}")

    pairs = []
    for a, b in combinations(skills, 2):
        ta, tb = tokens(a["description"]), tokens(b["description"])
        if not ta or not tb:
            continue
        j = len(ta & tb) / len(ta | tb)
        if j > 0.15:
            pairs.append((j, a["name"], b["name"], a["category"], b["category"]))
    pairs.sort(reverse=True)
    print(f"\ndescription overlaps (>0.15): {len(pairs)}")
    for j, a, b, ca, cb in pairs[:top]:
        cross = "  CROSS-DOMAIN" if ca != cb else ""
        print(f"  {j:.2f}  {a} [{ca}]  <->  {b} [{cb}]{cross}")

    print("\ncross-name mentions in descriptions")
    names = {s["name"] for s in skills}
    hits = 0
    for s in skills:
        named = [n for n in names if n != s["name"] and n in s["description"]]
        if named:
            hits += 1
            print(f"  {s['name']} -> {sorted(named)}")
    if not hits:
        print("  none")

    out = opts.get("json")
    if out:
        json.dump({"skills": skills, "histogram": dict(hist),
                   "over_window": [s["name"] for s in over],
                   "overlaps": [{"jaccard": round(j, 3), "a": a, "b": b} for j, a, b, _, _ in pairs]},
                  open(out, "w"), indent=1)
        print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
