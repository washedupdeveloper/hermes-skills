"""Fixtures + tests for score_reviews.py — run with: python -m pytest tests/test_score_reviews.py

Reproduces the two archived council runs and the termination edges.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GATE = REPO / "scripts" / "score_reviews.py"

_GATE_MOD = None


def _gate_mod():
    """Import score_reviews as a module, for tests that exercise its functions
    directly rather than through the CLI."""
    global _GATE_MOD
    if _GATE_MOD is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("score_reviews", GATE)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _GATE_MOD = mod
    return _GATE_MOD


def _write_run(tmp_path: Path, scores: dict, blocking: bool = False) -> Path:
    """Minimal run dir: one file per dimension, no deterministic tools (beta=0)."""
    run = tmp_path / "run"
    run.mkdir(parents=True, exist_ok=True)
    for dim, llm in scores.items():
        findings = []
        if blocking and dim == "correctness":
            findings.append({"id": "COR-0001", "severity": "high", "status": "open",
                             "location": {"path": "scripts/install_bots.py", "line_range": "15"},
                             "claim": "PROFILES_DIR resolves outside HERMES_HOME on Windows"})
        (run / f"{dim}.json").write_text(json.dumps({
            "reviewer": f"{dim}-reviewer", "dimension": dim, "score": llm,
            "rationale": "fixture", "tools_run": [], "findings": findings,
            "schema_valid": True,
        }), encoding="utf-8")
    return run


def _gate(run: Path, *extra: str) -> subprocess.CompletedProcess:
    # score_reviews.py refuses to run without REVIEW_COUNCIL_DISPATCHED; this helper
    # spawns it as a program, which is exactly what the guard is about.
    env = dict(os.environ, REVIEW_COUNCIL_DISPATCHED="1")
    return subprocess.run(
        [sys.executable, str(GATE), str(run), *extra],
        capture_output=True, text=True, env=env,
    )


def test_run2_reproduces_escalate(tmp_path):
    """The archived run-2 numbers: 78/72/70/68/84, beta 0 -> 74.00, gate fails."""
    run = _write_run(tmp_path, {"security": 78, "correctness": 72, "readability": 70,
                                "architecture": 68, "performance": 84})
    proc = _gate(run)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "aggregate 74.00" in proc.stdout
    assert "GATE FAILED" in proc.stdout


def test_pass_when_above_threshold(tmp_path):
    """The rule, decoupled from the calibrated value: above the threshold passes.

    The threshold is named explicitly here so a recalibration cannot change what
    this test means. The DEFAULT threshold's behaviour has its own test.
    """
    run = _write_run(tmp_path, {"security": 90, "correctness": 88, "readability": 85,
                                "architecture": 82, "performance": 86})
    proc = _gate(run, "--threshold", "80")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "satisfied" in proc.stdout


def test_high_finding_blocks_even_with_high_score(tmp_path):
    """aggregate >= threshold but an open HIGH finding still fails the gate."""
    run = _write_run(tmp_path, {"security": 95, "correctness": 95, "readability": 95,
                                "architecture": 95, "performance": 95}, blocking=True)
    proc = _gate(run)
    assert proc.returncode == 1
    assert "COR-0001" in proc.stdout
    assert "OPEN BLOCKING FINDINGS" in proc.stdout


def test_beta_inert_when_no_tools(tmp_path):
    """beta=0 must make det inert: a vacuous det cannot inflate the score."""
    run = _write_run(tmp_path, {"security": 78, "correctness": 72, "readability": 70,
                                "architecture": 68, "performance": 84})
    out = json.loads(_gate(run, "--json").stdout)
    assert all(d["beta"] == 0.0 for d in out["per_dimension"])
    assert all(d["score"] == d["llm"] for d in out["per_dimension"])


def test_stack_detection(tmp_path):
    """Stacks are detected from marker files and source extensions."""
    py = tmp_path / "pyrepo"
    (py / "src").mkdir(parents=True)
    (py / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    (py / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (py / "src" / "b.py").write_text("y = 2\n", encoding="utf-8")
    stacks = _gate_mod().detect_stacks(py)
    assert "python" in stacks, stacks

    nix = tmp_path / "nixrepo"
    nix.mkdir()
    (nix / "flake.nix").write_text("{}\n", encoding="utf-8")
    (nix / "mod.nix").write_text("{}\n", encoding="utf-8")
    assert "nix" in _gate_mod().detect_stacks(nix)

    empty = tmp_path / "bare"
    empty.mkdir()
    assert _gate_mod().detect_stacks(empty) == ["generic"]


def test_beta_is_reachable_on_python_repo(tmp_path):
    """The whole point of per-stack tables: a Python repo can reach beta > 0.

    With the old Nix-only table, correctness expected nix/flake-check and beta
    was structurally 0 no matter what ran.
    """
    mod = _gate_mod()
    expected = mod.expected_tools("correctness", ["python"])
    assert "pytest" in expected and "py-compile" in expected
    assert "flake-check" not in expected

    # py-compile ran -> beta > 0
    beta, hit, miss = mod.measure_beta(
        [{"name": "py-compile", "ran": True, "parsed": True}], "correctness", ["python"])
    assert beta == 0.5, (beta, hit, miss)
    assert "py-compile" in hit


def test_tool_name_normalization():
    """`py_compile`, `py-compile`, `python -m py_compile`, `ruff.exe` all match.

    A one-character mismatch must not silently zero a dimension's beta.
    """
    mod = _gate_mod()
    for reported in ("py_compile", "py-compile", "PY-COMPILE", "python -m py_compile",
                     "/usr/bin/py-compile", "py-compile.exe"):
        beta, hit, _ = mod.measure_beta(
            [{"name": reported, "ran": True, "parsed": True}], "correctness", ["python"])
        assert beta > 0, f"{reported!r} did not match: {beta}"
        assert "py-compile" in hit, reported


def test_beta_unions_across_stacks(tmp_path):
    """A mixed repo expects the union of its stacks' tools."""
    mod = _gate_mod()
    expected = mod.expected_tools("readability", ["python", "nix"])
    assert "ruff" in expected and "mypy" in expected       # python
    assert "nixfmt" in expected and "deadnix" in expected  # nix


