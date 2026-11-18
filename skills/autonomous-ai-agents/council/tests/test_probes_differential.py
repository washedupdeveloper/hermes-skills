"""Probes: the rewrite against v1, on the same trees, field by field.

A probe is a number with a provenance. If the rewrite computes a different number for the same tree,
one of them is wrong — and on a probe feeding a verdict, "roughly the same" is not a category.

v1 is loaded here as the *reference*, by path, the way the differential uses v1 everywhere else. The
no-import rule binds `reviewc`, not its tests: a test that could not look at the reference could not
compare against it.

Run standalone: python tests/test_probes_differential.py
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from reviewc import probes as rewrite  # noqa: E402

_spec = importlib.util.spec_from_file_location("v1_probes", REPO / "scripts" / "probes.py")
v1 = importlib.util.module_from_spec(_spec)
sys.modules["v1_probes"] = v1
_spec.loader.exec_module(v1)

TOOLS = ("secret-grep", "py-compile", "bash-n", "complexity", "dep-graph", "declared-rules")


def synthetic(root: Path) -> Path:
    """A tree that makes every ported probe say something, so agreement is not agreement on zero."""
    # Twenty nested `if`s: complexity 21, which clears the floor of 15 and is reported as `low`.
    # The first version of this fixture had complexity 12 and proved nothing — which is why the
    # assertion below checks that the finding exists rather than trusting that it should.
    deep = "def tangled(x):\n"
    deep += "".join("    " * (level + 1) + "if x:\n" for level in range(20))
    deep += "    " * 21 + "return 1\n"
    deep += "    return 0\n"
    (root / "app.py").write_text(
        'import json\n\n'
        'API_KEY = "sk-abcdefghijklmnopqrstuvwxyz012345"\n\n' + deep,
        encoding="utf-8")
    (root / "broken.py").write_text("def broken(:\n    pass\n", encoding="utf-8")
    (root / ".env").write_text('password = "hunter2hunter2hunter2"\n', encoding="utf-8")
    (root / "run.sh").write_text("#!/bin/sh\necho ok\n", encoding="utf-8")
    return root


def same(name: str, left, right) -> None:
    assert left.keys() == right.keys(), (name, left.keys(), right.keys())
    for key in left:
        a, b = left[key], right[key]
        if isinstance(a, float) or isinstance(b, float):
            assert a is not None and b is not None, (name, key, a, b)
            assert abs(a - b) < 1e-9, (name, key, a, b)
        else:
            assert a == b, (name, key, a, b)


def test_every_ported_probe_agrees_with_v1_on_a_synthetic_tree():
    with tempfile.TemporaryDirectory() as tmp:
        root = synthetic(Path(tmp))
        for name in TOOLS:
            same(name, v1.PROBES[name](root), rewrite.PROBES[name](root))


def test_every_ported_probe_agrees_with_v1_on_this_repository():
    for name in TOOLS:
        same(name, v1.PROBES[name](REPO), rewrite.PROBES[name](REPO))


def test_the_disagreement_mechanism_is_actually_exercised():
    """A differential on a tree where every probe says 100.0 proves very little."""
    with tempfile.TemporaryDirectory() as tmp:
        root = synthetic(Path(tmp))
        signals = {name: rewrite.PROBES[name](root)["signal"] for name in TOOLS}
    assert signals["py-compile"] < 100.0, signals          # the syntax error was seen
    assert signals["secret-grep"] < 100.0, signals         # the planted key was seen
    assert signals["declared-rules"] == 40.0, signals      # no rules declared
    assert signals["complexity"] < 100.0, signals          # the tangled function was counted
    with tempfile.TemporaryDirectory() as tmp:
        found = rewrite.probe_complexity(synthetic(Path(tmp)))
    assert any("cyclomatic complexity" in f["claim"] for f in found["findings"]), found


def test_a_probe_that_could_not_run_is_absent_not_zero():
    with tempfile.TemporaryDirectory() as tmp:
        root = synthetic(Path(tmp))
        real = rewrite.shutil.which
        rewrite.shutil.which = lambda name: None
        try:
            no_bash = rewrite.probe_bash_n(root)
        finally:
            rewrite.shutil.which = real
    assert no_bash["ran"] is False
    assert no_bash["signal"] is None
    assert rewrite.unexercised([no_bash]) == ["bash-n"]


def test_the_same_tree_twice_gives_the_same_numbers():
    """Determinism is a property, not a hope: the tree is re-walked on every call."""
    with tempfile.TemporaryDirectory() as tmp:
        root = synthetic(Path(tmp))
        first = rewrite.run_all(root)
        second = rewrite.run_all(root)
    assert first == second


if __name__ == "__main__":
    failures = 0
    names = [n for n in sorted(globals()) if n.startswith("test_")]
    for name in names:
        try:
            globals()[name]()
            print(f"ok   {name}")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL {name}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"FAIL {name}: {type(exc).__name__}: {exc}")
    print(f"\n{len(names) - failures} passed, {failures} failed")
    raise SystemExit(1 if failures else 0)
