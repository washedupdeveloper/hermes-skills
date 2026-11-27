#!/usr/bin/env python3
"""Find host-assumption constructs that behave differently per OS.

Run this when a test suite fails on one platform and passes on the others, BEFORE
fixing the specific test. A platform failure is rarely alone: the same assumption is
usually sitting in sibling tests, which fail on the next CI run instead. This prints
every candidate by category so the fix covers the class.

Usage:
    python platform-sweep.py [repo-path] [--roots tests,scripts,src]

Stdlib only, no imports beyond the stdlib, no writes. Exit code is always 0 -- this is
an inventory, not a gate. Read the output; do not wire it into CI as-is, because most
hits are legitimate and a real gate needs per-category judgement.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# (category, regex). Each entry is a host assumption worth a second look, not a bug.
CATEGORIES: list[tuple[str, str]] = [
    ("exec-bit", r"\.chmod\(|os\.chmod|st_mode|0o7[0-7]{2}|X_OK"),
    ("shebang-fixture", r"#!/(?:bin|usr)"),
    ("resolve-vs-raw", r"\.resolve\(\)"),
    ("temp-path", r"/tmp\b|/private/|TMPDIR|gettempdir"),
    ("process-spawn", r"os\.fork|multiprocessing|\bsignal\.|os\.kill|SIGKILL"),
    ("posix-module", r"import (pwd|grp|fcntl|termios|resource)\b|"
                     r"from (pwd|grp|fcntl|termios|resource) import|"
                     r"os\.getuid|os\.geteuid|os\.getgid|os\.getlogin"),
    ("shell-true", r"shell\s*=\s*True"),
    ("separator-literal", r"os\.sep|[^a-z]'\\\\'|\\\\Users|\\\\Temp"),
    ("home-env", r"USERPROFILE|environ\[\s*[\"']HOME[\"']\s*\]"),
    ("symlink-or-copy", r"os\.symlink|os\.readlink|os\.link\(|shutil\.copytree"),
    ("rename-over-target", r"os\.rename|os\.replace|shutil\.move"),
    ("reserved-name", r"\b(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])\b"),
    ("case-compare", r"\.lower\(\)\s*==|==\s*\S+\.lower\(\)|casefold"),
    ("interpreter-name", r"\bpython3\b|sys\.executable"),
    ("gnu-only-flag", r"readlink -f|stat -c|sed -i|date -d|mktemp --tmpdir|grep -P"),
    ("win-execname", r"\.exe\b|\.cmd\b|\.bat\b"),
    ("locale-or-tz", r"tzset|setlocale|LC_ALL|LC_COLLATE"),
    ("newline-write", r"newline\s*=\s*[\"']"),
    ("subprocess", r"subprocess\.(run|Popen|check_output|call)"),
    ("bash4-syntax", r"declare -A|mapfile|readarray|\$\{[A-Za-z_]+,,}|&>"),
]

DEFAULT_ROOTS = ["tests", "scripts", "src", "bots", "skills"]
DEFAULT_EXTS = {".py", ".sh", ".bash", ".nix", ".yml", ".yaml"}


def main() -> int:
    ap = argparse.ArgumentParser(description="Sweep for platform-sensitive constructs.")
    ap.add_argument("repo", nargs="?", default=".", help="repository root")
    ap.add_argument("--roots", default=",".join(DEFAULT_ROOTS),
                    help="comma-separated subdirectories to scan")
    ap.add_argument("--max-per-category", type=int, default=14)
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    roots = [r.strip() for r in args.roots.split(",") if r.strip()]
    compiled = [(name, re.compile(rx)) for name, rx in CATEGORIES]
    hits: dict[str, list[str]] = {name: [] for name, _ in CATEGORIES}
    scanned = 0

    for root in roots:
        base = repo / root
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in DEFAULT_EXTS:
                continue
            if "__pycache__" in path.parts or ".git" in path.parts:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            scanned += 1
            rel = path.relative_to(repo)
            for lineno, line in enumerate(text.splitlines(), 1):
                for name, rx in compiled:
                    if rx.search(line):
                        hits[name].append(f"{rel}:{lineno}  {line.strip()[:100]}")

    print(f"scanned {scanned} files under {repo.name}/{{{','.join(roots)}}}\n")
    total = 0
    for name, _ in CATEGORIES:
        rows = hits[name]
        if not rows:
            continue
        total += len(rows)
        print(f"--- {name}  ({len(rows)})")
        for row in rows[: args.max_per_category]:
            print(f"  {row}")
        if len(rows) > args.max_per_category:
            print(f"  ... {len(rows) - args.max_per_category} more")
        print()

    print(f"total hits: {total}")
    print("\nEach hit is a question, not a defect: does this construct mean the same thing "
          "on macOS and Windows? The ones that do not are the portability bugs.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
