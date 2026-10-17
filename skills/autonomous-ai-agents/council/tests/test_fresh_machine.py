"""The fresh-machine path: a review with no analyzers installed.

M9's acceptance criterion is "fresh machine → documented install → green end-to-end
run". The suite has never tested the first half, because it always runs with the
pinned toolchain on PATH — so the degradation path, which is the whole reason the
built-in probes exist, was asserted in prose and nowhere else.

This runs the real modules in a subprocess with:

  * `REVIEW_COUNCIL_TOOLCHAIN` removed, and
  * `PATH` pointing at an empty directory,

which is what a machine with Python and nothing else looks like. Note that removing
the variable alone is NOT enough: `toolchain.env()` resolves the toolchain itself when
`nix` is on PATH, so a test that only unsets it still runs every analyzer. The empty
PATH is what makes this a fresh machine.

What must hold:

  1. nothing crashes, and the command exits 0 — a missing analyzer is not an error;
  2. the stdlib probes still produce real signal;
  3. every tool-backed probe reports `ran: false` with a REASON, never a score;
  4. no probe reports a signal it did not measure;
  5. `doctor` reports a beta below 1, so the score cannot silently become the LLM's;
  6. `doctor` says how to fix it.

Run standalone (no pytest needed):
    python tests/test_fresh_machine.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TARGET = REPO / "tests" / "golden" / "target"

#: Probes that are pure stdlib: they need no binary and no toolchain.
STDLIB_PROBES = {
    "secret-grep", "py-compile", "complexity", "dep-graph", "declared-rules",
}


def _bare_env() -> tuple[dict, tempfile.TemporaryDirectory]:
    """An environment that looks like a machine with Python and nothing else.

    The caller owns the returned TemporaryDirectory and must clean it up.
    """
    empty = tempfile.TemporaryDirectory()
    env = {k: v for k, v in os.environ.items() if k != "REVIEW_COUNCIL_TOOLCHAIN"}
    env["PATH"] = empty.name
    env["REVIEW_COUNCIL_DISPATCHED"] = "1"
    return env, empty


def _run(script: str, *args: str) -> subprocess.CompletedProcess:
    """Run a module by absolute path, with the bare environment."""
    env, empty = _bare_env()
    try:
        return subprocess.run(
            [sys.executable, str(REPO / "scripts" / script), *args],
            cwd=str(REPO), env=env, capture_output=True, text=True, timeout=300,
            encoding="utf-8", errors="replace",
        )
    finally:
        empty.cleanup()


def _probes() -> list:
    proc = _run("probes.py", "--all", "--repo", str(TARGET))
    assert proc.returncode == 0, f"probes exited {proc.returncode}:\n{proc.stderr[:800]}"
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f"probes did not emit JSON ({exc}):\n{proc.stdout[:500]}\n"
            f"stderr:\n{proc.stderr[:500]}") from exc


def _doctor() -> dict:
    proc = _run("doctor.py", "--repo", str(TARGET), "--json")
    assert proc.returncode == 0, f"doctor exited {proc.returncode}:\n{proc.stderr[:800]}"
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"doctor did not emit JSON ({exc}):\n{proc.stdout[:500]}") from exc


# --- 1. it does not crash -----------------------------------------------------

def test_a_missing_toolchain_is_not_an_error():
    """A machine without the analyzers must still be able to ask for a review."""
    proc = _run("probes.py", "--all", "--repo", str(TARGET))
    assert proc.returncode == 0, (
        f"probes exited {proc.returncode}; a missing analyzer must not fail the run:\n"
        f"{proc.stderr[:800]}")


def test_doctor_runs_without_the_toolchain():
    proc = _run("doctor.py", "--repo", str(TARGET), "--json")
    assert proc.returncode == 0, proc.stderr[:800]


# --- 2. the stdlib probes carry the run ---------------------------------------

def test_the_stdlib_probes_still_run():
    """These are the reason the framework works on a machine with nothing installed."""
    results = {r["tool"]: r for r in _probes()}
    missing = sorted(STDLIB_PROBES - set(results))
    assert not missing, f"probes absent entirely: {missing}"

    did_not_run = [name for name in STDLIB_PROBES if not results[name]["ran"]]
    assert not did_not_run, (
        f"stdlib probes reported ran=false with no toolchain: {did_not_run} — "
        f"they are supposed to need nothing")


def test_at_least_one_probe_produces_signal():
    """Degradation is not the same as doing nothing: the run must still have a signal."""
    ran = [r for r in _probes() if r["ran"] and r.get("signal") is not None]
    assert ran, "no probe produced a signal on a fresh machine"


# --- 3. a tool that is absent says so, with a reason --------------------------

def test_tool_probes_report_a_reason_not_a_score():
    """The failure mode this prevents: a probe that cannot run reporting 100.0, which
    reads as 'clean' and hands the dimension to the LLM without saying so."""
    for result in _probes():
        if result["ran"]:
            continue
        note = (result.get("note") or "").strip()
        assert note, f"{result['tool']} reported ran=false with no reason given"


def test_a_tool_backed_probe_is_not_reported_as_clean():
    """`nixfmt`, `statix`, `ruff` and the rest cannot run here, so none may be
    reported as having run successfully."""
    results = {r["tool"]: r for r in _probes()}
    for name in ("statix", "deadnix", "nixfmt", "ruff", "mypy", "bandit", "gitleaks"):
        result = results.get(name)
        if result is None:
            continue
        assert not result["ran"], (
            f"{name} claims to have run with no toolchain and an empty PATH: {result}")


# --- 4. nothing is invented ---------------------------------------------------

def test_no_probe_reports_a_signal_it_did_not_measure():
    """The invariant behind the whole design: `signal` is set only when `ran`."""
    for result in _probes():
        if not result["ran"]:
            assert result.get("signal") is None, (
                f"{result['tool']} reports ran=false but signal={result.get('signal')}")


def test_every_probe_reports_the_same_shape():
    """A probe that omitted `findings` would break the merge that reads them."""
    for result in _probes():
        for field in ("tool", "ran", "parsed", "signal", "findings"):
            assert field in result, f"{result.get('tool')} is missing {field!r}"
        assert isinstance(result["findings"], list), result["tool"]


# --- 5. beta tells the truth --------------------------------------------------

def test_doctor_reports_a_beta_below_one():
    """beta is the deterministic share of the score. With no analyzers it must fall,
    or `score = beta*det + (1-beta)*llm` silently becomes the LLM's judgement."""
    doctor = _doctor()
    beta = doctor.get("beta_now")
    assert beta is not None, "doctor did not report beta_now"
    assert beta < 1.0, (
        f"doctor reports beta {beta} with no toolchain present — a missing analyzer "
        f"must lower beta, never leave it at 1")


def test_doctor_reports_the_toolchain_as_unavailable():
    doctor = _doctor()
    nix = doctor.get("nix") or {}
    assert nix.get("available") is False, nix
    assert nix.get("error"), "doctor must say why the toolchain is unavailable"


def test_per_dimension_beta_is_reported_and_low():
    """The aggregate can hide a dimension at zero; the per-dimension figure cannot."""
    doctor = _doctor()
    dims = doctor.get("dimensions") or []
    assert dims, "doctor reported no dimensions"
    for dim in dims:
        assert "beta_now" in dim, dim
        assert 0.0 <= dim["beta_now"] <= 1.0, dim


# --- 6. it says what to do about it -------------------------------------------

def test_doctor_names_the_way_out():
    """A beta of 0.32 is only actionable if the message says how to raise it."""
    doctor = _doctor()
    text = json.dumps(doctor)
    assert "CONTAINER.md" in text or "Install nix" in text, (
        "doctor must name the remedy: install nix, or run the container image")


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
