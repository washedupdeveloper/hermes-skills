"""An approved toolchain binary must actually run, not be reported "not installed".

Run standalone (no pytest needed):
    python tests/test_toolchain_proofs.py
"""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
_spec = importlib.util.spec_from_file_location("proofs", REPO / "scripts" / "proofs.py")
proofs = importlib.util.module_from_spec(_spec)
sys.modules["proofs"] = proofs
_spec.loader.exec_module(proofs)


def fake_toolchain(tmp: Path, name: str = "fauxlint", exit_code: int = 7) -> Path:
    prefix = tmp / "toolchain"
    (prefix / "bin").mkdir(parents=True)
    tool = prefix / "bin" / name
    tool.write_text(f"#!/bin/sh\nexit {exit_code}\n", encoding="utf-8")
    tool.chmod(0o755)
    return prefix


def run_proof(argv, root: Path):
    ctx = proofs.Context(root=root, artefact_dir=root / ".proofs")
    return proofs.evaluate({"kind": "command",
                            "params": {"argv": argv, "expect": {"exit": 7}}}, ctx)


def test_a_toolchain_binary_runs_without_being_on_path():
    """The allowlist approved it from the toolchain; execution has to use the same knowledge."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "repo"
        root.mkdir()
        prefix = fake_toolchain(Path(tmp))
        with mock.patch.dict(os.environ, {"REVIEW_COUNCIL_TOOLCHAIN": str(prefix),
                                          "PATH": "/nonexistent"}):
            verdict = run_proof(["fauxlint"], root)
    assert verdict["status"] == "supported", verdict
    assert verdict["observed"]["exit"] == 7


def test_the_resolved_path_is_the_toolchain_one():
    with tempfile.TemporaryDirectory() as tmp:
        prefix = fake_toolchain(Path(tmp))
        with mock.patch.dict(os.environ, {"REVIEW_COUNCIL_TOOLCHAIN": str(prefix),
                                          "PATH": "/nonexistent"}):
            resolved = proofs._resolve_binary("fauxlint", Path(tmp))
    assert resolved == str(prefix / "bin" / "fauxlint"), resolved


def test_an_unknown_binary_is_still_refused():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "repo"
        root.mkdir()
        with mock.patch.dict(os.environ, {"REVIEW_COUNCIL_TOOLCHAIN": str(Path(tmp) / "none"),
                                          "PATH": "/nonexistent"}):
            verdict = run_proof(["definitely-not-a-real-binary"], root)
    assert verdict["status"] == "unrunnable", verdict
    assert "not on the pinned toolchain" in verdict["detail"], verdict["detail"]


def test_a_repository_script_is_run_by_its_path():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "repo"
        root.mkdir()
        script = root / "check.sh"
        script.write_text("#!/bin/sh\nexit 7\n", encoding="utf-8")
        script.chmod(0o755)
        with mock.patch.dict(os.environ, {"PATH": "/nonexistent"}):
            verdict = run_proof([str(script)], root)
    assert verdict["status"] == "supported", verdict


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok   {name}")
            except AssertionError as exc:
                failures += 1
                print(f"FAIL {name}: {exc}")
            except Exception as exc:  # noqa: BLE001
                failures += 1
                print(f"FAIL {name}: {type(exc).__name__}: {exc}")
    total = len([n for n in globals() if n.startswith("test_")])
    print(f"\n{total - failures} passed, {failures} failed")
    raise SystemExit(1 if failures else 0)
