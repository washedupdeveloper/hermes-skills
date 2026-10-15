#!/usr/bin/env python3
"""claim-audit.py — check the mechanical claims in this repo's prose.

Every claim is classified:
  PROVEN   — checked here, right now, and it holds
  FALSE    — checked here and it does NOT hold
  UNPROVEN — cannot be checked from the repo alone (historical, external)

Usage: python3 claim-audit.py
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys

R = pathlib.Path(__file__).resolve().parent.parent
SK = R / "skills"

results: list[tuple[str, str, str]] = []


def claim(text: str, verdict: str, detail: str = "") -> None:
    results.append((verdict, text, detail))


def skill_files() -> list[pathlib.Path]:
    out = []
    for p in sorted(SK.rglob("SKILL.md")):
        if any(f"/{s}/" in p.as_posix() for s in ("assets", "references", "templates", "scripts")):
            continue
        out.append(p)
    return out


# ── counts the README states ─────────────────────────────────────────────────
total = len(list(SK.rglob("SKILL.md")))
catalog = len(skill_files())
rubrics = len(list(SK.rglob("assets/rubrics/*/SKILL.md")))
claim("README: '41 SKILL.md across 35 skills'",
      "PROVEN" if (total, catalog) == (41, 35) else "FALSE",
      f"actual: {total} SKILL.md across {catalog} catalog skills")
claim("README: 'Six of the 41 are the council's reviewer rubrics'",
      "PROVEN" if rubrics == 6 else "FALSE", f"actual: {rubrics}")

not_win = [p for p in skill_files()
           if not re.search(r"^platforms:.*windows", p.read_text(encoding="utf-8"),
                            re.M)]
claim("README: '34 load on Windows'",
      "PROVEN" if len(skill_files()) - len(not_win) == 34 else "FALSE",
      f"actual: {len(skill_files()) - len(not_win)} load; "
      f"skipped: {[p.parent.name for p in not_win]}")

# ── the description ceiling the repo enforces on itself ──────────────────────
over = []
for p in skill_files():
    fm = p.read_text(encoding="utf-8").split("---", 2)[1]
    m = re.search(r'^description:\s*"?(.*?)"?\s*$', fm, re.M)
    if m and len(m.group(1)) > 57:
        over.append(f"{p.parent.name}:{len(m.group(1))}")
claim("every description fits the 57-char index window",
      "PROVEN" if not over else "FALSE", f"over: {over or 'none'}")

# ── support-dir claim ────────────────────────────────────────────────────────
# The checkable half: the four names really are excluded from the catalog scan, so
# no SKILL.md hides in one. The other half (that this set matches Hermes' own
# documented set) cannot be read out of this repo, so it is labelled, not asserted —
# an earlier version hardcoded PROVEN here, which broke this script's own contract
# that PROVEN means "checked here, right now".
SUPPORT_DIRS = ("references", "templates", "assets", "scripts")
stray = [p for p in SK.rglob("SKILL.md") if p.parent.name in SUPPORT_DIRS]
claim(f"the catalog scan excludes {'/'.join(SUPPORT_DIRS)}",
      "PROVEN" if not stray else "FALSE",
      f"stray SKILL.md in a support dir: "
      f"{[str(s.relative_to(R)) for s in stray] or 'none'}")
claim("README: that set is the one Hermes documents",
      "UNPROVEN", "Hermes' own docs are outside this repo")

# ── links that resolve ───────────────────────────────────────────────────────
bad_links = []
for doc in [R / "README.md", R / "AGENTS.md", R / "docs" / "upstream.md"]:
    if not doc.is_file():
        bad_links.append(f"MISSING FILE {doc.relative_to(R)}")
        continue
    for _label, target in re.findall(r"\[([^\]]*)\]\(([^)]+)\)", doc.read_text(encoding="utf-8")):
        if target.startswith(("http", "#", "mailto:")):
            continue
        # Strip the `#anchor` before testing the path. A link like
        # `README.md#adding-or-changing-a-skill` is a real file plus a fragment, and
        # testing the raw target reported it broken — a false FALSE, which in a
        # gate that exits non-zero on FALSE is a false alarm, not a caught defect.
        path = target.split("#", 1)[0]
        if not path:
            continue
        if not (doc.parent / path).exists():
            bad_links.append(f"{doc.relative_to(R)} -> {target}")
claim("every relative doc link resolves",
      "PROVEN" if not bad_links else "FALSE", "; ".join(bad_links) or "all resolve")

# ── the token cost the README states ─────────────────────────────────────────
soul = pathlib.Path.home() / ".hermes" / "SOUL.md"
if soul.is_file():
    toks = len(soul.read_text(encoding="utf-8")) // 4
    claim("README: SOUL fragment costs '~500 tokens'",
          "PROVEN" if 450 <= toks <= 550 else "FALSE",
          f"actual: {toks} tokens")

# ── setup.sh claims, executed ────────────────────────────────────────────────
p = subprocess.run([str(R / "setup.sh"), "--check"], capture_output=True, text=True,
                   timeout=120)
# exit 1 is the documented DRIFT code, but it is also what the script returns when
# `hermes` is not on PATH — which is the normal state of a fresh CI runner. Reporting
# that as PROVEN would be a claim passing for a reason it did not establish, so the
# message decides which case this is.
_out = ((p.stderr or "") + (p.stdout or "")).strip()
_reason = _out.splitlines()[-1] if _out else "(no output)"
if p.returncode == 0:
    _verdict, _detail = "PROVEN", "exit=0 — in sync"
elif p.returncode == 1 and "not on PATH" in _reason:
    _verdict = "UNPROVEN"
    _detail = f"exit=1, but for a different reason: {_reason}"
elif p.returncode == 1:
    _verdict, _detail = "PROVEN", f"exit=1 — drift: {_reason}"
else:
    _verdict, _detail = "FALSE", f"exit={p.returncode}: {_reason}"
claim("README: '--check ... exit 1 on drift' (and 0 in sync)", _verdict, _detail)
claim("README: 'setup.sh resolves its own location'",
      "PROVEN" if "BASH_SOURCE" in (R / "setup.sh").read_text() else "FALSE")

# ── the vendored council skill against its source ────────────────────────────
# skills/autonomous-ai-agents/council/ ships a COPY of the council's scripts, and a
# copy drifts — it already has: two files differ from their source and one
# (sync_to_skill.py, the tool that regenerates the copy) is absent entirely. Compare
# them whenever the sibling checkout is present. Resolved from this repo's own
# location, never a hardcoded machine path.
vendored = SK / "autonomous-ai-agents" / "council" / "scripts"
source = R.parent / "review-council" / "scripts"
if not vendored.is_dir():
    claim("the vendored council scripts match their source", "UNPROVEN", "no vendored copy")
elif not source.is_dir():
    claim("the vendored council scripts match their source", "UNPROVEN",
          f"no sibling checkout at {source}")
else:
    drift = [p.name for p in sorted(vendored.glob("*.py"))
             if (source / p.name).is_file() and p.read_bytes() != (source / p.name).read_bytes()]
    absent = [p.name for p in sorted(vendored.glob("*.py")) if not (source / p.name).is_file()]
    claim("the vendored council scripts match their source",
          "PROVEN" if not (drift or absent) else "FALSE",
          f"differ: {drift or 'none'}; no source: {absent or 'none'}")

# ── unprovable from here, and honestly labelled ──────────────────────────────
claim("README: '23 here, 4 there, zero overlap' (the old sync.sh damage)",
      "UNPROVEN", "historical, about machines that no longer exist — keep as narrative, "
                  "not as evidence")
claim("README: 'bundled (~59)'",
      "UNPROVEN", "machine-specific; verify with wc -l .bundled_manifest")

# ── report ───────────────────────────────────────────────────────────────────
order = {"FALSE": 0, "UNPROVEN": 1, "PROVEN": 2}
for v, t, d in sorted(results, key=lambda x: order[x[0]]):
    print(f"{v:8} {t}")
    if d:
        print(f"         {d}")

bad = sum(1 for v, _, _ in results if v == "FALSE")
print(f"\n{len(results)} claims · {bad} false")
sys.exit(1 if bad else 0)