def test_det_uses_only_the_dimensions_own_tools():
    """§6: det[c] = geometric_mean(normalize(tool_signals_c)).

    Averaging every tool into every category made the readability number depend on
    bandit and the security number depend on mypy. That went unnoticed while beta
    < 1 let the reviewer's score dominate the result. At beta = 1 det IS the score,
    so the leak decides the verdict rather than merely colouring it.
    """
    mod = _gate_mod()
    tools = [
        # security: all clean
        {"tool": "bandit", "ran": True, "parsed": True, "signal": 100.0},
        {"tool": "secret-grep", "ran": True, "parsed": True, "signal": 100.0},
        {"tool": "statix", "ran": True, "parsed": True, "signal": 100.0},
        {"tool": "osv-scanner", "ran": True, "parsed": True, "signal": 100.0},
        # readability: one badly failing tool
        {"tool": "mypy", "ran": True, "parsed": True, "signal": 10.0},
    ]
    review = {"score": 95.0, "findings": [], "tools_run": tools}
    stacks = ["nix", "python"]

    security, _, _ = mod.deterministic_score(review, "security", stacks, 10.0)
    readability, _, _ = mod.deterministic_score(review, "readability", stacks, 10.0)
    architecture, _, _ = mod.deterministic_score(review, "architecture", stacks, 10.0)

    assert security > 90.0, f"security was dragged down by another dimension's tool: {security}"
    assert architecture > 90.0, f"architecture was dragged down: {architecture}"
    assert readability < 70.0, f"readability ignored its own failing tool: {readability}"


def test_det_ignores_a_tool_that_did_not_run():
    """A tool that did not run contributes no signal. Counting its absence as a
    zero would make a missing toolchain look like a broken repository."""
    mod = _gate_mod()
    ran = [{"tool": "ruff", "ran": True, "parsed": True, "signal": 100.0},
           {"tool": "mypy", "ran": True, "parsed": True, "signal": 100.0}]
    plus_absent = ran + [{"tool": "nixfmt", "ran": False, "parsed": False, "signal": None}]
    a, _, _ = mod.deterministic_score({"score": 90.0, "findings": [], "tools_run": ran},
                                      "readability", ["python"], 10.0)
    b, _, _ = mod.deterministic_score({"score": 90.0, "findings": [], "tools_run": plus_absent},
                                      "readability", ["python"], 10.0)
    assert a == b, f"a tool that did not run changed det: {a} != {b}"


