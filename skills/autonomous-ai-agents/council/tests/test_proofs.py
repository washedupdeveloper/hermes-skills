"""Proofs: every kind, both directions, and the control that makes a claim blockable.

Run standalone (no pytest needed):
    python tests/test_proofs.py

The theme is the one the framework lives by: `unrunnable` must never collapse into `refuted`, a
citation that does not exist must never read as a finding, and a check that cannot fail must never
count as proof. Each test below is one of those sentences made executable.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
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


def tree(tmp: Path) -> Path:
    (tmp / "good.py").write_text("def helper():\n    return 1\n\nhelper()\n", encoding="utf-8")
    (tmp / "bad.py").write_text("def unused_helper():\n    return 2\n", encoding="utf-8")
    (tmp / "data.json").write_text('{"version": 3, "nested": {"a": [10, 20]}}', encoding="utf-8")
    (tmp / "page.html").write_text(
        '<html><body><div id="app"><button class="cta">Go</button></div></body></html>',
        encoding="utf-8")
    return tmp


def ctx_for(root: Path, **kw) -> "proofs.Context":
    return proofs.Context(root=root, artefact_dir=root / ".artefacts", **kw)


def run(proof, root, **kw):
    return proofs.evaluate(proof, ctx_for(root, **kw))


# --- the contract is the vocabulary ----------------------------------------------


def test_the_registry_and_the_contract_agree():
    """A kind declared with no executor would be unrunnable at run time; caught here instead."""
    assert set(proofs.kinds()) == set(proofs.EXECUTORS)


def test_an_unknown_kind_is_unrunnable_not_refuted():
    with tempfile.TemporaryDirectory() as tmp:
        out = run({"kind": "vibes", "params": {}}, tree(Path(tmp)))
    assert out["status"] == "unrunnable"
    assert "closed" in out["detail"]


def test_an_unknown_parameter_is_refused():
    with tempfile.TemporaryDirectory() as tmp:
        out = run({"kind": "absent", "params": {"pattern": "x", "shell": "rm -rf /"}}, tree(Path(tmp)))
    assert out["status"] == "unrunnable"
    assert "no parameter(s) shell" in out["detail"]


def test_a_missing_required_parameter_is_refused():
    with tempfile.TemporaryDirectory() as tmp:
        out = run({"kind": "present", "params": {"path": "bad.py"}}, tree(Path(tmp)))
    assert out["status"] == "unrunnable"
    assert "requires `line`" in out["detail"] or "requires `text`" in out["detail"]


def test_a_bad_regex_is_unrunnable_not_an_empty_result():
    with tempfile.TemporaryDirectory() as tmp:
        out = run({"kind": "absent", "params": {"pattern": "([unclosed"}}, tree(Path(tmp)))
    assert out["status"] == "unrunnable"
    assert "valid regex" in out["detail"]


# --- absent -----------------------------------------------------------------------


def test_absent_refutes_when_the_symbol_is_there_and_supports_when_it_is_not():
    with tempfile.TemporaryDirectory() as tmp:
        root = tree(Path(tmp))
        found = run({"kind": "absent", "params": {"pattern": "unused_helper"}}, root)
        gone = run({"kind": "absent",
                    "params": {"pattern": "unused_helper\\(", "exclude": ["bad.py"]}}, root)
    assert found["status"] == "refuted" and "bad.py:1" in found["detail"]
    assert gone["status"] == "supported"


def test_absent_is_unrunnable_above_max_files_rather_than_truncated():
    with tempfile.TemporaryDirectory() as tmp:
        root = tree(Path(tmp))
        out = run({"kind": "absent", "params": {"pattern": "x", "max_files": 1}}, root)
    assert out["status"] == "unrunnable"
    assert "unbounded" in out["detail"]


# --- present: the citation killer --------------------------------------------------


def test_present_refuses_a_hallucinated_line():
    with tempfile.TemporaryDirectory() as tmp:
        out = run({"kind": "present",
                   "params": {"path": "bad.py", "line": 1, "text": "def helper"}}, tree(Path(tmp)))
    assert out["status"] == "refuted"


def test_present_refuses_a_file_that_does_not_exist():
    with tempfile.TemporaryDirectory() as tmp:
        out = run({"kind": "present",
                   "params": {"path": "ghost.py", "line": 1, "text": "x"}}, tree(Path(tmp)))
    assert out["status"] == "refuted"


def test_present_reads_a_line_range():
    with tempfile.TemporaryDirectory() as tmp:
        out = run({"kind": "present",
                   "params": {"path": "good.py", "line": 1, "line_end": 2,
                              "text": "return 1"}}, tree(Path(tmp)))
    assert out["status"] == "supported"


# --- command ------------------------------------------------------------------------


def test_a_binary_from_the_pinned_toolchain_is_allowed():
    """A claim about a gitleaks hit names a gitleaks binary. The toolchain declares it; a hand-kept
    allowlist of analyzer names would go stale the first time one was added."""
    with tempfile.TemporaryDirectory() as tmp:
        toolchain = Path(tmp) / "toolchain"
        (toolchain / "bin").mkdir(parents=True)
        gitleaks = toolchain / "bin" / "gitleaks"
        gitleaks.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        gitleaks.chmod(0o755)
        allowed, why = proofs._executable_allowed(str(gitleaks), Path(tmp), toolchain)
    assert allowed, why


def test_a_symlink_joined_toolchain_still_provides_its_tools():
    """`symlinkJoin` makes `<prefix>/bin/tool` a link to a DIFFERENT store path. Comparing resolved
    paths against the prefix refuses every tool in a working toolchain — the real bug this pins."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        package = root / "store" / "gitleaks-8.30.1" / "bin"
        package.mkdir(parents=True)
        real = package / "gitleaks"
        real.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        real.chmod(0o755)
        toolchain = root / "toolchain"
        (toolchain / "bin").mkdir(parents=True)
        (toolchain / "bin" / "gitleaks").symlink_to(real)
        assert proofs._toolchain_provides(toolchain, "gitleaks", real.resolve())
        allowed, why = proofs._executable_allowed(str(toolchain / "bin" / "gitleaks"),
                                                  root / "repo", toolchain)
    assert allowed, why


