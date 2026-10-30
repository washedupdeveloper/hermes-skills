#!/usr/bin/env python3
"""Deterministic bench for a skill library.

Two properties a skill library is actually paid for:

  1. routing  — a realistic request selects the skill that owns it. Measured by
     TF-IDF cosine over each skill's description, name and tags, against a frozen
     query set with a known owner.
  2. load     — the context a routed skill costs. Measured as the routed skill's
     body tokens, averaged over the same queries.

Plus integrity checks that are cheap and unambiguous: required frontmatter,
LF-only, and every `references/*.md` a skill names existing on disk.

    python3 skill-bench.py <skills-root> [queries.json] [--json out.json]

Not a task-success measure: it cannot run an agent. It measures the two things a
rewrite of the library can actually move, and refuses to score prose volume.
"""
from __future__ import annotations

import json
import math
import pathlib
import re
import sys

FENCE = re.compile(r"```.*?```", re.S)
REF = re.compile(r"references/([a-z0-9._-]+\.md)")
REQUIRED = ("name", "description", "version", "license", "platforms", "category")


def frontmatter(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    if not text.startswith("---"):
        return out
    head = text.split("---", 2)[1]
    for line in head.splitlines():
        m = re.match(r"^([a-z_]+):\s*(.*)$", line)
        if m:
            out[m.group(1)] = m.group(2).strip().strip('"')
    return out


def body_tokens(text: str) -> int:
    body = text.split("---", 2)[2] if text.startswith("---") else text
    return int(len(re.findall(r"\w+|[^\w\s]", body)) * 0.75)


def stem(t: str) -> str:
    for suf in ("ly", "ing", "ed", "es", "s"):
        if len(t) > len(suf) + 3 and t.endswith(suf):
            return t[: -len(suf)]
    return t


def tokens(s: str) -> list[str]:
    out = []
    for t in re.findall(r"[a-z][a-z0-9+#.:_-]{2,}", s.lower()):
        t = t.strip(".-:_")
        if len(t) >= 3:
            out.append(stem(t))
    return out


def load(root: pathlib.Path) -> list[dict]:
    rows = []
    for p in sorted(root.rglob("SKILL.md")):
        text = p.read_text(encoding="utf-8", errors="replace")
        fm = frontmatter(text)
        rel = p.parent.relative_to(root).as_posix()
        tags = re.search(r"tags:\s*\[([^\]]*)\]", text)
        blob = " ".join([rel.replace("/", " "), fm.get("description", ""),
                         tags.group(1) if tags else ""])
        rows.append({
            "skill": rel,
            "name": fm.get("name", p.parent.name),
            "desc": fm.get("description", ""),
            "tokens": body_tokens(text),
            "terms": tokens(blob),
            "refs": sorted(set(REF.findall(text))),
            "dir": p.parent,
            "fm": fm,
            "crlf": "\r" in text,
        })
    return rows


def idf(rows: list[dict]) -> dict[str, float]:
    df: dict[str, int] = {}
    for r in rows:
        for t in set(r["terms"]):
            df[t] = df.get(t, 0) + 1
    n = len(rows)
    return {t: math.log((n + 1) / (c + 0.5)) for t, c in df.items()}


def vec(terms: list[str], idf: dict[str, float]) -> dict[str, float]:
    tf: dict[str, float] = {}
    for t in terms:
        tf[t] = tf.get(t, 0) + 1
    v = {t: (1 + math.log(c)) * idf.get(t, 1.0) for t, c in tf.items()}
    norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
    return {t: x / norm for t, x in v.items()}


def cos(a: dict[str, float], b: dict[str, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(x * b.get(t, 0.0) for t, x in a.items())


def main() -> int:
    root = pathlib.Path(sys.argv[1])
    qpath = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 and not sys.argv[2].startswith("--") else None
    out = sys.argv[sys.argv.index("--json") + 1] if "--json" in sys.argv else None

    rows = load(root)
    idf_ = idf(rows)
    for r in rows:
        r["vec"] = vec(r["terms"], idf_)

    # integrity
    problems = []
    for r in rows:
        miss = [f for f in REQUIRED if f not in r["fm"]]
        if miss:
            problems.append((r["skill"], "frontmatter missing " + ", ".join(miss)))
        if r["crlf"]:
            problems.append((r["skill"], "CRLF"))
        for ref in r["refs"]:
            if not (r["dir"] / "references" / ref).is_file():
                problems.append((r["skill"], f"dangling references/{ref}"))

    result: dict = {
        "skills": len(rows),
        "tokens_total": sum(r["tokens"] for r in rows),
        "integrity_problems": [{"skill": s, "problem": p} for s, p in problems],
    }

    if qpath:
        queries = json.loads(qpath.read_text(encoding="utf-8"))
        hit = 0
        mrr = 0.0
        cost = 0
        misses = []
        for q in queries:
            qv = vec(tokens(q["query"]), idf_)
            ranked = sorted(rows, key=lambda r: -cos(qv, r["vec"]))
            top = [r["skill"] for r in ranked[:5]]
            cost += ranked[0]["tokens"]
            if ranked[0]["skill"] == q["expect"]:
                hit += 1
                mrr += 1.0
            else:
                rank = top.index(q["expect"]) + 1 if q["expect"] in top else 0
                mrr += 1.0 / rank if rank else 0.0
                misses.append({"query": q["query"], "expect": q["expect"],
                               "got": ranked[0]["skill"], "rank": rank})
        result |= {
            "queries": len(queries),
            "accuracy": round(hit / len(queries), 4),
            "mrr": round(mrr / len(queries), 4),
            "mean_load_tokens": round(cost / len(queries), 1),
            "misses": misses,
        }

    text = json.dumps(result, indent=2)
    if out:
        pathlib.Path(out).write_text(text + "\n", encoding="utf-8", newline="\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())