def test_builtin_tools_need_no_install():
    """Built-in probes always count as available, so the framework runs bare."""
    mod = _gate_mod()
    assert "secret-grep" in mod.BUILTIN_TOOLS
    assert "py-compile" in mod.BUILTIN_TOOLS
    for dim in ("security", "correctness", "performance", "architecture"):
        expected = mod.expected_tools(dim, ["python"])
        assert any(t in mod.BUILTIN_TOOLS for t in expected), dim


def test_gate_accepts_stacks_override(tmp_path):
    """--stacks forces the beta denominator, overriding detection."""
    run = _write_run(tmp_path, {"security": 78, "correctness": 72, "readability": 70,
                                "architecture": 68, "performance": 84})
    out = json.loads(_gate(run, "--json", "--stacks", "nix").stdout)
    assert out["stacks"] == ["nix"]
    read = next(d for d in out["per_dimension"] if d["dimension"] == "readability")
    assert "nixfmt" in read["tools_missing"]


def test_partial_run_is_error_by_default(tmp_path):
    """A partial council cannot certify a pass (COR-0001)."""
    run = _write_run(tmp_path, {"security": 90, "correctness": 90})
    proc = _gate(run)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "partial council" in (proc.stdout + proc.stderr)


def test_unparseable_file_is_error(tmp_path):
    """One corrupt reviewer file fails the gate rather than being skipped."""
    run = _write_run(tmp_path, {"security": 90, "correctness": 90, "readability": 90,
                                "architecture": 90, "performance": 90})
    (run / "correctness.json").write_text("{ not json", encoding="utf-8")
    proc = _gate(run)
    assert proc.returncode == 2, proc.stdout + proc.stderr


def test_missing_dimensions_renormalize_with_opt_in(tmp_path):
    """--allow-partial scores on what was reviewed, not diluted toward zero."""
    run = _write_run(tmp_path, {"security": 90, "correctness": 90})
    out = json.loads(_gate(run, "--json", "--allow-partial").stdout)
    assert out["aggregate"] == 90.0
    assert out["missing_files"] == ["architecture", "performance", "readability"]


def test_empty_run_dir_is_error(tmp_path):
    run = tmp_path / "empty"
    run.mkdir()
    proc = _gate(run)
    assert proc.returncode == 2


def test_continuation_prompt_is_capped(tmp_path):
    run = _write_run(tmp_path, {"security": 10, "correctness": 10, "readability": 10,
                                "architecture": 10, "performance": 10}, blocking=True)
    proc = _gate(run, "--tail-chars", "200")
    assert len(proc.stdout) <= 400


# --- extracted verdict logic ------------------------------------------------
# The pass predicate is the most consequential line in the framework; it was buried
# mid-way through a 100-line loader, now it is a function.

def test_verdict_passes_with_aggregate_and_no_blockers():
    satisfied, reason = _gate_mod().verdict_summary(90.0, 80.0, [])
    assert satisfied
    assert "no blocking" in reason


def test_verdict_fails_below_threshold():
    satisfied, reason = _gate_mod().verdict_summary(70.0, 80.0, [])
    assert not satisfied
    assert "70.00 < threshold 80" in reason


def test_verdict_fails_on_blocking_findings_despite_a_perfect_aggregate():
    """The hard gate: a 99 aggregate cannot certify a pass while a high/critical
    finding is open. Without this, one strong dimension could paper over a
    critical defect elsewhere."""
    blocking = [{"id": "SEC-0001", "severity": "critical"}]
    satisfied, reason = _gate_mod().verdict_summary(99.0, 80.0, blocking)
    assert not satisfied
    assert "open high/critical" in reason


def test_verdict_reason_names_every_failing_condition():
    """Both failures must be reported, not just the first — the fix turn needs
    to know the aggregate fell AND findings are open."""
    blocking = [{"id": "SEC-0001", "severity": "critical"}]
    satisfied, reason = _gate_mod().verdict_summary(70.0, 80.0, blocking)
    assert not satisfied
    assert "< threshold" in reason and "open high/critical" in reason


def test_verdict_passes_exactly_at_threshold():
    """>= not >: the threshold is inclusive."""
    satisfied, _ = _gate_mod().verdict_summary(80.0, 80.0, [])
    assert satisfied


def test_renormalized_aggregate_over_a_partial_council():
    per = [{"dimension": "security", "score": 90.0},
           {"dimension": "correctness", "score": 70.0}]
    present = {"security": 0.30, "correctness": 0.25}
    expected = (0.30 / 0.55) * 90.0 + (0.25 / 0.55) * 70.0
    got = _gate_mod().renormalized_aggregate(present, per)
    assert abs(got - expected) < 1e-9


