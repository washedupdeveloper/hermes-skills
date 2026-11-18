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
# The numbers' home is README.md, so the audit PARSES the claim out of it and
# compares it with the tree. An earlier version repeated the expected pair as a
# literal here: adding one skill then failed the audit twice over, because the
# gate carried a second copy of a fact README already owned.
readme = (R / "README.md").read_text(encoding="utf-8")
total = len(list(SK.rglob("SKILL.md")))
catalog = len(skill_files())

m = re.search(r"^(\d+) `SKILL\.md` across (\d+) skills", readme, re.M)
stated = (int(m.group(1)), int(m.group(2))) if m else None
claim(f"README: 'N SKILL.md across N skills' — stated {stated}",
      "PROVEN" if stated == (total, catalog) else "FALSE",
      f"actual: {total} SKILL.md across {catalog} catalog skills")

not_win = [p for p in skill_files()
           if not re.search(r"^platforms:.*windows", p.read_text(encoding="utf-8"),
                            re.M)]
m = re.search(r"(\d+) load on Windows", readme)
stated_win = int(m.group(1)) if m else None
loads = len(skill_files()) - len(not_win)
claim(f"README: 'N load on Windows' — stated {stated_win}",
      "PROVEN" if stated_win == loads else "FALSE",
      f"actual: {loads} load; "
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

# ── the installer the README documents ───────────────────────────────────────
installer = R / "install.sh"
# Bytes, not `read_text`: a shebang claim is about the first bytes of the file, and a
# variable shared with the prose loops above is not the file it claims to describe.
_shebang = installer.read_bytes() if installer.is_file() else b""
claim("README: `./install.sh <dir>` is the installer",
      "PROVEN" if installer.is_file() else "FALSE", f"{installer.relative_to(R)}")
claim("install.sh resolves its own location",
      "PROVEN" if b'dirname -- "$0"' in _shebang else "FALSE")
_first, _ = (_shebang.split(b"\n", 1) + [b""])[:2] if _shebang else (b"", b"")
# `nix/checks.nix` runs `patchShebangs`, which rewrites `#!/bin/sh` to a store path, so
# the claim is about the interpreter being `sh` and not `bash` — true before and after.
_interp = _first[2:].rsplit(b"/", 1)[-1] if _first.startswith(b"#!") else b""
# The *basename* of the interpreter, because a patched shebang points into the bash
# store path while still running `sh`.
claim("install.sh is POSIX sh, not bash",
      "PROVEN" if _interp == b"sh" else "FALSE",
      _first.decode("utf-8", "replace") or "no shebang")

# ── unprovable from here ────────────────────────────────────────────────────
# Empty on purpose, and worth explaining rather than leaving bare. Three claims lived here:
#
#   * "that set is the one Hermes documents" quoted a README sentence that no longer exists
#     (`grep documents README.md` has no match) — a ghost claim, deleted;
#   * "23 here, 4 there, zero overlap" counted skills on two machines that no longer exist;
#   * "bundled (~59)" counted an installed Hermes' bundled set, which this clone cannot see.
#
# The first was stale. The other two were removed from the README rather than left as numbers
# no clone can settle: a claim that cannot be measured should not be stated as a figure. The
# `UNPROVEN` verdict stays in the vocabulary for the next honest limitation.

# ── report ───────────────────────────────────────────────────────────────────
order = {"FALSE": 0, "UNPROVEN": 1, "PROVEN": 2}
for v, t, d in sorted(results, key=lambda x: order[x[0]]):
    print(f"{v:8} {t}")
    if d:
        print(f"         {d}")

bad = sum(1 for v, _, _ in results if v == "FALSE")
print(f"\n{len(results)} claims · {bad} false")
sys.exit(1 if bad else 0)