def test_a_binary_outside_the_toolchain_and_the_repo_is_still_refused():
    with tempfile.TemporaryDirectory() as tmp:
        toolchain = Path(tmp) / "toolchain"
        toolchain.mkdir()
        allowed, why = proofs._executable_allowed("/usr/bin/curl", Path(tmp), toolchain)
    assert not allowed and "toolchain" in why


def test_command_refuses_an_unlisted_executable():
    with tempfile.TemporaryDirectory() as tmp:
        out = run({"kind": "command",
                   "params": {"argv": ["curl", "http://example.com"], "expect": {"exit": "zero"}}},
                  tree(Path(tmp)))
    assert out["status"] == "unrunnable"
    assert "allowlisted" in out["detail"]


def test_a_timeout_is_unrunnable_not_refuted():
    with tempfile.TemporaryDirectory() as tmp:
        out = run({"kind": "command",
                   "params": {"argv": [sys.executable, "-c", "import time; time.sleep(5)"],
                              "expect": {"exit": "zero"}, "timeout": 1}}, tree(Path(tmp)))
    assert out["status"] == "unrunnable"
    assert "unrunnable, not refuted" in out["detail"]


def test_command_reads_stdout_and_leaves_an_artefact():
    with tempfile.TemporaryDirectory() as tmp:
        root = tree(Path(tmp))
        out = run({"kind": "command",
                   "params": {"argv": [sys.executable, "-c", "print('boom')"],
                              "expect": {"exit": "zero", "stdout_contains": "boom"}}}, root)
        assert out["status"] == "supported", out["detail"]
        assert out["artefact"] and Path(out["artefact"]).read_text(encoding="utf-8").count("boom")


def test_command_detects_the_stdout_it_must_not_see():
    with tempfile.TemporaryDirectory() as tmp:
        out = run({"kind": "command",
                   "params": {"argv": [sys.executable, "-c", "print('traceback')"],
                              "expect": {"exit": "zero", "stdout_absent": "traceback"}}},
                  tree(Path(tmp)))
    assert out["status"] == "refuted"


