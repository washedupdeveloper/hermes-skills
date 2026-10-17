#!/usr/bin/env python3
"""Verify this repo's skills against a REAL Hermes install.

    python3 scripts/verify-live.py

Everything else in the gate is a property of the tree. This is the only check
that asks the product itself, so it is the one that proves the tree is loadable
rather than merely well-formed:

  * Hermes discovers every catalog skill this repo ships -- the count in the
    README is the count `hermes skills list` reports, not a number derived by a
    script that agrees with itself.
  * Every skill is enabled, i.e. its frontmatter parsed in the real parser.
  * A skill whose slash command is shadowed by a built-in is reported, because
    the skill still works but its short form does not.

It runs against a throwaway `HERMES_HOME` containing a COPY of `skills/`, so it
cannot read, write or disturb the caller's own profile. Exit 1 on any failure.

Why a copy is right here and wrong elsewhere: Hermes reads `external_dirs` in
place, so the repo needs no installer -- but a test must not depend on the
caller's live library, where a same-named local skill would shadow the repo and
make the result a statement about their machine instead of this tree.
"""
from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
SKILLS = REPO / "skills"
SUPPORT = ("references", "templates", "assets", "scripts")

# `hermes skills list` renders a table; a row starts with the skill name. The
# width is whatever the terminal is, so match the leading cell only.
ROW = re.compile(r"^\S*\s*│\s*(\S+)\s*│\s*(\S+)\s*│")

# A skill name is a slug. Continuation rows of a multi-line status cell carry a
# box character in the name column, and counting one would inflate the total.
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def catalog_skills() -> dict[str, str | None]:
    """This repo's catalog skills, and the `environments:` gate each declares.

    The gate is Hermes' own: `environments:` is an offer-time relevance filter
    (`agent/skill_utils.py:skill_matches_environment`), so a skill declaring
    `[s6]` is deliberately absent from the list outside that environment. That is
    correct behaviour, and a check that ignored it would fail on every host that
    is not the one the skill is for.
    """
    out: dict[str, str | None] = {}
    for path in sorted(SKILLS.rglob("SKILL.md")):
        if any(f"/{s}/" in path.as_posix() for s in SUPPORT):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        gate = None
        m = re.search(r"^environments:\s*(.+)$", text, re.M)
        if m:
            gate = m.group(1).strip()
        out[path.parent.name] = gate
    return out


def run(hermes: str, home: pathlib.Path, *args: str) -> str:
    env = dict(os.environ, HERMES_HOME=str(home))
    proc = subprocess.run(
        [hermes, *args], capture_output=True, text=True, env=env, timeout=300
    )
    return proc.stdout + proc.stderr


def main() -> int:
    hermes = shutil.which("hermes")
    if not hermes:
        print("SKIP: no `hermes` on PATH -- this check needs the real product", file=sys.stderr)
        return 2

    failures: list[str] = []
    catalog = catalog_skills()
    if not catalog:
        print("FAIL: found no catalog skills to verify", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory() as tmp:
        home = pathlib.Path(tmp)
        shutil.copytree(SKILLS, home / "skills")

        version = run(hermes, home, "--version").strip().splitlines()
        print(f"hermes: {version[0] if version else '(no version)'}")

        listing = run(hermes, home, "skills", "list")
        # The table is box-drawn and the name column truncates with an ellipsis,
        # so a TRUNCATED listed name is a prefix of the real one. The comparison
        # must allow that direction and no other: `x.startswith(n)` would let a
        # skill renamed to `caveman-renamed` satisfy `caveman`, which is the
        # exact drift this check exists to catch.
        listed: list[str] = []
        for line in listing.splitlines():
            m = ROW.match(line)
            if not m:
                continue
            name = m.group(1)
            if not SLUG.match(name.rstrip("…")):
                continue
            listed.append(name)

        def discovered(name: str) -> bool:
            return any(
                x == name
                or (x.endswith("…") and name.startswith(x.rstrip("…")))
                for x in listed
            )

        # A skill gated on an environment this host is not in is EXPECTED to be
        # absent; only an ungated skill that Hermes does not list is a failure.
        expected = {n for n, gate in catalog.items() if gate is None}
        gated = {n: gate for n, gate in catalog.items() if gate is not None}

        missing = sorted(n for n in expected if not discovered(n))
        if missing:
            failures.append(f"not discovered by hermes: {missing}")

        # ...and a gated skill that IS listed means the gate did not apply, which
        # would make `environments:` decorative.
        wrongly_offered = sorted(n for n in gated if discovered(n))
        if wrongly_offered:
            failures.append(
                f"gated by `environments:` but offered anyway: {wrongly_offered}"
            )

        # A count cross-check in both directions: a name that a truncation makes
        # ambiguous could hide a swap, and a duplicate could hide a missing one.
        if len(listed) != len(expected) + len(wrongly_offered):
            failures.append(
                f"hermes lists {len(listed)} skills, {len(expected)} are expected to load"
            )

        disabled = [
            line.strip()
            for line in listing.splitlines()
            if "│" in line and "disabled" in line
        ]
        if disabled:
            failures.append(f"skills hermes reports as disabled: {disabled}")

        # A slash command shadowed by a built-in is not a failure of the skill --
        # it still loads and still answers `/skill <name>` -- but it is a real
        # usability fact about the tree, so it is reported, not swallowed.
        shadowed = []
        for line in listing.splitlines():
            if "name taken by built-in" in line:
                shadowed.append(line.strip())

        print(f"catalog skills in this repo : {len(catalog)}")
        print(f"expected to load on this host: {len(expected)}")
        print(f"discovered by hermes        : {len(listed)}")
        if gated:
            print(f"environment-gated (correctly hidden): {len(gated)}")
            for n, gate in sorted(gated.items()):
                print(f"  {n}: {gate}")
        if shadowed:
            print(f"slash command shadowed      : {len(shadowed)}")
            for s in shadowed:
                print(f"  {s}")

        if failures:
            for f in failures:
                print(f"FAIL: {f}", file=sys.stderr)
            return 1

    print("OK: every catalog skill loads in the real Hermes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
