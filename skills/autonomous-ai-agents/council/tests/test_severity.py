"""Severity from evidence: the tool's finding decides, the reviewer's label is advisory.

Run standalone (no pytest needed):
    python tests/test_severity.py
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
_spec = importlib.util.spec_from_file_location("severity", REPO / "scripts" / "severity.py")
severity = importlib.util.module_from_spec(_spec)
sys.modules["severity"] = severity
_spec.loader.exec_module(severity)


def proof(tool: str) -> dict:
    return {"kind": "command", "params": {"argv": [tool, "detect", "--source", "src"]}}


def test_a_gitleaks_hit_is_critical_whatever_the_reviewer_called_it():
    """The measured failure: one credential came back critical, critical, medium across passes."""
    value, rule, authority = severity.from_evidence(proof("gitleaks"), {})
    assert (value, rule, authority) == ("critical", "credential", "floor"), (value, rule, authority)
    for label in ("low", "medium", ""):
        effective, source = severity.effective(label, value)
        assert effective == "critical" and source == "evidence", (label, effective, source)
    # Agreeing is not "evidence decided it" — the source records who set the value, and when the
    # reviewer already said critical there was nothing to raise.
    effective, source = severity.effective("critical", value)
    assert (effective, source) == ("critical", "reviewer"), (effective, source)


def test_evidence_never_lowers_a_reviewer_label():
    """Measured: a critical claim proven with a lint command was downgraded to low by rule alone."""
    effective, source = severity.effective("critical", "low")
    assert (effective, source) == ("critical", "reviewer"), (effective, source)
    raised, source = severity.effective("medium", "critical")
    assert (raised, source) == ("critical", "evidence"), (raised, source)
    kept, source = severity.effective("high", "high")
    assert (kept, source) == ("high", "reviewer"), (kept, source)


def test_named_classes_settle_severity_in_both_directions():
    """Exact settles, floor only raises. Measured: one syntax error came back critical, critical,
    high on the same line."""
    # exact settles it even when the reviewer over-stated the severity
    assert severity.effective("critical", "high", "exact") == ("high", "evidence")
    # floor never lowers
    assert severity.effective("critical", "low", "floor") == ("critical", "reviewer")
    # and floor still raises
    assert severity.effective("low", "high", "floor") == ("high", "evidence")


def test_a_citation_quoting_the_error_is_settled_by_the_class():
    """A `present` proof whose citation includes the error text names the class."""
    citing = {"kind": "present", "params": {"path": "out.log", "line": 3, "text": "SyntaxError"}}
    value, rule, authority = severity.from_evidence(
        citing, {"excerpt": '  File "a.py", line 8\nSyntaxError: invalid syntax'})
    assert (value, rule, authority) == ("high", "does-not-parse-literal", "exact"), \
        (value, rule, authority)


def test_a_toolchain_path_still_names_the_tool():
    store = "/nix/store/abc-gitleaks-8.30.1/bin/gitleaks"
    value, rule, authority = severity.from_evidence(
        {"kind": "command", "params": {"argv": [store, "detect"]}}, {})
    assert (value, rule, authority) == ("critical", "credential", "floor"), (value, rule, authority)


def test_bandit_only_fires_for_code_execution_rules():
    ok, rule, _ = severity.from_evidence(
        proof("bandit"), {"stdout_head": "Issue: [B307:blacklist] eval used"})
    assert ok == "high" and rule == "code-execution", (ok, rule)
    unrelated, _, _ = severity.from_evidence(
        proof("bandit"), {"stdout_head": "Issue: [B101:assert_used]"})
    assert unrelated is None, "assert_used was promoted to code execution"


def test_lint_is_low_and_types_are_medium():
    assert severity.from_evidence(proof("ruff"), {})[0] == "low"
    assert severity.from_evidence(proof("statix"), {})[0] == "low"
    assert severity.from_evidence(proof("mypy"), {})[0] == "medium"


def test_a_cited_credential_is_critical_without_a_tool():
    """The measured case: a `present` proof of the same key kept the reviewer's `medium`."""
    present = {"kind": "present", "params": {"path": "src/svc/__init__.py",
                                             "pattern": "sk_live_"}}
    value, rule, authority = severity.from_evidence(
        present, {"excerpt": 'API_KEY = "sk_live_9f2ab31c7741d0e5"'})
    assert (value, rule, authority) == ("critical", "credential-literal", "exact"), \
        (value, rule, authority)
    effective, source = severity.effective("medium", value, authority)
    assert (effective, source) == ("critical", "evidence"), (effective, source)


def test_a_command_proof_cannot_stamp_its_output_as_the_finding():
    """Measured: `ruff format --check` echoed the secret it was reformatting, and a formatting
    finding was stamped critical by the credential rule."""
    ruff = {"kind": "command", "params": {"argv": ["ruff", "format", "--check", "."]}}
    value, rule, authority = severity.from_evidence(
        ruff, {"stdout_head": '1 file would be reformatted\n-API_KEY = "sk_live_9f2ab31c7741d0e5"'})
    assert (value, rule, authority) == ("low", "lint-python", "floor"), (value, rule, authority)


def test_a_citation_of_the_line_still_stamps_it():
    present = {"kind": "present", "params": {"path": "a.py", "line": 4, "text": "API_KEY"}}
    value, rule, _ = severity.from_evidence(
        present, {"excerpt": 'API_KEY = "sk_live_9f2ab31c7741d0e5"'})
    assert (value, rule) == ("critical", "credential-literal"), (value, rule)


def test_an_uncovered_tool_leaves_the_reviewer_label_alone():
    value, rule, authority = severity.from_evidence(proof("some-other-analyzer"), {})
    assert value is None and rule == "" and authority == ""
    effective, source = severity.effective("high", value)
    assert (effective, source) == ("high", "reviewer")


def test_no_proof_means_no_evidence():
    assert severity.from_evidence(None, {}) == (None, "", "")
    assert severity.from_evidence({"kind": "command", "params": {}}, {}) == (None, "", "")


def test_the_table_says_why_it_says_what_it_says():
    for rule in severity.contract().get("rules", []):
        assert rule.get("why"), f"{rule.get('id')} has no rationale"
        assert rule.get("severity") in severity.RANK, rule


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