# --- json ---------------------------------------------------------------------------


def test_json_follows_an_rfc6901_pointer():
    with tempfile.TemporaryDirectory() as tmp:
        ok = run({"kind": "json", "params": {"path": "data.json", "pointer": "/nested/a/1",
                                             "equals": 20}}, tree(Path(tmp)))
    assert ok["status"] == "supported"


def test_json_reports_a_missing_pointer_as_refuted():
    with tempfile.TemporaryDirectory() as tmp:
        out = run({"kind": "json", "params": {"path": "data.json", "pointer": "/nope",
                                              "equals": 1}}, tree(Path(tmp)))
    assert out["status"] == "refuted"
    assert "does not exist" in out["detail"]


def test_json_absent_mode():
    with tempfile.TemporaryDirectory() as tmp:
        out = run({"kind": "json", "params": {"path": "data.json", "pointer": "/version",
                                              "absent": True}}, tree(Path(tmp)))
    assert out["status"] == "refuted"


def test_json_without_a_value_proves_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        out = run({"kind": "json", "params": {"path": "data.json", "pointer": "/version"}},
                  tree(Path(tmp)))
    assert out["status"] == "unrunnable"
    assert "proves nothing" in out["detail"]


# --- http ---------------------------------------------------------------------------


def test_http_refuses_a_non_loopback_host():
    with tempfile.TemporaryDirectory() as tmp:
        out = run({"kind": "http", "params": {"url": "https://example.com/"}}, tree(Path(tmp)))
    assert out["status"] == "unrunnable"
    assert "loopback" in out["detail"]


def test_http_with_no_server_is_unrunnable_not_refuted():
    with tempfile.TemporaryDirectory() as tmp:
        out = run({"kind": "http", "params": {"url": "http://127.0.0.1:9/", "timeout": 2}},
                  tree(Path(tmp)))
    assert out["status"] == "unrunnable"


# --- diff ---------------------------------------------------------------------------