def test_renormalized_aggregate_is_not_diluted_by_absent_dimensions():
    """A partial run is scored on what it reviewed. If the absent dimensions
    counted as zero, a perfect two-dimension run would score ~55."""
    per = [{"dimension": "security", "score": 100.0},
           {"dimension": "correctness", "score": 100.0}]
    present = {"security": 0.30, "correctness": 0.25}
    assert _gate_mod().renormalized_aggregate(present, per) == 100.0


def test_load_reviews_separates_missing_from_invalid(tmp_path):
    (tmp_path / "security.json").write_text('{"schema_valid": true}', encoding="utf-8")
    (tmp_path / "correctness.json").write_text('{ not json at all', encoding="utf-8")
    reviews, missing, invalid = _gate_mod().load_reviews(tmp_path)
    assert "security" in reviews
    assert "correctness" not in reviews, "unparseable output must not be scored"
    assert len(invalid) == 1 and "correctness" in invalid[0]
    assert set(missing) == {"readability", "architecture", "performance"}


def test_load_reviews_rejects_self_declared_invalid_output(tmp_path):
    """A child that marks its own output schema_valid=false is not trustworthy
    enough to score — it must land in `invalid`, not `reviews`."""
    (tmp_path / "security.json").write_text(
        '{"schema_valid": false, "findings": []}', encoding="utf-8")
    reviews, missing, invalid = _gate_mod().load_reviews(tmp_path)
    assert "security" not in reviews
    assert any("schema_valid=false" in f for f in invalid)


# --- reproducibility --------------------------------------------------------

def test_score_is_independent_of_how_the_gate_is_invoked(tmp_path):
    """The same run dir must score the same with or without --repo.

    The harness records the repo in meta.json. Without reading it back, the
    findings term silently falls from a calibrated DENSITY to a raw COUNT, so the
    loop reports one number while a manual re-run reports another for identical
    data. Found by re-scoring a real run: 86.04 from the loop, 90.33 by hand.
    """
    run = _write_run(tmp_path, {"security": 80, "correctness": 80, "readability": 80,
                                "architecture": 80, "performance": 80})
    (run / "meta.json").write_text(json.dumps({
        "target_sha": "x", "mode": "working-tree", "round": 1,
        "stacks": ["python"], "repo": str(REPO),
    }), encoding="utf-8")

    bare = json.loads(_gate(run, "--json").stdout)["aggregate"]
    explicit = json.loads(_gate(run, "--json", "--repo", str(REPO)).stdout)["aggregate"]
    assert bare == explicit, f"invocation changed the score: {bare} vs {explicit}"


