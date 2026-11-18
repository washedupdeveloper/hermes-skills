"""A proof must blame the caller's bad path, not a binary that is present and working.

Measured: a re-adjudication pointed `--repo` at a tree that did not exist, and every `command`
proof came back `unrunnable — /nix/store/…/gitleaks is not installed` while that binary ran fine.
`subprocess.run` raises FileNotFoundError for a missing CWD as well as a missing executable, and
the handler reported both as "not installed".

Run standalone: python tests/test_proofs_root.py
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
_spec = importlib.util.spec_from_file_location("proofs", REPO / "scripts" / "proofs.py")
proofs = importlib.util.module_from_spec(_spec)
sys.modules["proofs"] = proofs
_spec.loader.exec_module(proofs)


def _context(root: Path):
    return proofs.Context(root=root, artefact_dir=Path(tempfile.mkdtemp()), base_root=None)


def test_a_missing_root_names_the_root_not_the_binary():
    missing = Path("/tmp/definitely-not-a-tree-xyz")
    proof = {"kind": "command", "params": {"argv": ["true"], "expect": {"exit": "zero"}}}
    try:
        proofs._run_command(proof["params"], _context(missing))
    except proofs.ProofError as exc:
        message = str(exc)
    else:
        raise AssertionError("a missing root did not raise")
    assert str(missing) in message, message
    assert "not installed" not in message, f"the binary was blamed: {message}"


def test_a_pinned_tool_resolves_without_the_env_var(monkeypatch, tmp_path):
    """Measured: `ruff` was in the pinned toolchain and still reported "not installed", because
    the caller had not exported REVIEW_COUNCIL_TOOLCHAIN. Six passes: 3 confirmed, 3 refused."""
    import sys
    import types

    prefix = tmp_path / "toolchain"
    (prefix / "bin").mkdir(parents=True)
    tool = prefix / "bin" / "ruff"
    tool.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    tool.chmod(0o755)
    monkeypatch.delenv("REVIEW_COUNCIL_TOOLCHAIN", raising=False)
    monkeypatch.setitem(sys.modules, "toolchain",
                        types.SimpleNamespace(resolve=lambda: str(prefix)))
    assert proofs._resolve_binary("ruff", tmp_path) == str(tool)


def test_an_unresolvable_tool_is_left_for_the_allowlist_to_refuse(monkeypatch, tmp_path):
    import sys
    import types

    monkeypatch.delenv("REVIEW_COUNCIL_TOOLCHAIN", raising=False)
    monkeypatch.setitem(sys.modules, "toolchain", types.SimpleNamespace(resolve=lambda: None))
    assert proofs._resolve_binary("no-such-analyzer-xyz", tmp_path) == "no-such-analyzer-xyz"


def test_a_real_root_is_never_reported_as_missing():
    """The guard must fire only for a genuinely absent tree — a valid one falls through to the
    allowlist (or to a real run), which is the correct reason for anything else."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "x.txt").write_text("hi\n", encoding="utf-8")
        ok, detail, _ = proofs._run_command(
            {"argv": ["true"], "expect": {"exit": "zero"}}, _context(root))
    # `true` is not an allowlisted analyzer, so this reports the allowlist — the point is that it
    # did NOT report the root as missing, and did not raise.
    assert "does not exist" not in detail, detail
    assert ok is None, (ok, detail)


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
