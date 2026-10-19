"""Tests for hermes.py — locating the launcher, and what can be known about it.

The council does not talk to a Hermes *gateway*; it shells out to the `hermes`
launcher. These tests pin the layers apart, because collapsing them is the bug
this module exists to prevent: a machine with the gateway up and no launcher
cannot review, and a check that only looked at the port would say it could.

Run standalone (no pytest needed):
    python tests/test_hermes.py
"""
from __future__ import annotations

import importlib.util
import os
import socket
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS))

_spec = importlib.util.spec_from_file_location("hermes", SCRIPTS / "hermes.py")
assert _spec is not None and _spec.loader is not None, "cannot load scripts/hermes.py"
hermes = importlib.util.module_from_spec(_spec)
sys.modules["hermes"] = hermes
_spec.loader.exec_module(hermes)


class _Env:
    """Set env vars for a block, restoring the previous values exactly."""

    def __init__(self, **values):
        self.values = values
        self.saved = {}

    def __enter__(self):
        for key, value in self.values.items():
            self.saved[key] = os.environ.get(key)
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        return self

    def __exit__(self, *exc):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        return False


# A `#!/bin/sh` fixture executes on POSIX, not Windows: the file has no extension,
# so CreateProcess refuses it and `version()` returns None — correctly. Tests needing
# it to RUN are POSIX-only; the Windows `.cmd` equivalent, which `launcher()` does look
# for, is a real gap in this file, not a covered case.
_SHEBANG_FIXTURES_EXECUTE = os.name != "nt"


def _skip_without_shebang_fixtures() -> None:
    if _SHEBANG_FIXTURES_EXECUTE:
        return
    try:
        import pytest
        pytest.skip("a shebang fixture cannot execute on Windows")
    except ImportError:  # pragma: no cover — the toolchain always has pytest
        raise RuntimeError("skipped: Windows cannot execute a shebang fixture") from None


# --- L0: the launcher --------------------------------------------------------

def test_hermes_bin_wins_over_path():
    """HERMES_BIN is how a container names an install that is not on PATH."""
    with tempfile.TemporaryDirectory() as td:
        fake = Path(td) / "hermes"
        fake.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        fake.chmod(0o755)
        with _Env(HERMES_BIN=str(fake)):
            assert hermes.launcher() == str(fake)


def test_a_dangling_hermes_bin_is_not_used():
    """A path that does not exist must not be returned as the launcher."""
    with _Env(HERMES_BIN="/nonexistent/definitely-not-hermes"):
        assert hermes.launcher() != "/nonexistent/definitely-not-hermes"


def test_no_launcher_is_none_not_a_guess():
    with _Env(HERMES_BIN=None, PATH="/nonexistent"):
        assert hermes.launcher() is None


# --- L1: version proves it EXECUTES ------------------------------------------

def test_version_is_none_for_a_launcher_that_cannot_run():
    """The whole point of L1: a file on PATH that cannot execute resolves fine
    and then fails every turn, which reads as an agent problem."""
    with tempfile.TemporaryDirectory() as td:
        broken = Path(td) / "hermes"
        broken.write_text("#!/bin/sh\nexit 3\n", encoding="utf-8")
        broken.chmod(0o755)
        assert hermes.version(str(broken)) is None


def test_version_reads_a_real_launcher():
    _skip_without_shebang_fixtures()
    with tempfile.TemporaryDirectory() as td:
        ok = Path(td) / "hermes"
        ok.write_text("#!/bin/sh\necho hermes 9.9.9\n", encoding="utf-8")
        ok.chmod(0o755)
        assert hermes.version(str(ok)) == "hermes 9.9.9"


def test_version_is_none_without_a_launcher():
    assert hermes.version("/nonexistent/hermes") is None


# --- L2: the profiles carry a provider ---------------------------------------

def test_profiles_missing_is_reported(tmp_path):
    with _Env(HERMES_HOME=str(tmp_path)):
        status = hermes.profile_status()
    assert set(status["missing"]) == set(hermes.PROFILES)
    assert status["present"] == []


def test_profiles_without_a_provider_are_reported(tmp_path):
    """Installed profiles with no provider cannot reach a model, and that is the
    failure the user sees as "the agent did nothing"."""
    for name in hermes.PROFILES:
        (tmp_path / "profiles" / name).mkdir(parents=True)
        (tmp_path / "profiles" / name / "config.yaml").write_text(
            "display:\n  skin: default\n", encoding="utf-8")
    with _Env(HERMES_HOME=str(tmp_path)):
        status = hermes.profile_status()
    assert set(status["without_provider"]) == set(hermes.PROFILES)
    assert status["with_provider"] == []


def test_profiles_with_a_provider_are_ready(tmp_path):
    for name in hermes.PROFILES:
        (tmp_path / "profiles" / name).mkdir(parents=True)
        (tmp_path / "profiles" / name / "config.yaml").write_text(
            "model:\n  provider: custom\n  api_key: x\n", encoding="utf-8")
    with _Env(HERMES_HOME=str(tmp_path)):
        status = hermes.profile_status()
    assert set(status["with_provider"]) == set(hermes.PROFILES)
    assert status["missing"] == []


