"""Tests for probes.py — the deterministic checks.

Run standalone (no pytest needed):
    python tests/test_probes.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("probes", REPO / "scripts" / "probes.py")
probes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(probes)


# --- output parsing ---------------------------------------------------------
#
# This is the bug that mattered: statix pretty-prints each JSON object across
# many lines, deadnix emits one object per line. A line-based parser works for
# one and silently returns ZERO for the other — a false clean bill of health on a
# file that does not even parse.

def test_parses_deadnix_jsonl():
    """deadnix: one object per line."""
    text = (
        '{"file":"./a.nix","results":[{"line":1,"column":3,"message":"Unused lambda pattern: x"}]}\n'
        '{"file":"./b.nix","results":[{"line":4,"column":3,"message":"Unused let binding: y"}]}\n'
    )
    objs = probes._json_objects(text)
    assert len(objs) == 2, objs
    assert objs[0]["file"] == "./a.nix"
    assert objs[1]["results"][0]["line"] == 4


def test_parses_statix_pretty_printed():
    """statix: objects pretty-printed across many lines, concatenated."""
    text = json.dumps({
        "file": "./broken.nix",
        "report": [{
            "note": "Syntax error", "severity": "Error",
            "diagnostics": [{"at": {"from": {"line": 1, "column": 8}},
                             "message": "Unexpected TOKEN_IDENT"}],
        }],
    }, indent=2) + "\n" + json.dumps({
        "file": "./ok.nix", "report": [],
    }, indent=2)
    objs = probes._json_objects(text)
    assert len(objs) == 2, objs
    assert objs[0]["file"] == "./broken.nix"
    diag = objs[0]["report"][0]["diagnostics"][0]
    assert diag["at"]["from"]["line"] == 1


def test_parser_ignores_noise():
    """Non-JSON banner lines must not break parsing."""
    text = 'warning: something\n{"file":"./a.nix","results":[]}\ntrailing garbage'
    objs = probes._json_objects(text)
    assert len(objs) == 1
    assert objs[0]["file"] == "./a.nix"


# --- built-in probes --------------------------------------------------------

def test_secret_grep_finds_a_credential():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "conf.py").write_text(
            'API_KEY = "inf_9f4c2b7e1a8d6350b2c4e6f8a0d1c3e5"\n', encoding="utf-8")
        out = probes.probe_secret_grep(root)
        assert out["ran"] is True
        assert len(out["findings"]) >= 1
        assert out["signal"] < 100


def test_secret_grep_ignores_examples():
    """A secret-shaped string in docs/examples must not fire (SNR matters)."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "examples").mkdir()
        (root / "examples" / "conf.py").write_text(
            'API_KEY = "inf_9f4c2b7e1a8d6350b2c4e6f8a0d1c3e5"\n', encoding="utf-8")
        out = probes.probe_secret_grep(root)
        assert out["findings"] == [], out["findings"]


def test_py_compile_catches_syntax_error():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "ok.py").write_text("x = 1\n", encoding="utf-8")
        (root / "bad.py").write_text("def f(:\n", encoding="utf-8")
        out = probes.probe_py_compile(root)
        assert out["ran"] is True
        assert len(out["findings"]) == 1
        assert out["findings"][0]["severity"] == "critical"
        assert "bad.py" in out["findings"][0]["location"]["path"]


def test_complexity_flags_a_hotspot():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        body = "def tangled(x):\n" + "".join(
            f"    if x == {i}:\n        x += {i}\n" for i in range(20)) + "    return x\n"
        (root / "t.py").write_text(body, encoding="utf-8")
        out = probes.probe_complexity(root)
        assert out["ran"] is True
        assert len(out["findings"]) >= 1
        assert "complexity" in out["findings"][0]["claim"]


def test_declared_rules_scores_absence():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        out = probes.probe_declared_rules(root)
        assert out["ran"] is True
        assert out["signal"] < 100
        assert len(out["findings"]) == 1
        (root / "AGENTS.md").write_text("# rules\n", encoding="utf-8")
        out2 = probes.probe_declared_rules(root)
        assert out2["signal"] == 100.0
        assert out2["findings"] == []


# --- nix probes: honest degradation -----------------------------------------
#
# When the toolchain is unavailable every nix probe must report ran=False. It
# must NEVER invent a result — claiming ran=True would inflate beta.

