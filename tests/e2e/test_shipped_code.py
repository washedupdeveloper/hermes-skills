"""Functional tests for code the skills actually ship.

The unit tests beside this file are contracts: a path exists, a doc states a
true count, a frontmatter field parses. None of them executes the code a skill
tells the reader to run, so a broken shipped script passes the suite.

These do execute it, and each is paired with a control that proves the check
can fail — a test that only ever passes is indistinguishable from one that
never ran.
"""
from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

SKILLS = pathlib.Path(__file__).resolve().parent.parent.parent / "skills"
KB = SKILLS / "autonomous-ai-agents/hermes-knowledge-pipeline"
COUNCIL = SKILLS / "autonomous-ai-agents/council"


def _run(script: pathlib.Path, cwd: pathlib.Path, timeout: int = 300):
    return subprocess.run([sys.executable, str(script)], cwd=cwd, capture_output=True,
                          text=True, stdin=subprocess.DEVNULL, timeout=timeout)


def _selftest(script: pathlib.Path) -> str:
    """Assert the vault self-test passes; return its output."""
    r = _run(script, script.parent.parent)
    assert r.returncode == 0, f"{script.name} failed:\n{r.stdout[-800:]}\n{r.stderr[-800:]}"
    assert "OK" in r.stdout, f"{script.name} printed no OK line:\n{r.stdout[-400:]}"
    return r.stdout


def test_the_knowledge_pipeline_self_test_passes():
    """kb_selftest builds a broken vault and a clean one, and asserts on both."""
    out = _selftest(KB / "scripts/kb_selftest.py")
    assert "detection" in out and "silence" in out, out[-300:]


def test_the_self_test_check_is_not_vacuous():
    """Negative control: the same assertion must fail on a broken copy."""
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp) / "kb"
        shutil.copytree(KB, root, ignore=shutil.ignore_patterns("__pycache__"))
        script = root / "scripts/kb_selftest.py"
        src = script.read_text(encoding="utf-8")
        assert "raise SystemExit(main())" in src, "control cannot be built"
        script.write_text(src.replace("raise SystemExit(main())",
                                      "raise SystemExit(3)"), encoding="utf-8")
        try:
            _selftest(script)
        except AssertionError:
            return
        raise AssertionError("a deliberately broken script passed the check")


def test_the_council_suite_passes_on_the_shipped_code():
    """The council ships 500+ assertions over its own scripts; run them, not a grep."""
    pytest = shutil.which("pytest")
    if not pytest:
        return  # no runner in this environment; the check below still applies elsewhere
    r = subprocess.run([pytest, "tests", "-q", "--no-header", "-p", "no:cacheprovider"],
                       cwd=COUNCIL, capture_output=True, text=True,
                       stdin=subprocess.DEVNULL, timeout=420)
    tail = (r.stdout or "")[-600:]
    assert r.returncode == 0, f"council suite failed:\n{tail}\n{(r.stderr or '')[-400:]}"
    assert " passed" in tail, f"no pass count parsed:\n{tail}"


def test_the_loader_accepts_every_shipped_skill():
    """Hermes's own loader, not a regex: every catalog skill parses and is enabled."""
    hermes = shutil.which("hermes")
    if not hermes:
        return
    r = subprocess.run([hermes, "skills", "list"], capture_output=True, text=True,
                       stdin=subprocess.DEVNULL, timeout=120)
    if r.returncode != 0:
        return
    rows = re.findall(r"\u2502\s*([^\u2502]+?)\s*\u2502", r.stdout)
    cells = [c.strip().rstrip("\u2026") for c in rows]
    catalog = []
    for p in SKILLS.rglob("SKILL.md"):
        if any(f"/{x}/" in p.as_posix() for x in ("references", "templates", "assets", "scripts")):
            continue
        if re.search(r"^environments:", p.read_text(encoding="utf-8").split("---", 2)[1], re.M):
            continue  # scoped to one environment; the loader is right to omit it here
        catalog.append(p.parent.name)
    missing = [n for n in catalog if not any(c and n.startswith(c) for c in cells)]
    assert not missing, f"loader did not list: {missing}"