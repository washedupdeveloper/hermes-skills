#!/usr/bin/env python3
"""kb_install.py - deploy the pipeline scripts from this skill to $HERMES_HOME/scripts/.

cron resolves `--script` under $HERMES_HOME/scripts/, but the maintained source
lives in this skill. Two copies deployed by hand `cp` drift silently: you edit the
skill, forget to deploy, and the scheduled job keeps running last week's code.

This makes the deploy explicit and verifiable:

    python scripts/kb_install.py            # deploy, print a hash per file
    python scripts/kb_install.py --check    # deploy nothing; exit 1 if they differ

The skill directory is the single source of truth. Always edit there.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def digest(path: Path) -> str:
    """Content hash with line endings normalised.

    Hashing raw bytes makes every CRLF-vs-LF difference look like a different file —
    the same false-positive class as a byte-exact source hash. A Windows checkout
    re-introduces CRLF, and the check then cries wolf on byte-identical code.
    """
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()[:12]


def content_matches(a: Path, b: Path) -> bool:
    """True when the two files differ only in line endings, if at all."""
    return (a.read_bytes().replace(b"\r\n", b"\n")
            == b.read_bytes().replace(b"\r\n", b"\n"))


def target_dir() -> Path:
    home = os.environ.get("HERMES_HOME")
    return Path(home) if home else Path.home() / ".hermes"


def main() -> int:
    check_only = "--check" in sys.argv
    dest = target_dir() / "scripts"
    dest.mkdir(parents=True, exist_ok=True)
    sources = sorted(HERE.glob("kb_*.py"))
    if not sources:
        print("kb_install: no kb_*.py found next to this script", file=sys.stderr)
        return 1

    drifted, deployed, relined = [], [], []
    for src in sources:
        dst = dest / src.name
        if dst.is_file():
            content_same = content_matches(src, dst)
            bytes_same = src.read_bytes() == dst.read_bytes()
        else:
            content_same = bytes_same = False

        if content_same and bytes_same:
            status = "current"
        elif content_same:
            # Same code, different line endings. That is a checkout artefact, not
            # drift - so it never fails the check. In deploy mode it is still copied,
            # which converges the installed copy onto the repo's LF form.
            relined.append(src.name)
            if check_only:
                status = "current*"
            else:
                shutil.copy2(src, dst)
                status = "normalized"
        elif check_only:
            status = "DRIFT"
            drifted.append(src.name)
        else:
            shutil.copy2(src, dst)
            status = "deployed"
            deployed.append(src.name)
        print(f"  {status:10s} {src.name:18s} {digest(src)}")

    if check_only:
        if drifted:
            print(f"kb_install: {len(drifted)} script(s) differ from the skill copy: "
                  f"{', '.join(drifted)}")
            print("  Run `python scripts/kb_install.py` to deploy, or edit the skill if the "
                  "installed copy is the newer one.")
            return 1
        if relined:
            print(f"kb_install: no drift ({len(relined)} file(s) differ only in line endings: "
                  f"{', '.join(relined)})")
        else:
            print("kb_install: installed copies match the skill (no drift)")
        return 0

    note = f", {len(relined)} re-normalised to LF" if relined else ""
    print(f"kb_install: {len(deployed)} deployed{note}, "
          f"{len(sources) - len(deployed) - len(relined)} already current -> {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