def test_nix_probes_degrade_without_nix():
    """When the toolchain cannot resolve, every nix probe reports ran=False and
    must NEVER invent a result — claiming ran=True would inflate beta."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "flake.nix").write_text("{ outputs = { self }: {}; }\n", encoding="utf-8")
        (root / "a.nix").write_text("{ x = 1; }\n", encoding="utf-8")
        original = probes._bridge
        probes._bridge = lambda *a, **k: (127, "toolchain unavailable (test)")
        try:
            for name in ("statix", "deadnix", "nixfmt", "flake-check", "nix-eval"):
                out = probes.run_probe(name, root)
                assert out["ran"] is False, f"{name} claimed to run without a toolchain"
                assert out["parsed"] is False, name
                assert out["findings"] == [], f"{name} invented findings while not running"
                assert out["signal"] is None, f"{name} produced a signal while not running"
        finally:
            probes._bridge = original


def test_probe_with_no_nix_files_reports_not_run():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)  # no .nix files at all
        for name in ("statix", "deadnix", "nixfmt", "nix-eval"):
            out = probes.run_probe(name, root)
            assert out["ran"] is False, f"{name} claimed to run with no .nix files"
            assert out["parsed"] is False


def test_run_probe_never_raises():
    """A broken probe must not break the run."""
    out = probes.run_probe("does-not-exist", Path("."))
    assert out["ran"] is False
    assert "unknown probe" in out["note"]


# --- python probes: the same honest degradation ------------------------------
#
# The gate EXPECTED ruff, mypy, bandit, a dependency scanner and pytest, and left
# them to the reviewer -- so beta measured the reviewer's diligence on the Python
# side while being deterministic on the Nix side. They are harness probes now, and
# a probe that cannot run must say so rather than let the reviewer's report stand
# in for a measurement.

def test_python_probes_degrade_without_a_toolchain():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "a.py").write_text("x = 1\n", encoding="utf-8")
        # A lockfile, so the dependency probe has something to audit and therefore
        # actually needs the toolchain. With no dependencies at all it reports
        # "nothing to audit" without invoking anything -- a correct answer that
        # does not require osv-scanner to exist.
        (root / "requirements.txt").write_text("requests==2.31.0\n", encoding="utf-8")
        original = probes._bridge
        probes._bridge = lambda *a, **k: (127, "toolchain unavailable (test)")
        try:
            for name in ("ruff", "mypy", "bandit", "pytest", "osv-scanner"):
                out = probes.run_probe(name, root)
                assert out["ran"] is False, f"{name} claimed to run without a toolchain"
                assert out["parsed"] is False, name
                assert out["findings"] == [], f"{name} invented findings while not running"
                assert out["signal"] is None, f"{name} produced a signal while not running"
        finally:
            probes._bridge = original


def test_every_expected_tool_has_a_probe():
    """The asymmetry this closes: a tool the gate EXPECTS that no probe runs can
    only ever be satisfied by the reviewer's own report. That is what made beta a
    measure of diligence on the Python side and of the toolchain on the Nix side."""
    expected = {
        "statix", "deadnix", "nixfmt", "flake-check", "nix-eval", "nix-eval-time",
        "ruff", "mypy", "bandit", "osv-scanner", "pytest",
        "secret-grep", "py-compile", "complexity", "dep-graph", "declared-rules",
    }
    missing = sorted(expected - set(probes.PROBES))
    assert missing == [], f"the gate expects tools that no probe runs: {missing}"


def test_parser_accepts_a_top_level_json_array():
    """ruff emits ONE array; statix and deadnix emit concatenated objects. One
    parser has to read both, or a tool's entire output parses as zero findings --
    a false clean bill of health."""
    text = json.dumps([{"code": "F401", "filename": "a.py",
                        "location": {"row": 3}, "message": "unused import"}])
    objs = probes._json_objects(text)
    assert len(objs) == 1, objs
    assert objs[0]["code"] == "F401"


def test_osv_scanner_separates_nothing_to_audit_from_cannot_audit():
    """No dependencies and unreadable dependencies are different facts, and only
    one of them is clean. Reporting the second as clean would hide unaudited risk
    behind a 100."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        out = probes.probe_osv_scanner(root)
        assert out["ran"] is True
        assert out["signal"] == 100.0
        assert "no dependencies declared" in out["note"]

        (root / "pyproject.toml").write_text(
            '[project]\nname = "x"\ndependencies = ["requests>=2"]\n', encoding="utf-8")
        out2 = probes.probe_osv_scanner(root)
        assert out2["ran"] is False, "declared-but-unreadable deps reported as clean"
        assert out2["signal"] is None
        assert "lockfile" in out2["note"]


def test_pytest_exit_5_is_not_run_not_pass():
    """Exit 5 is 'no tests collected' -- not a pass and not a failure. Calling it
    a pass would let a repository with no tests score full marks on correctness."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "a.py").write_text("x = 1\n", encoding="utf-8")
        original = probes._bridge
        probes._bridge = lambda *a, **k: (5, "no tests ran in 0.01s")
        try:
            out = probes.run_probe("pytest", root)
            assert out["ran"] is False
            assert out["signal"] is None
        finally:
            probes._bridge = original


def test_signal_is_a_density_not_a_count():
    """§6 applies the Hill curve to findings per KLOC. Feeding it a raw count
    scored a 14 KLOC repository's 16 findings as 16 per KLOC. Survivable while
    beta < 1 let the reviewer's score dominate; at beta = 1 the probe signal IS
    the score, so the miscalibration decides verdicts and penalises size."""
    with tempfile.TemporaryDirectory() as td:
        small, big = Path(td) / "small", Path(td) / "big"
        small.mkdir()
        big.mkdir()
        # The same 20 findings, in a tree 100x larger: a far lower density.
        for root, modules in ((small, 20), (big, 2000)):
            for i in range(modules):
                (root / f"m{i}.py").write_text("x = 1\n", encoding="utf-8")
        assert probes.score_from_density(20, small) < probes.score_from_density(20, big)


def test_density_falls_back_to_a_count_with_no_measurable_size():
    """You cannot normalise by a size you have not measured -- and the fallback
    must match score_reviews' so the two never disagree."""
    assert probes.score_from_density(16, None) == probes.score_from_density(16, Path("/nonexistent-rc"))
    assert probes.score_from_density(0, None) == 100.0


def main() -> int:
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    passed = failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS {name}")
            passed += 1
        except AssertionError as exc:
            print(f"  FAIL {name} -> {exc}")
            failed += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  ERROR {name} -> {type(exc).__name__}: {exc}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
