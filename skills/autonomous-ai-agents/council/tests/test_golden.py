"""Tests for the golden end-to-end regression suite (M8).

M8's acceptance criterion is that the suite "catches a deliberate rubric/weight
regression". These tests are that criterion, executed: each one mutates one
scoring input, asserts the golden check FAILS, then restores it and asserts the
check passes again. A regression suite nobody has watched fail is a suite that
passes for the wrong reason.

Run standalone (no pytest needed):
    python tests/test_golden.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("golden", REPO / "scripts" / "golden.py")
golden = importlib.util.module_from_spec(spec)
spec.loader.exec_module(golden)


class _restore:
    """Mutate a dict (or attribute) for the duration of a block, then put it back.

    Written as a context manager so a failed assertion cannot leave the module
    mutated for every test that runs after it -- which would turn one real failure
    into a cascade of confusing ones.
    """

    def __init__(self, target, key, value):
        self.target, self.key, self.value = target, key, value

    def __enter__(self):
        self.had = self.key in self.target
        self.old = self.target.get(self.key)
        self.target[self.key] = self.value
        return self

    def __exit__(self, *exc):
        if self.had:
            self.target[self.key] = self.old
        else:
            del self.target[self.key]
        return False


# --- it passes on an unmodified tree ---------------------------------------

def test_the_golden_check_passes_on_the_committed_fixtures():
    assert golden.check(quiet=True) == 0


def test_expect_json_is_present_and_records_its_inputs():
    """A pinned value with no record of its inputs cannot be audited: you cannot
    tell a fixture edit from a scoring change."""
    payload = json.loads(golden.EXPECT.read_text(encoding="utf-8"))
    assert payload["inputs"], "expect.json must record the fixture hashes"
    assert payload["threshold"] > 0
    assert set(payload["rounds"]) == {"clean", "defects"}, sorted(payload["rounds"])
    assert "two-samples" in payload["merges"]


# --- the acceptance criterion: it catches deliberate regressions ------------

def test_it_catches_a_dimension_weight_regression():
    scorer = golden._scorer()
    with _restore(scorer.WEIGHTS, "security", 0.99):
        assert golden.check(quiet=True) == 1, "a reweighted dimension must fail"
    assert golden.check(quiet=True) == 0, "and restoring must pass"


def test_it_catches_a_severity_weight_regression():
    """The rubric-side weight. `info` is 0 by design -- reweighting it off zero
    silently turns 'verified clean' notes into findings."""
    scorer = golden._scorer()
    with _restore(scorer.SEVERITY_WEIGHT, "info", 1.0):
        assert golden.check(quiet=True) == 1, "reweighting info must fail"
    assert golden.check(quiet=True) == 0


def test_it_catches_a_tool_table_regression():
    """STACK_TOOLS is the beta denominator. Removing a tool it expects changes
    beta, and beta is the blend weight on the deterministic half.

    The defects round's security dimension deliberately reports only `statix` of
    its two expected tools, so beta there is 0.5 and the table's contents are
    observable. With both tools reported this mutation would be invisible -- beta
    is 1.0 either way -- which is why the fixture is partial on purpose.
    """
    scorer = golden._scorer()
    with _restore(scorer.STACK_TOOLS["security"], "nix", ["statix"]):
        assert golden.check(quiet=True) == 1, "a changed tool table must fail"
    assert golden.check(quiet=True) == 0


def test_it_catches_a_calibration_regression():
    """The Hill curve as actually used.

    NOT HILL_K: when calibration.json is present, `hill_density` takes both the
    steepness (`halflife_k`) and the anchor (`d_star`) from the manifest, so the
    HILL_K constant is dead on a calibrated checkout. Mutating it changes nothing,
    which is how this test came to be written against the manifest instead.
    """
    scorer = golden._scorer()
    manifest = scorer.load_calibration()
    assert manifest, "the fixture is scored against the shipped calibration"
    with _restore(manifest, "halflife_k", 2.5):
        assert golden.check(quiet=True) == 1, "a changed Hill curve must fail"
    assert golden.check(quiet=True) == 0


def test_it_catches_a_d_star_regression():
    """d* is the density that scores 50, so moving the anchor moves every density
    term.

    Mutates `complexity`, not `statix`: `hill_density` pools d* over the tools with
    a REAL baseline reading and excludes the floored ones, because most tools find
    nothing on clean code and the median over all of them collapses to the floor.
    `statix` is floored, so changing its d* is deliberately inert.
    """
    scorer = golden._scorer()
    table = scorer.load_calibration()["d_star"]
    assert not table["complexity"]["floored"], "the pooled anchor must be a real reading"
    with _restore(table["complexity"], "d_star", 5.0):
        assert golden.check(quiet=True) == 1, "a moved d* must fail"
    assert golden.check(quiet=True) == 0


def test_it_catches_a_loss_of_the_invocation_aliases():
    """The specific bug this suite was built after: without the alias table,
    `nix flake check` never resolves to the expected tool `flake-check`, so the
    reviewer runs the check and beta cannot see it."""
    scorer = golden._scorer()
    original = scorer._INVOCATION_ALIASES
    try:
        scorer._INVOCATION_ALIASES = tuple(
            (inv, canonical) for inv, canonical in original
            if canonical != "flake-check")
        assert golden.check(quiet=True) == 1, "losing the alias must fail"
    finally:
        scorer._INVOCATION_ALIASES = original
    assert golden.check(quiet=True) == 0


def test_it_catches_a_threshold_regression():
    """The threshold decides pass/fail, so a drift in the calibrated value is the
    most consequential change of all."""
    scorer = golden._scorer()
    original = scorer.calibrated_threshold
    try:
        scorer.calibrated_threshold = lambda: 50.0
        assert golden.check(quiet=True) == 1, "a moved threshold must fail"
    finally:
        scorer.calibrated_threshold = original
    assert golden.check(quiet=True) == 0


# --- the CLI, which is what CI runs ----------------------------------------
#
# These spawn the module as a PROCESS, which is a hand-run as far as the module
# can tell: `scripts/golden.py` refuses to execute unless the dispatcher set
# REVIEW_COUNCIL_DISPATCHED. The test IS the dispatcher here, so it says so —
# exactly as council.py does, and for the same reason: the guard must not have a
# hole just because a caller happens to be Python.

def _as_dispatcher():
    env = dict(os.environ)
    env["REVIEW_COUNCIL_DISPATCHED"] = "1"
    return env


def test_the_cli_check_exits_zero():
    proc = subprocess.run([sys.executable, str(REPO / "scripts" / "golden.py"),
                           "--check"], capture_output=True, text=True, timeout=120,
                          env=_as_dispatcher())
    assert proc.returncode == 0, (proc.returncode, proc.stdout, proc.stderr)
    assert "reproduce exactly" in proc.stdout, proc.stdout


def test_the_cli_update_refuses_to_rewrite_when_nothing_changed():
    """`--update` is the one command that can hide a regression by re-pinning it.
    It must be inert when there is nothing to pin."""
    proc = subprocess.run([sys.executable, str(REPO / "scripts" / "golden.py"),
                           "--update"], capture_output=True, text=True, timeout=120,
                          env=_as_dispatcher())
    assert proc.returncode == 0, (proc.returncode, proc.stdout, proc.stderr)
    assert "nothing changed" in proc.stdout, proc.stdout


def test_the_module_refuses_to_run_without_the_dispatcher():
    """The guard itself, on the process that can re-pin every score."""
    proc = subprocess.run([sys.executable, str(REPO / "scripts" / "golden.py"),
                           "--check"], capture_output=True, text=True, timeout=120,
                          env={k: v for k, v in os.environ.items()
                               if k != "REVIEW_COUNCIL_DISPATCHED"})
    assert proc.returncode != 0, "golden.py ran without going through council"
    assert "council golden" in (proc.stdout + proc.stderr)


# --- standalone runner ------------------------------------------------------

def main() -> int:
    failures = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
            print(f"  ok    {name}")
        except AssertionError as exc:
            failures += 1
            print(f"  FAIL  {name}: {exc}")
        except Exception as exc:  # noqa: BLE001 - a broken test must be reported
            failures += 1
            print(f"  ERROR {name}: {type(exc).__name__}: {exc}")
    print(f"\n{'FAILED' if failures else 'all passed'} ({failures} failure(s))")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