# --- L3: the gateway is a HINT, and only that --------------------------------

def test_the_gateway_port_is_not_the_verdict(tmp_path):
    """The heart of it. A listening port must not turn a missing launcher into a
    'ready': they are different things, and only one of them can review."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    try:
        with _Env(HERMES_BIN=None, PATH="/nonexistent", HERMES_HOME=str(tmp_path)):
            data = hermes.report(gateway_host="127.0.0.1", gateway_port=port)
        assert data["gateway"]["reachable"] is True, "the probe missed a live listener"
        assert data["verdict"] == "no-launcher", (
            "a reachable gateway was treated as a usable Hermes")
    finally:
        listener.close()


def test_a_closed_gateway_does_not_break_a_working_launcher(tmp_path):
    """The other direction: no gateway at all, and the launcher is fine. The CLI
    path needs no gateway, so this must stay 'ready'."""
    _skip_without_shebang_fixtures()
    for name in hermes.PROFILES:
        (tmp_path / "profiles" / name).mkdir(parents=True)
        (tmp_path / "profiles" / name / "config.yaml").write_text(
            "model:\n  provider: custom\n", encoding="utf-8")
    with tempfile.TemporaryDirectory() as td:
        ok = Path(td) / "hermes"
        ok.write_text("#!/bin/sh\necho hermes 1.0\n", encoding="utf-8")
        ok.chmod(0o755)
        with _Env(HERMES_BIN=str(ok), HERMES_HOME=str(tmp_path)):
            data = hermes.report(gateway_host="127.0.0.1", gateway_port=1)
    assert data["gateway"]["reachable"] is False
    assert data["verdict"] == "ready", data


def test_the_gateway_reports_what_it_does_and_does_not_mean():
    with _Env(HERMES_GATEWAY_HOST="127.0.0.1", HERMES_GATEWAY_PORT="1"):
        data = hermes.gateway(timeout=0.2)
    assert data["port"] == 1
    assert "NOT what the council drives" in data["meaning"], data["meaning"]


# --- the verdict -------------------------------------------------------------

def test_the_verdict_names_the_first_thing_to_fix(tmp_path):
    """Ordered: no launcher beats no profiles, which beats no credentials. The
    user should be told the one thing worth doing next, not a list."""
    with _Env(HERMES_BIN=None, PATH="/nonexistent", HERMES_HOME=str(tmp_path)):
        assert hermes.report()["verdict"] == "no-launcher"

    with tempfile.TemporaryDirectory() as td:
        broken = Path(td) / "hermes"
        broken.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        broken.chmod(0o755)
        with _Env(HERMES_BIN=str(broken), HERMES_HOME=str(tmp_path)):
            assert hermes.report()["verdict"] == "unusable-launcher"

    # Only this last block needs the fixture to RUN. The two above hold on Windows
    # too — a file it cannot execute reports 'unusable-launcher' — but 'no-profiles'
    # is unreachable from a launcher Windows will not start.
    if _SHEBANG_FIXTURES_EXECUTE:
        with tempfile.TemporaryDirectory() as td:
            ok = Path(td) / "hermes"
            ok.write_text("#!/bin/sh\necho hermes 1.0\n", encoding="utf-8")
            ok.chmod(0o755)
            with _Env(HERMES_BIN=str(ok), HERMES_HOME=str(tmp_path)):
                assert hermes.report()["verdict"] == "no-profiles"


def test_every_verdict_has_wording_and_an_action(tmp_path):
    """A verdict with no text prints as a bare token, and one with no action
    tells the user they are stuck."""
    with _Env(HERMES_BIN=None, PATH="/nonexistent", HERMES_HOME=str(tmp_path)):
        data = hermes.report()
    assert data["verdict"] in hermes._VERDICT_TEXT
    assert data["action"], "a failing verdict must say what to do"


def test_render_names_the_gateway_as_a_hint(tmp_path):
    with _Env(HERMES_BIN=None, PATH="/nonexistent", HERMES_HOME=str(tmp_path)):
        lines = hermes.render(hermes.report())
    joined = "\n".join(lines)
    assert "NOT FOUND" in joined, joined
    assert "hint" in joined, "the gateway must be labelled as a hint, not a fact"


# --- L4 is opt-in and never runs by itself -----------------------------------

def test_capability_is_not_called_by_report(tmp_path):
    """It spends an agent turn. Nothing but an explicit request may trigger it."""
    calls = []
    original = hermes.capability
    hermes.capability = lambda *a, **k: calls.append(1) or {"ok": True}
    try:
        with _Env(HERMES_BIN=None, PATH="/nonexistent", HERMES_HOME=str(tmp_path)):
            data = hermes.report()
    finally:
        hermes.capability = original
    assert calls == [], "report() spent an agent turn"
    assert "capability" not in data


def test_capability_reports_no_launcher_without_inventing_a_result():
    with _Env(HERMES_BIN=None, PATH="/nonexistent"):
        result = hermes.capability()
    assert result["ran"] is False
    assert result["ok"] is False


def main() -> int:
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    passed = failed = 0
    for name, fn in tests:
        try:
            if fn.__code__.co_argcount:
                with tempfile.TemporaryDirectory() as td:
                    fn(Path(td))
            else:
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
