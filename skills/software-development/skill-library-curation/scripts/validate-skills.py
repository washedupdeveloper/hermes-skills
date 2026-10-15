#!/usr/bin/env python3
"""Validate SKILL.md frontmatter across one or more skill trees.

Checks the properties that break loading or discoverability:
  * frontmatter starts at byte 0 and closes with ---
  * required fields present
  * description <= 60 chars and ends with a period
  * `name` matches the containing directory
  * related_skills entries resolve to a skill in ANY tree given

Stdlib only, so it runs under any Python without a YAML dependency.

Usage:
    python validate-skills.py <skills-root> [<skills-root> ...]
    python validate-skills.py --quiet <skills-root>

Under the mounted model this repo holds only locally-authored skills, while
bundled skills live in $HERMES_HOME/skills. A repo skill may legitimately
reference one, so pass both roots:

    python validate-skills.py skills "$HERMES_HOME/skills"

Exit 0 = all valid, 1 = problems found, 2 = bad usage.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REQUIRED = ("name", "description", "version", "author", "license", "platforms")
DESC_MAX = 60


def _frontmatter(path: Path):
    """Return (fields, body, problems). fields is a flat str->str mapping."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}, text, ["frontmatter must start at byte 0 with ---"]
    m = re.search(r"\n---\s*\n", text[3:])
    if not m:
        return {}, text, ["no closing --- before the body"]
    raw = text[3:m.start() + 3]
    body = text[m.end() + 3:]
    fields = {}
    for line in raw.splitlines():
        mm = re.match(r"^([a-z_]+):\s*(.*)$", line)
        if mm:
            fields[mm.group(1)] = mm.group(2).strip().strip('"').strip("'")
    return fields, raw + "\n" + body, ([] if body.strip() else ["empty body"])


def _related(raw: str):
    """related_skills is usually nested under metadata.hermes — regex it out."""
    m = re.search(r"related_skills:\s*\[([^\]]*)\]", raw)
    if not m:
        return []
    return [x.strip().strip('"').strip("'") for x in m.group(1).split(",") if x.strip()]


def check_tree(root: Path, quiet: bool = False, known: set | None = None) -> int:
    files = sorted(root.rglob("SKILL.md"))
    if not files:
        print(f"no SKILL.md under {root}", file=sys.stderr)
        return 2
    names = {p.parent.name for p in files}
    # Resolve against the UNION of every root given. A repo-only run cannot see
    # the bundled skills this repo's skills reference, so without this every such
    # reference reports as broken and the check becomes noise.
    resolvable = names | (known or set())
    failures = 0

    for path in files:
        fields, raw, problems = _frontmatter(path)
        desc = fields.get("description", "")

        for field in REQUIRED:
            if field not in fields:
                problems.append(f"missing '{field}'")
        if len(desc) > DESC_MAX:
            problems.append(f"description is {len(desc)} chars (max {DESC_MAX})")
        if desc and not desc.endswith("."):
            problems.append("description does not end with a period")
        if fields.get("name") and fields["name"] != path.parent.name:
            problems.append(
                f"name '{fields['name']}' != directory '{path.parent.name}'")
        for ref in _related(raw):
            if ref not in resolvable:
                problems.append(f"related_skills '{ref}' does not resolve")

        if problems:
            failures += 1
            print(f"FAIL {path.parent.name}")
            for p in problems:
                print(f"       {p}")
        elif not quiet:
            print(f"OK   {path.parent.name}  (desc {len(desc)})")

    total = len(files)
    print(f"\n{total - failures}/{total} valid under {root}")
    return 1 if failures else 0


def main(argv):
    args = [a for a in argv if a != "--quiet"]
    quiet = "--quiet" in argv
    if not args:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    roots = [Path(a).expanduser() for a in args]
    # The union is computed across ALL roots before any is checked, so a
    # reference is judged against the whole library rather than one slice of it.
    known: set = set()
    for r in roots:
        known |= {p.parent.name for p in r.rglob("SKILL.md")}
    rc = 0
    for r in roots:
        rc |= check_tree(r, quiet=quiet, known=known)
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
