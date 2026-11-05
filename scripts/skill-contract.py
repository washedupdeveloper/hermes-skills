#!/usr/bin/env python3
"""skill-contract.py — validate the skill tree against library/contract.json.

The same function the runtime guard calls, so the tree gate and the hook cannot disagree about
what a valid skill is. The gate runs `--all`; a human or an agent runs `--check <path>` on one file.

    python scripts/skill-contract.py --all
    python scripts/skill-contract.py --check skills/devops/ephemeral-cleanup/SKILL.md
    python scripts/skill-contract.py --print          # the contract, as loaded

Exit 1 on any violation; exit 2 when the scan found no skills (a scan over nothing passes, and
would look identical to a clean tree).
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MODULE = REPO / "plugins/library-guard/library_guard.py"


def _guard():
    spec = importlib.util.spec_from_file_location("library_guard", MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def catalog(guard, repo: Path) -> list[Path]:
    """Every catalog SKILL.md: two levels under skills/, never inside a support directory."""
    support = set(guard.contract()["support_dirs"])
    found = []
    for path in sorted(repo.glob("skills/*/*/SKILL.md")):
        relative = path.relative_to(repo / "skills")
        if support & set(relative.parts[1:-1]):
            continue  # assets/, references/ … shipped with a skill, not a skill
        found.append(path)
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--all", action="store_true", help="scan every catalog skill")
    parser.add_argument("--check", metavar="PATH", help="validate one SKILL.md")
    parser.add_argument("--print", action="store_true", help="print the contract as loaded")
    args = parser.parse_args(argv)

    guard = _guard()

    if args.print:
        import json

        print(json.dumps(guard.contract(), indent=2, sort_keys=True))
        return 0

    if args.check:
        path = Path(args.check).resolve()
        if not path.is_file():
            print(f"skill-contract: no such file: {path}", file=sys.stderr)
            return 2
        targets = [path]
    elif args.all:
        targets = catalog(guard, REPO)
        if not targets:
            print("skill-contract: the scan found no skills — the tree is not where this expects it", file=sys.stderr)
            return 2
    else:
        parser.error("one of --all, --check or --print")

    violations = 0
    for path in targets:
        text = path.read_text(encoding="utf-8", errors="replace")
        for violation in guard.check_skill_text(text, path.parent.name):
            violations += 1
            print(f"{path.relative_to(REPO)}: {violation}")

    print(f"skill-contract: {len(targets)} skill(s), {violations} violation(s)")
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())