def test_resolve_repo_reads_meta_json(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    (run / "meta.json").write_text(json.dumps({"repo": str(REPO)}), encoding="utf-8")
    assert _gate_mod().resolve_repo(run) == REPO


def test_resolve_repo_ignores_a_missing_directory(tmp_path):
    """A recorded path that no longer exists must not be used — falling back is
    better than measuring a repo that is not there."""
    run = tmp_path / "run"
    run.mkdir()
    (run / "meta.json").write_text(json.dumps({"repo": str(tmp_path / "gone")}),
                                   encoding="utf-8")
    assert _gate_mod().resolve_repo(run) is None


# --- the threshold has ONE source of truth ----------------------------------

def test_calibrated_threshold_reads_the_manifest():
    """The shipped threshold is the calibrated recommendation, not a literal.

    It was hardcoded in three places (score_reviews.DEFAULT_THRESHOLD,
    council_loop's --threshold default, calibration.json's shipped_default), so a
    recalibration could not actually change what the gate enforced.
    """
    mod = _gate_mod()
    cal = json.loads((REPO / "scripts" / "calibration.json").read_text(encoding="utf-8"))
    assert mod.calibrated_threshold() == float(cal["threshold"]["recommended"])


def test_calibrated_threshold_falls_back_when_uncalibrated(tmp_path):
    """An uncalibrated checkout still runs — it just uses the fallback."""
    mod = _gate_mod()
    original = mod.CALIBRATION_PATH
    try:
        mod.CALIBRATION_PATH = tmp_path / "absent.json"
        mod._CALIBRATION_LOADED = False
        assert mod.calibrated_threshold() == mod.DEFAULT_THRESHOLD
    finally:
        mod.CALIBRATION_PATH = original
        mod._CALIBRATION_LOADED = False


def test_calibrated_threshold_degrades_on_a_malformed_manifest(tmp_path):
    """Corrupt JSON, a missing block, a non-numeric or non-positive value: each
    must fall back rather than raise inside the gate."""
    mod = _gate_mod()
    bad = tmp_path / "calibration.json"
    original = mod.CALIBRATION_PATH
    payloads = [
        "{ not json at all",
        '{"threshold": {}}',
        '{"threshold": {"recommended": "high"}}',
        '{"threshold": {"recommended": 0}}',
        '{"threshold": {"recommended": -5}}',
    ]
    try:
        for payload in payloads:
            bad.write_text(payload, encoding="utf-8")
            mod.CALIBRATION_PATH = bad
            mod._CALIBRATION_LOADED = False
            assert mod.calibrated_threshold() == mod.DEFAULT_THRESHOLD, payload
    finally:
        mod.CALIBRATION_PATH = original
        mod._CALIBRATION_LOADED = False


def test_a_score_just_below_the_calibrated_threshold_fails(tmp_path):
    """The gate enforces `calibrated_threshold()`, and an explicit --threshold overrides it.

    This used to prove the default had moved off a hardcoded 80 by scoring 85 and expecting
    a failure. The re-derived default IS 80.0 now (`docs/CALIBRATION.md`), so the fixture
    moves just under it: the point of the test is that the number comes from the manifest
    and is overridable, not that any particular number is hardcoded here.
    """
    run = _write_run(tmp_path, {"security": 79.5, "correctness": 79.5, "readability": 79.5,
                                "architecture": 79.5, "performance": 79.5})
    result = json.loads(_gate(run, "--json").stdout)
    assert result["threshold"] == 80.0, result["threshold"]
    assert result["aggregate"] < result["threshold"], result["aggregate"]
    assert _gate(run).returncode == 1, "79.5 must not satisfy the calibrated threshold"
    assert _gate(run, "--threshold", "79").returncode == 0


def test_an_explicit_threshold_still_overrides(tmp_path):
    """--threshold remains the caller's escape hatch."""
    run = _write_run(tmp_path, {"security": 85, "correctness": 85, "readability": 85,
                                "architecture": 85, "performance": 85})
    assert _gate(run, "--threshold", "80").returncode == 0


# --- severity-weighted density (§3) -----------------------------------------
# The numerator was a raw count of open findings, so a reviewer that RECORDED what
# it verified at `info` scored worse than one that stayed silent — the incentive
# pointed away from the diligence the council exists to reward.


def test_info_weighs_nothing():
    mod = _gate_mod()
    assert mod.weighted_open_findings([{"severity": "info", "status": "open"}]) == 0.0


def test_low_is_the_scale_anchor():
    """`low` must stay 1.0, or every d_star in calibration.json is invalidated."""
    mod = _gate_mod()
    assert mod.weighted_open_findings([{"severity": "low", "status": "open"}]) == 1.0


def test_severity_escalates():
    mod = _gate_mod()
    w = mod.weighted_open_findings
    values = [w([{"severity": s, "status": "open"}])
              for s in ("info", "low", "medium", "high", "critical")]
    assert values == sorted(values), values
    assert len(set(values)) == len(values), "each severity must weigh distinctly"


def test_non_open_findings_do_not_count():
    mod = _gate_mod()
    for status in ("fixed", "wontfix", "accepted"):
        assert mod.weighted_open_findings(
            [{"severity": "critical", "status": status}]) == 0.0


def test_unknown_severity_counts_as_a_defect():
    """Silence about a defect is the worse failure: an unrecognised severity is
    treated as a real finding, not dropped."""
    mod = _gate_mod()
    assert mod.weighted_open_findings([{"severity": "banana", "status": "open"}]) == 1.0
    assert mod.weighted_open_findings([{"status": "open"}]) == 1.0


def test_a_thorough_reviewer_does_not_score_worse_than_a_silent_one():
    """The regression this change exists for."""
    mod = _gate_mod()

    def det(findings):
        review = {
            "findings": findings,
            "tools_run": [{"name": "statix", "ran": True, "parsed": True, "signal": 100.0}],
        }
        score, _beta, _missing = mod.deterministic_score(review, "readability", ["nix"], 1.0)
        return score

    silent = det([])
    thorough = det([{"severity": "info", "status": "open"} for _ in range(6)])
    assert thorough == silent, f"info findings moved the score: {silent} -> {thorough}"

    # A real defect still costs, and a worse one costs more.
    low = det([{"severity": "low", "status": "open"}])
    medium = det([{"severity": "medium", "status": "open"}])
    critical = det([{"severity": "critical", "status": "open"}])
    assert silent > low > medium > critical, (silent, low, medium, critical)


# ---------------------------------------------------------------------------
# Invocation aliases. On a real run the reviewer reported
# `nix flake check --no-build --keep-going`, the probe table expects `flake-check`,
# and the generic rules produced {nix, nix-flake} — so the tool ran, beta could not
# see it, and correctness scored as if it had not. The canonical name is the
# SUBCOMMAND PAIR, which no generic join reaches.
# ---------------------------------------------------------------------------


def test_nix_flake_check_resolves_to_the_flake_check_tool():
    mod = _gate_mod()
    tools = [{"cmd": "nix flake check --no-build --keep-going  # 'all checks passed!'",
              "ran": True, "parsed": True}]
    beta, ran, missing = mod.measure_beta(tools, "correctness", ["nix"])
    assert "flake-check" in ran, (ran, missing)
    # correctness on nix expects flake-check AND nix-eval; only one ran.
    assert beta == 0.5, (beta, ran, missing)
    assert missing == ["nix-eval"], missing


def test_nix_instantiate_resolves_to_the_nix_eval_tool():
    mod = _gate_mod()
    tools = [{"cmd": "nix-instantiate --parse flake.nix", "ran": True, "parsed": True}]
    beta, ran, _missing = mod.measure_beta(tools, "correctness", ["nix"])
    assert "nix-eval" in ran, ran
    assert beta == 0.5, (beta, ran)


def test_the_alias_does_not_invent_a_match_it_should_not():
    """A bare `nix build` is not flake-check, and must not be credited as one."""
    mod = _gate_mod()
    assert "flake-check" not in mod.tool_name_candidates("nix build .#x")
    assert "flake-check" not in mod.tool_name_candidates("git flake check")


# ---------------------------------------------------------------------------
# An ARGUMENT containing a path must not destroy the command: on a real run of this
# repository `tool_name_candidates` stripped everything before the LAST `/` in the
# whole string, so
#   PATH=$TC/bin:$PATH python3 -m pytest tests/ -q  ->  {-q, -q-(308}
#   PATH=$TC/bin:$PATH ruff check scripts/ tests/   ->  {(all, (all-checks}
#   python3 -m py_compile scripts/*.py              ->  {*.py}
# The reviewers HAD run pytest, ruff and mypy: correctness 0.75, readability 0.60, so
# three of five dimensions were partly judgement. Worse, next-steps.md advised
# "install ruff, mypy (beta 0.60 -> 1.00)" for tools already installed and run.
# Only the EXECUTABLE may be path-stripped; a command's arguments are its own.
# ---------------------------------------------------------------------------

def test_a_reported_command_with_a_path_argument_still_names_its_tool():
    mod = _gate_mod()
    cases = {
        "PATH=$TC/bin:$PATH python3 -m pytest tests/ -q  (308 passed)": "pytest",
        "PATH=$TC/bin:$PATH ruff check scripts/ tests/  (All checks passed)": "ruff",
        "PATH=$TC/bin:$PATH mypy scripts/  (11 errors in 4 files)": "mypy",
        "python3 -m py_compile scripts/*.py": "py-compile",
        "PATH=$TC/bin:$PATH python3 -m compileall -q scripts/": "compileall",
    }
    for cmd, want in cases.items():
        got = mod.tool_name_candidates(cmd)
        assert want in got, f"{want!r} not in {sorted(got)} for {cmd!r}"


def test_a_path_assignment_prefix_is_not_the_executable():
    """`VAR=value cmd` is one command, and the tool is what follows the prefix."""
    mod = _gate_mod()
    assert "ruff" in mod.tool_name_candidates("TC=/nix/store/x ruff check .")
    assert "pytest" in mod.tool_name_candidates("A=1 B=2 python3 -m pytest")


def test_beta_is_1_when_every_expected_tool_reports_a_path_argument():
    """The end-to-end consequence: these three commands are enough for beta 1.0."""
    mod = _gate_mod()
    tools = [
        {"cmd": "PATH=$TC/bin:$PATH ruff check scripts/ tests/", "ran": True, "parsed": True},
        {"cmd": "PATH=$TC/bin:$PATH mypy scripts/", "ran": True, "parsed": True},
        {"cmd": "nixfmt --check flake.nix", "ran": True, "parsed": True},
        {"cmd": "statix check .", "ran": True, "parsed": True},
        {"cmd": "deadnix --fail .", "ran": True, "parsed": True},
    ]
    beta, ran, missing = mod.measure_beta(tools, "readability", ["nix", "python"])
    assert beta == 1.0, (beta, ran, missing)


def test_the_advice_says_not_run_rather_than_install():
    """`tools_missing` means "expected, not reported as run" -- not "absent".

    The two are different facts and the gate can only see the first: whether a tool
    is installed is the environment's answer, which `council doctor` reports. The
    wording used to be "install X", so a run whose reviewer had simply not invoked
    ruff and mypy advised installing tools that were pinned in the toolchain and, in
    that run, already run.
    """
    mod = _gate_mod()
    result = {
        "aggregate": 91.49,
        "threshold": 87.1141,
        "blocking": [],
        "per_dimension": [
            {"dimension": "readability", "score": 53.82, "beta": 0.6, "det": 94.5,
             "llm": 86.3, "tools_missing": ["ruff", "mypy"]},
        ],
    }
    ops = mod.improvement_opportunities(result, target=87.1141)
    beta_ops = [o for o in ops if o.get("kind") == "beta"]
    assert beta_ops, ops
    action = beta_ops[0]["action"]
    assert "not run" in action, action
    assert "install" not in action, action
    assert "ruff, mypy" in action, action


# --- scoring accuracy: dimension-aware blocking ----------------------------------
# Nine well-regarded repositories put 93 of 94 blocking findings in security and
# correctness. Those two are the hard requirements; the rest move the score without
# vetoing a merge, and a `critical` anywhere still blocks so no dimension loses its floor.

def _one_finding(dimension: str, severity: str):
    return {dimension: {"score": 95, "findings": [{
        "id": "X-1", "severity": severity, "status": "open",
        "location": {"path": "a.nix", "line_range": "1"},
        "claim": "fixture", "falsifiable_check": "true",
    }]}}


def test_security_high_blocks():
    mod = _gate_mod()
    assert mod.open_blocking(_one_finding("security", "high")), \
        "security is a hard requirement: a high must block"


def test_correctness_high_blocks():
    mod = _gate_mod()
    assert mod.open_blocking(_one_finding("correctness", "high")), \
        "correctness is a hard requirement: a high must block"


def test_readability_high_does_not_block():
    """A readability defect moves the score; it does not veto a merge."""
    mod = _gate_mod()
    assert not mod.open_blocking(_one_finding("readability", "high"))


def test_performance_high_does_not_block():
    """Measured on naersk: an IFD finding is real, and it is not a merge veto."""
    mod = _gate_mod()
    assert not mod.open_blocking(_one_finding("performance", "high"))


def test_critical_blocks_in_every_dimension():
    """The floor is not lost: a critical anywhere still blocks."""
    mod = _gate_mod()
    for dim in ("security", "correctness", "readability", "architecture", "performance"):
        assert mod.open_blocking(_one_finding(dim, "critical")), dim


def test_an_unknown_dimension_gets_the_strict_floor():
    """A dimension nobody classified must not pass on a `high`.

    This test used to assert `not open_blocking(... "high")` — the opposite of its own
    docstring — and passed because `DEFAULT_BLOCKING` was `{"critical"}`. Code, comment
    and test therefore agreed on the lenient behaviour while all three prose statements
    described the strict one. The assertion now says what the docstring says.
    """
    mod = _gate_mod()
    assert mod.open_blocking(_one_finding("brand_new", "high")), \
        "an unclassified dimension is not a licence to pass on a high"
    assert mod.open_blocking(_one_finding("brand_new", "critical"))
    assert not mod.open_blocking(_one_finding("brand_new", "medium"))


def test_a_blocking_finding_is_not_offered_as_an_improvement():
    """Section 4 skips findings section 1 already lists as required.

    The skip compared a SEVERITY against a dict keyed by DIMENSION
    (`sev in BLOCKING_SEVERITIES`), so it never fired and a blocking finding appeared
    twice in the plan: once as "must be fixed before this can pass", once as "improves
    the review". A reader told both things about one finding cannot tell which is true.
    """
    mod = _gate_mod()
    finding = {
        "id": "SEC-0001", "dimension": "security", "severity": "high", "status": "open",
        "claim": "hardcoded token", "location": {"path": "a.py", "line_range": "1"},
    }
    result = {
        "aggregate": 90.0,
        "threshold": 80.0,
        "blocking": [dict(finding)],
        "per_dimension": [
            {"dimension": "security", "score": 90.0, "beta": 1.0, "det": 90.0,
             "llm": 90.0, "findings": [dict(finding)]},
        ],
    }
    ops = mod.improvement_opportunities(result, target=80.0)
    naming = [o for o in ops if "SEC-0001" in str(o)]
    assert len(naming) == 1, f"listed {len(naming)} times: {[o.get('kind') for o in naming]}"
    assert naming[0]["kind"] == "blocking", naming[0]["kind"]

    # ...and a non-blocking finding in the same dimension is still offered.
    soft = dict(finding, id="SEC-0002", severity="low")
    result["per_dimension"][0]["findings"].append(soft)
    ops = mod.improvement_opportunities(result, target=80.0)
    assert any(o.get("id") == "SEC-0002" and o["kind"] == "finding" for o in ops), ops


# --- scoring accuracy: beta measures the code the repo is MADE OF ----------------

def test_incidental_stack_does_not_add_expected_tools(tmp_path):
    """Two Python files in a Nix repository used to make pytest/ruff/mypy/bandit
    expected, depressing beta on a repo with nothing to test in Python.

    Measured on nix-direnv: nix 77%, shell 23%, python dropped.
    """
    mod = _gate_mod()
    root = tmp_path / "mixed"
    (root / "nix").mkdir(parents=True)
    (root / "scripts").mkdir()
    (root / "flake.nix").write_text("{\n" + "  # nix\n" * 200 + "}\n", encoding="utf-8")
    (root / "scripts" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (root / "scripts" / "b.py").write_text("y = 2\n", encoding="utf-8")

    present = mod.detect_stacks(root)
    assert "python" in present, present
    assert "python" not in mod.relevant_stacks(root), mod.relevant_stacks(root)
    assert "nix" in mod.relevant_stacks(root)


def test_a_meaningful_second_stack_is_kept(tmp_path):
    """zero-to-nix is 49% nix and 43% javascript; both must count."""
    mod = _gate_mod()
    root = tmp_path / "polyglot"
    (root / "src").mkdir(parents=True)
    (root / "flake.nix").write_text("{\n" + "  # nix\n" * 100 + "}\n", encoding="utf-8")
    # Two files: detect_stacks needs at least two before it calls a language present.
    for name in ("a.ts", "b.ts"):
        (root / "src" / name).write_text("let x = 1;\n" * 45, encoding="utf-8")
    kept = mod.relevant_stacks(root)
    assert "nix" in kept and "javascript" in kept, kept


def test_stack_shares_are_fractions_that_sum_to_one(tmp_path):
    mod = _gate_mod()
    root = tmp_path / "r"
    root.mkdir()
    (root / "a.nix").write_text("x\n" * 75, encoding="utf-8")
    (root / "b.py").write_text("y\n" * 25, encoding="utf-8")
    shares = mod.stack_shares(root)
    assert abs(sum(shares.values()) - 1.0) < 1e-9, shares
    assert 0.70 < shares["nix"] < 0.80, shares


def test_relevant_stacks_never_returns_empty(tmp_path):
    """A marker-only repository keeps its stack rather than falling back to generic."""
    mod = _gate_mod()
    root = tmp_path / "mk"
    root.mkdir()
    (root / "Makefile").write_text("all:\n\techo hi\n", encoding="utf-8")
    assert mod.relevant_stacks(root), "must not be empty"


def test_a_checkout_under_a_skipped_name_still_counts(tmp_path):
    """`_SKIP_DIRS` must apply to the path RELATIVE to the repo root.

    The check used the absolute path's parts, so a checkout at
    `/somewhere/build/my-repo` had every file skipped: stacks came back empty and beta
    lost its denominator. Same latent bug in `detect_stacks`, fixed together.
    """
    mod = _gate_mod()
    root = tmp_path / "build" / "target" / "my-repo"
    root.mkdir(parents=True)
    (root / "flake.nix").write_text("{\n" + "  # nix\n" * 120 + "}\n", encoding="utf-8")
    (root / "a.nix").write_text("{ x = 1; }\n", encoding="utf-8")
    (root / "b.nix").write_text("{ y = 2; }\n", encoding="utf-8")

    assert "nix" in mod.detect_stacks(root), "absolute path parts leaked into the skip check"
    shares = mod.stack_shares(root)
    assert shares and shares.get("nix") == 1.0, shares
