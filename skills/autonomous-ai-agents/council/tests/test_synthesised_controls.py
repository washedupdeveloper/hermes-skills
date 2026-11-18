"""Synthesised controls: the orchestrator writes the control the reviewer did not.

Run standalone (no pytest needed):
    python tests/test_synthesised_controls.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS))

_spec = importlib.util.spec_from_file_location("proofs", SCRIPTS / "proofs.py")
proofs = importlib.util.module_from_spec(_spec)
sys.modules["proofs"] = proofs
_spec.loader.exec_module(proofs)

CHECK = """#!/bin/sh
# Fails when the defect is present. The control runs this same script against the base tree.
if grep -q "shell=True" app.py; then exit 1; fi
exit 0
"""


def tree(root: Path, *, defective: bool) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    app = "import subprocess\n\n\ndef run(cmd):\n"
    app += "    return subprocess.run(cmd, shell=True)\n" if defective else \
        "    return subprocess.run(cmd, shell=False)\n"
    if not defective:
        app += "\n\ndef legacy():\n    return 1\n"
    (root / "app.py").write_text(app, encoding="utf-8")
    script = root / "check.sh"
    script.write_text(CHECK, encoding="utf-8")
    script.chmod(0o755)
    (root / "config.json").write_text(
        json.dumps({"debug": defective}), encoding="utf-8")
    return root


def context(root: Path, base: Path | None = None) -> "proofs.Context":
    return proofs.Context(root=root, artefact_dir=root / ".proofs",
                          base_root=base)


def command_proof(root: Path) -> dict:
    return {"kind": "command",
            "params": {"argv": [str(root / "check.sh")], "expect": {"exit": "nonzero"}}}


# --- the command kind: the strongest case -------------------------------------------
def test_a_failing_check_is_proven_by_the_base_revision_passing_it():
    with tempfile.TemporaryDirectory() as tmp:
        base = tree(Path(tmp) / "base", defective=False)
        head = tree(Path(tmp) / "head", defective=True)
        verdict = proofs.adjudicate(command_proof(head), context(head, base))
    assert verdict["status"] == "supported", verdict
    assert verdict["control_source"] == "orchestrator:base-revision", verdict["control_source"]
    assert verdict["control"]["status"] == "refuted", verdict["control"]
    assert verdict["admission"] == "proven", verdict["admission"]


def test_a_check_that_fails_on_the_base_too_is_not_evidence():
    """The defect is pre-existing: the check cannot tell this change apart from the repository."""
    with tempfile.TemporaryDirectory() as tmp:
        base = tree(Path(tmp) / "base", defective=True)
        head = tree(Path(tmp) / "head", defective=True)
        verdict = proofs.adjudicate(command_proof(head), context(head, base))
    assert verdict["control"]["status"] == "supported", verdict["control"]
    assert verdict["admission"] == "control_did_not_fail", verdict["admission"]
    assert verdict["class"] == "unproven"


def test_without_a_base_revision_the_claim_stays_uncontrolled():
    with tempfile.TemporaryDirectory() as tmp:
        head = tree(Path(tmp) / "head", defective=True)
        verdict = proofs.adjudicate(command_proof(head), context(head))
    assert verdict["admission"] == "uncontrolled", verdict["admission"]
    assert verdict["control_source"] == "none"
    assert "no base revision supplied" in verdict["detail"], verdict["detail"]


def test_a_reviewer_control_is_never_replaced():
    with tempfile.TemporaryDirectory() as tmp:
        base = tree(Path(tmp) / "base", defective=False)
        head = tree(Path(tmp) / "head", defective=True)
        proof = command_proof(head)
        # A control the reviewer wrote: the same script, expected to pass. It does not, so the
        # control is refuted and the claim is proven — without the orchestrator touching it.
        proof["control"] = {"kind": "command",
                            "params": {"argv": [str(head / "check.sh")],
                                       "expect": {"exit": "zero"}}}
        verdict = proofs.adjudicate(proof, context(head, base))
    assert verdict["control_source"] == "reviewer", verdict["control_source"]
    assert verdict["admission"] == "proven", verdict["admission"]


# --- the tree-reading kinds ---------------------------------------------------------
def test_absent_is_proven_when_the_base_still_has_it():
    with tempfile.TemporaryDirectory() as tmp:
        base = tree(Path(tmp) / "base", defective=False)
        head = tree(Path(tmp) / "head", defective=True)
        proof = {"kind": "absent", "params": {"pattern": r"def legacy\("}}
        verdict = proofs.adjudicate(proof, context(head, base))
    assert verdict["status"] == "supported", verdict
    assert verdict["admission"] == "proven", verdict["admission"]


def test_absent_is_uncontrolled_when_the_base_lacks_it_too():
    with tempfile.TemporaryDirectory() as tmp:
        base = tree(Path(tmp) / "base", defective=True)
        head = tree(Path(tmp) / "head", defective=True)
        proof = {"kind": "absent", "params": {"pattern": r"def legacy\("}}
        verdict = proofs.adjudicate(proof, context(head, base))
    assert verdict["admission"] == "control_did_not_fail", verdict["admission"]


def test_present_is_proven_when_the_line_is_new():
    with tempfile.TemporaryDirectory() as tmp:
        base = tree(Path(tmp) / "base", defective=False)
        head = tree(Path(tmp) / "head", defective=True)
        proof = {"kind": "present",
                 "params": {"path": "app.py", "line": 5, "text": "shell=True"}}
        verdict = proofs.adjudicate(proof, context(head, base))
    assert verdict["status"] == "supported", verdict
    assert verdict["admission"] == "proven", verdict["admission"]


def test_json_is_proven_when_the_base_holds_a_different_value():
    with tempfile.TemporaryDirectory() as tmp:
        base = tree(Path(tmp) / "base", defective=False)
        head = tree(Path(tmp) / "head", defective=True)
        proof = {"kind": "json",
                 "params": {"path": "config.json", "pointer": "/debug", "equals": True}}
        verdict = proofs.adjudicate(proof, context(head, base))
    assert verdict["status"] == "supported", verdict
    assert verdict["admission"] == "proven", verdict["admission"]


# --- the runtime kinds: an expectation flip, no base needed -------------------------
def test_dom_and_http_controls_flip_the_expectation():
    ctx = context(Path("/tmp"))
    dom = proofs.synthesise_control(
        {"kind": "dom", "params": {"selector": "#app", "expect": "present"}}, ctx)
    http = proofs.synthesise_control(
        {"kind": "http", "params": {"url": "http://127.0.0.1:1/x", "expect_status": 200}}, ctx)
    diff = proofs.synthesise_control(
        {"kind": "diff", "params": {"path": "a.py", "line": 3, "mode": "added"}}, ctx)
    assert dom["params"]["expect"] == "absent" and dom["source"].endswith("expectation-flip")
    assert http["params"]["expect_status"] == 404
    assert diff["params"]["mode"] == "removed" and diff["source"].endswith("mode-flip")


def test_a_tree_reading_kind_without_a_base_has_no_synthesis():
    ctx = context(Path("/tmp"))
    assert proofs.synthesise_control({"kind": "command", "params": {"argv": ["true"]}}, ctx) is None


# --- rebasing -----------------------------------------------------------------------
def test_absolute_paths_are_rebased_into_the_base_tree():
    root, base = Path("/repo/head"), Path("/repo/base")
    params = {"argv": ["/repo/head/check.sh", "--config", "/repo/head/c.json", "/usr/bin/env"]}
    rebased = proofs._rebase(params, root, base)
    assert rebased["argv"] == ["/repo/base/check.sh", "--config", "/repo/base/c.json",
                               "/usr/bin/env"], rebased


def test_rebasing_leaves_relative_and_outside_paths_alone():
    root, base = Path("/repo/head"), Path("/repo/base")
    assert proofs._rebase({"argv": ["check.sh", "/opt/tool"]}, root, base)["argv"] == \
        ["check.sh", "/opt/tool"]


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