def _git_repo(tmp: Path) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp, check=True)
    subprocess.run(["git", "config", "user.email", "c@example.invalid"], cwd=tmp, check=True)
    subprocess.run(["git", "config", "user.name", "council"], cwd=tmp, check=True)
    (tmp / "app.py").write_text("one\ntwo\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=tmp, check=True)
    (tmp / "app.py").write_text("one\ntwo\nthree\n", encoding="utf-8")
    return tmp


def test_diff_without_a_base_is_unrunnable():
    with tempfile.TemporaryDirectory() as tmp:
        out = run({"kind": "diff", "params": {"path": "bad.py", "line": 1}}, tree(Path(tmp)))
    assert out["status"] == "unrunnable"
    assert "no base revision" in out["detail"]


def test_diff_separates_a_new_line_from_an_old_one():
    with tempfile.TemporaryDirectory() as tmp:
        root = _git_repo(Path(tmp))
        added = run({"kind": "diff", "params": {"path": "app.py", "line": 3}},
                    root, diff_base="HEAD")
        old = run({"kind": "diff", "params": {"path": "app.py", "line": 1}},
                  root, diff_base="HEAD")
    assert added["status"] == "supported", added["detail"]
    assert old["status"] == "refuted"


# --- dom ----------------------------------------------------------------------------


def test_dom_without_a_driver_is_unrunnable_and_says_why():
    with tempfile.TemporaryDirectory() as tmp:
        import probes

        original = probes.browser_driver
        probes.browser_driver = lambda: None
        try:
            out = run({"kind": "dom", "params": {"selector": "#app", "expect": "present"}},
                      tree(Path(tmp)))
        finally:
            probes.browser_driver = original
    assert out["status"] == "unrunnable"
    assert "not loaded" in out["detail"]


# --- adjudication: the control is what makes a claim blockable ----------------------


def test_a_supported_proof_with_no_control_is_uncontrolled():
    with tempfile.TemporaryDirectory() as tmp:
        out = proofs.adjudicate({"kind": "absent",
                                 "params": {"pattern": "unused_helper\\(", "exclude": ["bad.py"]}},
                                ctx_for(tree(Path(tmp))))
    assert out["status"] == "supported"
    assert out["admission"] == "uncontrolled"
    assert out["class"] == "unproven"


def test_a_refuted_control_makes_the_claim_proven():
    with tempfile.TemporaryDirectory() as tmp:
        out = proofs.adjudicate(
            {"kind": "absent",
             "params": {"pattern": "unused_helper\\(", "exclude": ["bad.py"]},
             "control": {"params": {"pattern": "unused_helper\\("}}},
            ctx_for(tree(Path(tmp))))
    assert out["admission"] == "proven", out
    assert out["control"]["status"] == "refuted"


def test_a_control_that_also_passes_is_the_vacuity_detector():
    """A pattern that matches nothing anywhere supports its claim and its negation alike."""
    with tempfile.TemporaryDirectory() as tmp:
        out = proofs.adjudicate(
            {"kind": "absent", "params": {"pattern": "no_such_symbol_anywhere"},
             "control": {"params": {"pattern": "no_such_symbol_anywhere"}}},
            ctx_for(tree(Path(tmp))))
    assert out["status"] == "supported"
    assert out["admission"] == "control_did_not_fail"
    assert out["class"] == "unproven"


def test_a_control_that_cannot_run_leaves_the_claim_unproven():
    with tempfile.TemporaryDirectory() as tmp:
        out = proofs.adjudicate(
            {"kind": "absent",
             "params": {"pattern": "unused_helper\\(", "exclude": ["bad.py"]},
             "control": {"kind": "command", "params": {"argv": ["curl", "http://x"],
                                                       "expect": {"exit": "zero"}}}},
            ctx_for(tree(Path(tmp))))
    assert out["admission"] == "uncontrolled"
    assert "could not run" in out["control"]["detail"]


def test_a_refuted_proof_stays_refuted_whatever_the_control_says():
    with tempfile.TemporaryDirectory() as tmp:
        out = proofs.adjudicate(
            {"kind": "absent", "params": {"pattern": "unused_helper"},
             "control": {"params": {"pattern": "unused_helper"}}},
            ctx_for(tree(Path(tmp))))
    assert out["status"] == "refuted" and out["admission"] == "refuted"


def test_evaluation_is_deterministic():
    with tempfile.TemporaryDirectory() as tmp:
        root = tree(Path(tmp))
        first = run({"kind": "absent", "params": {"pattern": "unused_helper"}}, root)
        second = run({"kind": "absent", "params": {"pattern": "unused_helper"}}, root)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


# --- the self-test and the CLI ------------------------------------------------------


def test_a_present_browser_that_cannot_render_fails_the_self_test():
    """The lane must not report `ok` when a driver exists and produced nothing — that is how an
    image with a broken chromium reported 10/10."""
    import probes

    with tempfile.TemporaryDirectory() as tmp:
        root = tree(Path(tmp))
        ctx = ctx_for(root)
        original = probes.browser_driver
        probes.browser_driver = lambda: "/bin/false"  # present, runs, produces no DOM
        try:
            cases = proofs._self_test_dom(root, ctx)
        finally:
            probes.browser_driver = original
    # Both directions are exercised now, and a browser that runs without rendering proves
    # neither of them.
    assert len(cases) == 2
    assert all(c["ok"] is False for c in cases), cases
    assert all(c["got"] == "unrunnable" for c in cases), cases


def test_an_unexercised_kind_exits_three_and_says_which():
    """The consequence of the lenient self-test, made impossible: no `0` when a lane never ran."""
    import contextlib
    import io

    import probes

    original = probes.browser_driver
    probes.browser_driver = lambda: None  # a host with no browser at all
    buffer = io.StringIO()
    try:
        with contextlib.redirect_stdout(buffer):
            code = proofs.main(["--self-test"])
    finally:
        probes.browser_driver = original
    out = buffer.getvalue()
    assert code == 3, out
    assert "INCOMPLETE" in out and "dom" in out
    # The summary must say the run was partial — the exact sentence a reader can quote.
    assert "2 not exercised" in out, out
    assert "18/18" not in out, out


def test_a_kind_exercised_in_one_direction_only_is_a_coverage_failure():
    """The regression that let `diff` ship untested: one direction is not coverage."""
    one_way = [{"kind": k, "want": "supported", "ok": True} for k in proofs.EXECUTORS]
    gaps = proofs._coverage_gaps(one_way)
    assert {g["kind"] for g in gaps} == set(proofs.EXECUTORS)
    both = one_way + [{"kind": k, "want": "refuted", "ok": True} for k in proofs.EXECUTORS]
    assert proofs._coverage_gaps(both) == []


def test_diff_finds_an_addition_in_the_first_of_two_hunks():
    """Measured before the fix: only the last hunk matched, so a genuine change at line 2 in a
    two-hunk diff came back `not added in this change`."""
    import subprocess as sp

    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        sp.run(["git", "init", "-q"], cwd=repo, check=True)
        sp.run(["git", "config", "user.email", "t@example.invalid"], cwd=repo, check=True)
        sp.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
        lines = [f"line{i} = 'original'" for i in range(1, 31)]
        (repo / "a.py").write_text("\n".join(lines) + "\n", encoding="utf-8")
        sp.run(["git", "add", "a.py"], cwd=repo, check=True)
        sp.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
        changed = list(lines)
        changed[1] = "line2 = 'changed'"
        changed[20] = "line21 = 'changed'"
        (repo / "a.py").write_text("\n".join(changed) + "\n", encoding="utf-8")
        ctx = proofs.Context(root=repo, artefact_dir=repo / ".artefacts", diff_base="HEAD")

        def status(line: int) -> str:
            return proofs.evaluate({"kind": "diff",
                                    "params": {"path": "a.py", "line": line, "mode": "added"}},
                                   ctx)["status"]

        first, last = status(2), status(21)
    assert first == "supported", "the first hunk was refuted"
    assert last == "supported"


def test_the_self_test_passes_on_this_host():
    cases, failures = proofs.self_test()
    assert len(cases) >= 10
    assert not failures, failures


def test_the_cli_exits_one_for_an_unproven_claim_and_zero_for_a_proven_one():
    with tempfile.TemporaryDirectory() as tmp:
        root = tree(Path(tmp))
        proof = root / "proof.json"
        proof.write_text(json.dumps({"kind": "absent",
                                     "params": {"pattern": "unused_helper\\(", "exclude": ["bad.py"]},
                                     "control": {"params": {"pattern": "unused_helper\\("}}}),
                         encoding="utf-8")
        proven = proofs.main(["--file", str(proof), "--root", str(root)])
        proof.write_text(json.dumps({"kind": "absent",
                                     "params": {"pattern": "unused_helper\\(", "exclude": ["bad.py"]}}),
                         encoding="utf-8")
        uncontrolled = proofs.main(["--file", str(proof), "--root", str(root), "--json"])
    assert proven == 0
    assert uncontrolled == 1


def test_the_cli_measures_a_real_git_diff_against_a_base():
    """`--base` is what makes the `diff` kind usable from the CLI at all — without it every diff
    claim is unrunnable, and a kind nobody can run is a kind that cannot be trusted."""
    with tempfile.TemporaryDirectory() as tmp:
        root = _git_repo(Path(tmp))
        proof = root / "p.json"
        proof.write_text(json.dumps({"kind": "diff", "params": {"path": "app.py", "line": 3},
                                     "control": {"params": {"path": "app.py", "line": 1}}}),
                         encoding="utf-8")
        added = proofs.main(["--file", str(proof), "--root", str(root), "--base", "HEAD"])
        proof.write_text(json.dumps({"kind": "diff", "params": {"path": "app.py", "line": 1}}),
                         encoding="utf-8")
        unchanged = proofs.main(["--file", str(proof), "--root", str(root), "--base", "HEAD"])
    assert added == 0, "an added line, with a refuted control, must be proven"
    assert unchanged == 1, "a line outside the diff must be refuted"


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
    raise SystemExit(1 if failures else 0)
