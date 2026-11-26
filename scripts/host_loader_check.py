#!/usr/bin/env python3
"""The host half: an installed Hermes lists every shipped skill.

This is not a test. A test states something about the tree; this asks the machine you
are sitting at to read the tree. A machine without Hermes cannot answer, so in the gate
it could only skip — a pass that measured nothing — or fail on every machine that does
not ship Hermes. Both are wrong, so it lives here and is run by hand where it applies:

    python scripts/host_loader_check.py

Exit 0 when every shipped skill is listed, 1 when one is missing or Hermes is absent.
"""
from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
import sys

SKILLS = pathlib.Path(__file__).resolve().parent.parent / "skills"


def main() -> int:
    hermes = shutil.which("hermes")
    if not hermes:
        print("no `hermes` on PATH; nothing to measure")
        return 1
    result = subprocess.run(
        [hermes, "skills", "list"], capture_output=True, text=True,
        stdin=subprocess.DEVNULL, timeout=120,
    )
    if result.returncode != 0:
        print(f"`hermes skills list` exited {result.returncode}")
        return 1
    rows = re.findall(r"\u2502\s*([^\u2502]+?)\s*\u2502", result.stdout)
    cells = [cell.strip().rstrip("\u2026") for cell in rows]
    catalog = []
    for path in SKILLS.rglob("SKILL.md"):
        if any(f"/{part}/" in path.as_posix() for part in ("references", "templates", "assets", "scripts")):
            continue
        if re.search(r"^environments:", path.read_text(encoding="utf-8").split("---", 2)[1], re.M):
            continue  # scoped to one environment; the loader is right to omit it here
        catalog.append(path.parent.name)
    missing = [name for name in catalog if not any(cell and name.startswith(cell) for cell in cells)]
    if missing:
        print(f"loader did not list: {missing}")
        return 1
    print(f"loader listed all {len(catalog)} shipped skill(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())