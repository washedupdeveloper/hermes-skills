"""Termination tests for council_loop.py (FRAMEWORK §7/§8).

Stubs the orchestrator turn (run_hermes) and lets the REAL gate run, so the
loop's continue/stop decisions are exercised against the real scoring code.

Run standalone (no pytest needed):
    python tests/test_council_loop.py
"""
from __future__ import annotations

import contextlib
import importlib.util
import json
import os
import re
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("council_loop", REPO / "scripts" / "council_loop.py")
loop = importlib.util.module_from_spec(spec)
spec.loader.exec_module(loop)

# The loop runs the gate as a CHILD process, and a scripts/ module refuses to
# execute unless the dispatcher set REVIEW_COUNCIL_DISPATCHED — so these tests
# declare themselves the dispatcher, or the refusal masks what they assert.
os.environ.setdefault("REVIEW_COUNCIL_DISPATCHED", "1")


# --- the agent turn must NOT inherit the dispatch variable --------------------
# A spawned turn inherited the env guard while reading untrusted content: measured,
# `env | grep REVIEW_COUNCIL_DISPATCHED` returned 1 and `inject_defects.py --out V`
# destroyed V, refused in a clean shell. Not a boundary — an agent can set it — but
# the framework must not hand it over.

def test_the_agent_environment_drops_the_dispatch_variable():
    saved = os.environ.get("REVIEW_COUNCIL_DISPATCHED")
    os.environ["REVIEW_COUNCIL_DISPATCHED"] = "1"
    try:
        env = loop.agent_env()
    finally:
        if saved is None:
            os.environ.pop("REVIEW_COUNCIL_DISPATCHED", None)
        else:
            os.environ["REVIEW_COUNCIL_DISPATCHED"] = saved
    assert "REVIEW_COUNCIL_DISPATCHED" not in env, (
        "an agent turn would inherit the guard's variable and the module guard "
        "would be inert inside the run"
    )
    assert env.get("HERMES_ACCEPT_HOOKS") == "1", "hook consent must still be set"

DIMS = ["security", "correctness", "readability", "architecture", "performance"]
# Shipped default sample count, named so asserts test the SAMPLING, not a literal
# that happens to equal len(DIMS).
SAMPLES = 5
# Only the reviewer prompt carries a per-dimension output path; the aggregation
# prompt carries the run directory.
_OUT_PATH_RE = re.compile(r"exactly this path:\s+(\S+)")
_ROUND_RE = re.compile(r"Round:\s*(\d+)")
# The generalist prompt is identified by its output path `generalist-N.json`: the
# goals prompt also says "exactly this path:", so the filename distinguishes them.
_GENERALIST_RE = re.compile(r"exactly this path:\s+(\S*generalist-\d+\.json)")


# Both prompts share markers ("exactly this path:", "Run directory:"), so each
# predicate requires the distinguishing pair.
def _is_reviewer(prompt: str) -> bool:
    """The reviewer turn is the generalist one — it writes `generalist-N.json`."""
    return bool(_GENERALIST_RE.search(prompt))


def _is_aggregate(prompt: str) -> bool:
    """The aggregation turn names the run directory — so does the goal review."""
    return "Run directory:" in prompt and "THE GOALS YOU SET FOR THIS ROUND" not in prompt


def make_stub(scores_per_round, blocking_rounds=(), reuse_findings=False,
              goals_fail=False):
    """Return a fake run_hermes that writes one generalist sample per turn.

    The real loop spawns ONE profile `samples` times; each sample returns findings
    that name the dimension they belong to, and the loop buckets them into the
    per-dimension files the gate reads. The stub mirrors that, so the round, the
    sampling and the bucketing are all exercised for real.
    """
    calls = {"n": 0, "reviewers": 0, "aggregates": 0, "fixes": 0,
             "goals": 0, "goal_reviews": 0, "spawns": []}

    def stub(binary, repo, prompt, timeout, log, profile=None):
        calls["n"] += 1
        calls["spawns"].append({"profile": profile, "prompt": prompt})

        # Most specific FIRST: the goals prompt also says "exactly this path:", so
        # the reviewer branch would claim it and fail its markers.
        if "set this round's goals" in prompt:
            calls["goals"] += 1
            if not goals_fail:
                path_match = _OUT_PATH_RE.search(prompt)
                round_match = _ROUND_RE.search(prompt)
                if path_match:
                    target = Path(path_match.group(1).strip())
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(json.dumps({
                        "round": int(round_match.group(1)) if round_match else 1,
                        "goals": [{"dimension": d, "objective": f"fixture goal: {d}",
                                   "acceptance": "fixture acceptance",
                                   "focus": ["x.py"]} for d in DIMS],
                    }), encoding="utf-8")
            return (1 if goals_fail else 0), "goals turn"

        if "THE GOALS YOU SET FOR THIS ROUND" in prompt:
            calls["goal_reviews"] += 1
            return 0, "goal review turn"

        match = _OUT_PATH_RE.search(prompt)
        if not match:
            # Not a reviewer: aggregation names the run directory, the fix turn
            # neither.
            if "Run directory:" in prompt:
                calls["aggregates"] += 1
                return 0, "aggregate turn"
            calls["fixes"] += 1
            return 0, "fix turn"

        out_path = Path(match.group(1).strip())
        round_match = _ROUND_RE.search(prompt)
        assert round_match, "reviewer prompt is missing its round marker"
        idx = int(round_match.group(1)) - 1
        calls["reviewers"] += 1

        scores = scores_per_round[min(idx, len(scores_per_round) - 1)]
        blocking = idx in blocking_rounds
        fid_round = 0 if reuse_findings else idx
        out_path.parent.mkdir(parents=True, exist_ok=True)

        # One low-severity finding per DIMENSION keeps the novelty signal alive, so
        # tests of OTHER termination paths are not cut short by the k-window check.
        # reuse_findings=True re-emits the SAME ids — what the novelty test needs.
        findings = [{"id": f"{dim[:3].upper()}-{fid_round:04d}", "dimension": dim,
                     "severity": "low", "status": "open",
                     "location": {"path": "x.py", "line_range": "1-2"},
                     "claim": f"fixture noise in {dim}"} for dim in DIMS]
        if blocking:
            findings.append({"id": f"COR-BLK-{idx:04d}", "dimension": "correctness",
                             "severity": "high", "status": "open",
                             "location": {"path": "x.py", "line_range": "1-2"},
                             "claim": "fixture blocker"})
        out_path.write_text(json.dumps({
            "reviewer": "council-generalist",
            "scores": {d: scores[d] for d in DIMS},
            "findings": findings,
        }), encoding="utf-8")
        return 0, "review turn"

    return stub, calls


@contextlib.contextmanager
def profiles_installed():
    """A HERMES_HOME with both council profiles, as a real machine has.

    The loop refuses to run without them -- that is the preflight's whole point --
    so a test that exercises a run has to provide them. Without this the tests
    fall through to the DEVELOPER'S ~/.hermes: they pass on a machine with the
    council installed and fail in a sandbox, which makes the suite depend on the
    host rather than on the code.
    """
    real = os.environ.get("HERMES_HOME")
    with tempfile.TemporaryDirectory() as td:
        for name in (loop.ORCHESTRATOR_PROFILE, loop.GENERALIST_PROFILE):
            (Path(td) / "profiles" / name).mkdir(parents=True)
        os.environ["HERMES_HOME"] = td
        try:
            yield
        finally:
            if real is None:
                os.environ.pop("HERMES_HOME", None)
            else:
                os.environ["HERMES_HOME"] = real


def run_loop(tmp, scores_per_round, **kwargs):
    """Run main() with a stubbed fan-out; return the exit code + outcome."""
    stub, calls = make_stub(
        scores_per_round,
        blocking_rounds=kwargs.pop("blocking_rounds", ()),
        reuse_findings=kwargs.pop("reuse_findings", False),
        goals_fail=kwargs.pop("goals_fail", False),
    )
    orig = (loop.run_hermes, loop.hermes_bin, loop.run_probes, loop.git_sha)
    loop.run_hermes = stub
    loop.hermes_bin = lambda: "hermes-stub"
    # Real probes shell out and take minutes; git_sha would need a real repo.
    loop.run_probes = lambda *a, **k: []
    loop.git_sha = lambda *a, **k: "stub-sha"
    try:
        argv = [str(tmp), "--run-root", str(Path(tmp) / "rc"), "--timeout", "5"]
        # Pin the threshold unless the test names one: these exercise LOOP LOGIC,
        # and the shipped default comes from scripts/calibration.json, so leaving
        # it implicit would fail them on a recalibration. Its own behaviour has a test.
        if "threshold" not in kwargs:
            argv += ["--threshold", "80"]
        for key, value in kwargs.items():
            argv += [f"--{key.replace('_', '-')}", str(value)]
        with profiles_installed():
            rc = loop.main(argv)
        outcome = json.loads((Path(tmp) / "rc" / "outcome.json").read_text(encoding="utf-8"))
        return rc, outcome, calls
    finally:
        (loop.run_hermes, loop.hermes_bin, loop.run_probes, loop.git_sha) = orig


PASS = {"security": 92, "correctness": 90, "readability": 88, "architecture": 85, "performance": 86}
FAIL = {"security": 78, "correctness": 72, "readability": 70, "architecture": 68, "performance": 84}

# Strictly better than PASS, to exercise climbing above the minimum while rising.
BETTER = {"security": 96, "correctness": 95, "readability": 94, "architecture": 93, "performance": 94}
BETTER2 = {"security": 99, "correctness": 98, "readability": 97, "architecture": 96, "performance": 97}
WORSE = {"security": 70, "correctness": 60, "readability": 58, "architecture": 55, "performance": 60}


def test_satisfied_first_round():
    with tempfile.TemporaryDirectory() as td:
        rc, outcome, _ = run_loop(Path(td), [PASS], mode="advisory", max_rounds=1)
        assert rc == 0, outcome
        assert outcome["outcome"] == "satisfied"


def test_advisory_never_edits():
    """advisory stops after the review even though the gate failed."""
    with tempfile.TemporaryDirectory() as td:
        rc, outcome, calls = run_loop(Path(td), [FAIL], mode="advisory", max_rounds=3)
        assert rc == 1, outcome
        assert outcome["outcome"] == "escalate"
        assert "advisory" in outcome["reason"]
        assert calls["fixes"] == 0, "advisory must not run a fix turn"
        assert calls["reviewers"] == 5, "one reviewer per dimension"


def test_full_applies_fix_then_passes():
    """full: round 1 fails, fix turn runs, round 2 passes."""
    with tempfile.TemporaryDirectory() as td:
        rc, outcome, calls = run_loop(Path(td), [FAIL, PASS], mode="full", max_rounds=2)
        assert rc == 0, outcome
        assert outcome["outcome"] == "satisfied"
        # FAIL -> 74.00; PASS -> the weighted mean of 92/90/88/85/86 = 89.05
        assert outcome["scores"] == [74.0, 89.05], outcome["scores"]
        assert calls["reviewers"] == 10, "5 reviewers x 2 rounds"
        assert calls["aggregates"] == 2, "one aggregation per round"
        assert calls["fixes"] == 1, "one fix turn between the rounds"


def test_stall_detected():
    """Two rounds with improvement below epsilon -> stalled, escalate."""
    with tempfile.TemporaryDirectory() as td:
        rc, outcome, _ = run_loop(Path(td), [FAIL, FAIL], mode="full", max_rounds=3)
        assert rc == 1, outcome
        assert "stall" in outcome["reason"]


def test_oscillation_detected():
    """Strictly regressing scores across 3 rounds -> oscillation, escalate."""
    d2 = {"security": 62, "correctness": 60, "readability": 58, "architecture": 56, "performance": 60}
    d3 = {"security": 50, "correctness": 48, "readability": 46, "architecture": 44, "performance": 48}
    with tempfile.TemporaryDirectory() as td:
        rc, outcome, _ = run_loop(Path(td), [FAIL, d2, d3], mode="full", max_rounds=3)
        assert rc == 1, outcome
        assert "oscillat" in outcome["reason"], outcome["reason"]


def test_novelty_k_window_stops_loop():
    """Scores improve but the SAME findings keep recurring -> novelty (k) fires.

    This is the COR-0002/RD-0001 defect: --k must actually terminate the loop.
    """
    improving = [
        {"security": 40, "correctness": 40, "readability": 40, "architecture": 40, "performance": 40},
        {"security": 60, "correctness": 60, "readability": 60, "architecture": 60, "performance": 60},
        {"security": 75, "correctness": 75, "readability": 75, "architecture": 75, "performance": 75},
    ]
    with tempfile.TemporaryDirectory() as td:
        rc, outcome, _ = run_loop(Path(td), improving, mode="full", max_rounds=4,
                                  reuse_findings=True, k=2)
        assert rc == 1, outcome
        assert "novelty" in outcome["reason"], outcome["reason"]
        assert outcome["scores"] == [40.0, 60.0, 75.0], outcome["scores"]


def test_round_cap():
    """Improving but never reaching threshold exhausts the cap."""
    improving = [
        {"security": 40, "correctness": 40, "readability": 40, "architecture": 40, "performance": 40},
        {"security": 55, "correctness": 55, "readability": 55, "architecture": 55, "performance": 55},
        {"security": 70, "correctness": 70, "readability": 70, "architecture": 70, "performance": 70},
    ]
    with tempfile.TemporaryDirectory() as td:
        rc, outcome, _ = run_loop(Path(td), improving, mode="full", max_rounds=3)
        assert rc == 1, outcome
        assert outcome["outcome"] == "escalate"


def test_blocking_finding_prevents_pass():
    """High score but an open HIGH finding in round 1 -> not satisfied."""
    with tempfile.TemporaryDirectory() as td:
        rc, outcome, _ = run_loop(Path(td), [PASS], mode="advisory", max_rounds=1,
                                  blocking_rounds=(0,))
        assert rc == 1, outcome
        assert outcome["outcome"] == "escalate"


def test_project_inference(tmp_path):
    """No path argument -> infer from cwd (nearest git root, else markers)."""
    # A nested directory inside a git root resolves to the git root.
    root = tmp_path / "proj"
    (root / ".git").mkdir(parents=True)
    nested = root / "src" / "pkg"
    nested.mkdir(parents=True)
    got, why, confident = loop.find_project_root(nested)
    assert got == root.resolve(), got
    assert "git" in why
    assert confident is True

    # No git root: fall back to an agent context file.
    plain = tmp_path / "plain" / "sub"
    plain.mkdir(parents=True)
    (tmp_path / "plain" / "AGENTS.md").write_text("# rules", encoding="utf-8")
    got, why, confident = loop.find_project_root(plain)
    assert got == (tmp_path / "plain").resolve(), got
    assert "AGENTS.md" in why
    assert confident is True

    # Nothing at all: report the directory but flag low confidence, so the caller
    # can refuse instead of reviewing an arbitrary tree.
    bare = tmp_path / "bare"
    bare.mkdir()
    got, why, confident = loop.find_project_root(bare)
    assert got == bare.resolve()
    assert "no project marker" in why
    assert confident is False


def test_explicit_path_beats_inference(tmp_path):
    """An explicit path always wins over cwd inference, and is confident."""
    explicit = tmp_path / "elsewhere"
    explicit.mkdir()
    got, why, confident = loop.resolve_project(str(explicit))
    assert got == explicit.resolve()
    assert why == "explicit path"
    assert confident is True


def test_unanchored_session_refuses(tmp_path):
    """A session whose cwd is not a project must not be reviewed silently."""
    bare = tmp_path / "home"
    bare.mkdir()
    orig_cwd = Path.cwd
    Path.cwd = staticmethod(lambda: bare)
    try:
        rc = loop.main(["--dry-run"])
        assert rc == 2, f"expected refusal (2), got {rc}"
    finally:
        Path.cwd = orig_cwd


# --- the adaptive termination ladder (§8, M8) --------------------------------
#
# The threshold is the MINIMUM; everything above it is desirable. These lived in a
# 170-line main() reachable only by a full council; extracted, each rule is
# independently testable.

def _decide(**kw):
    """Call decide_stop with permissive defaults; override per test."""
    base = dict(round_no=2, max_rounds=8, min_rounds=1, met_minimum=False,
                scores=[50.0, 70.0], epsilon=0.5, no_new_rounds=0, k=2,
                budget_spent=False, mode="full",
                confirm_fn=lambda _prompt: True)
    base.update(kw)
    return loop.decide_stop(**base)


def test_decide_continues_while_improving_below_the_minimum():
    assert _decide() is None


def test_decide_continues_when_minimum_met_and_still_climbing():
    """Above the minimum is desirable but not required — the loop keeps
    climbing while it is still gaining ground."""
    assert _decide(met_minimum=True, scores=[85.0, 90.0]) is None


def test_decide_stops_as_satisfied_once_gains_stall_above_the_minimum():
    """The key behaviour: once the minimum is met and gains stop, stop and plan
    the remainder rather than grinding toward the theoretical maximum."""
    outcome, reason = _decide(met_minimum=True, scores=[88.0, 88.2])
    assert outcome == "satisfied"
    assert "minimum met" in reason
    assert "planning the remainder" in reason


def test_decide_sees_one_more_round_when_there_is_no_trend_yet():
    """A satisfied round 1 has no trend to judge, so take one more round before
    deciding the gains have stopped."""
    assert _decide(round_no=1, met_minimum=True, scores=[90.0]) is None


def test_decide_stops_on_budget_with_minimum_met():
    outcome, reason = _decide(met_minimum=True, budget_spent=True)
    assert outcome == "satisfied", "budget spent but the minimum was met"
    assert "budget" in reason


def test_decide_escalates_on_budget_below_the_minimum():
    outcome, reason = _decide(budget_spent=True)
    assert outcome == "escalate"
    assert "budget" in reason


def test_decide_round_cap_reports_the_outcome_truthfully():
    """Hitting the cap is not a failure if the minimum was already met."""
    outcome, reason = _decide(round_no=8, max_rounds=8, met_minimum=True)
    assert outcome == "satisfied"
    assert "round cap" in reason
    # The reason must not contradict the outcome: clearing the minimum is never
    # described as failing to.
    assert "without clearing" not in reason, reason
    assert "minimum met" in reason
    outcome, reason = _decide(round_no=8, max_rounds=8, met_minimum=False)
    assert outcome == "escalate"
    assert "without clearing the minimum" in reason


def test_decide_budget_reason_matches_the_outcome():
    _, reason = _decide(met_minimum=True, budget_spent=True)
    assert "without clearing" not in reason, reason
    _, reason = _decide(met_minimum=False, budget_spent=True)
    assert "budget" in reason


def test_decide_hard_limits_outrank_min_rounds():
    """A cap or budget must end the run even inside the min-rounds floor —
    otherwise the floor could overrun a hard limit."""
    assert _decide(round_no=1, min_rounds=5, max_rounds=1) is not None
    assert _decide(round_no=1, min_rounds=5, budget_spent=True) is not None


def test_decide_min_rounds_forces_another_attempt():
    """The floor: one unlucky round cannot end the run."""
    assert _decide(round_no=1, min_rounds=3, met_minimum=False,
                   scores=[10.0]) is None


def test_decide_oscillation_needs_three_scores():
    assert _decide(scores=[80.0, 70.0]) is None, "two points is not a trend"
    outcome, reason = _decide(scores=[80.0, 70.0, 60.0])
    assert outcome == "escalate"
    assert "oscillation" in reason


def test_decide_ignores_non_monotonic_scores():
    """60 -> 80 -> 70 is noise, not a regression. Only a strictly decreasing run
    is an oscillation."""
    assert _decide(scores=[60.0, 80.0, 70.0]) is None


def test_decide_stalled_below_the_minimum_escalates():
    outcome, reason = _decide(scores=[50.0, 50.2])
    assert outcome == "escalate"
    assert "stalled" in reason


def test_decide_novelty_window_fires_at_k():
    assert _decide(no_new_rounds=1, k=2) is None, "k consecutive means k, not k-1"
    outcome, reason = _decide(no_new_rounds=2, k=2)
    assert outcome == "escalate"
    assert "novelty" in reason


def test_decide_advisory_mode_never_applies_fixes():
    outcome, reason = _decide(mode="advisory")
    assert outcome == "escalate"
    assert "advisory" in reason


def test_decide_semi_mode_honours_refusal():
    outcome, reason = _decide(mode="semi", confirm_fn=lambda _p: False)
    assert outcome == "escalate"
    assert "not approved" in reason


def test_decide_semi_mode_proceeds_on_approval():
    assert _decide(mode="semi", confirm_fn=lambda _p: True) is None


def test_out_of_budget():
    assert loop.out_of_budget(100.0, 0.0, now=9999.0) is False, "0 means unlimited"
    assert loop.out_of_budget(100.0, 50.0, now=120.0) is False
    assert loop.out_of_budget(100.0, 50.0, now=150.0) is True
    assert loop.out_of_budget(100.0, 50.0, now=999.0) is True


def test_update_novelty_tracks_and_resets_the_streak():
    original = loop.count_new_verified
    try:
        loop.count_new_verified = lambda rd, seen: (2, seen | {"A", "B"})
        count, seen, streak = loop.update_novelty(Path("."), set(), 0, 2)
        assert (count, streak) == (2, 0)

        loop.count_new_verified = lambda rd, seen: (0, seen)
        count, seen, streak = loop.update_novelty(Path("."), seen, 0, 2)
        assert (count, streak) == (0, 1)
        count, seen, streak = loop.update_novelty(Path("."), seen, 1, 2)
        assert streak == 2, "the streak must accumulate across barren rounds"

        loop.count_new_verified = lambda rd, seen: (1, seen | {"C"})
        count, seen, streak = loop.update_novelty(Path("."), seen, 2, 2)
        assert streak == 0, "a new finding must reset the no-new streak"
    finally:
        loop.count_new_verified = original


def test_build_parser_defaults_match_the_documented_contract():
    args = loop.build_parser().parse_args([])
    # The default is what a bare run USES, not what the parser stores: the config
    # may set it, so the contract is asserted after resolution.
    mode, samples, max_rounds, _ = loop.resolve_review_defaults(
        args.mode, args.samples, args.max_rounds, args.threshold, {})
    assert mode == "full", "autonomy is the point; semi/advisory are opt-in"
    assert samples == 5
    assert max_rounds == 8
    assert args.threshold is None, "resolved from calibration.json, never hardcoded"
    assert args.epsilon == 0.5
    assert args.min_rounds == 1
    assert args.budget_seconds == 0.0, "0 means no budget limit"
    assert args.repo is None, "no path means infer from the session"


# --- the next-steps plan ----------------------------------------------------

def _verdict(aggregate=74.0, threshold=80.0, blocking=(), dims=None):
    dims = dims or [
        {"dimension": "security", "score": 60.0, "beta": 1.0, "det": 60.0,
         "llm": 60.0, "tools_missing": []},
        {"dimension": "correctness", "score": 95.0, "beta": 1.0, "det": 95.0,
         "llm": 95.0, "tools_missing": []},
    ]
    blocking = list(blocking)
    satisfied = aggregate >= threshold and not blocking
    return {"aggregate": aggregate, "threshold": threshold,
            "status": "satisfied" if satisfied else "not_satisfied",
            "blocking": blocking, "per_dimension": dims}


def test_plan_leads_with_required_work():
    verdict = _verdict(blocking=[{"dimension": "security", "id": "SEC-0001",
                                  "severity": "critical", "claim": "hardcoded key",
                                  "location": {"path": "a.py", "line_range": "3-4"}}])
    text = loop.render_next_steps(
        result=verdict, history=[{"round": 1, "aggregate": 74.0, "gate_rc": 1}],
        outcome="escalate", reason="round cap reached", threshold=80.0,
        repo=Path("."), mode="full", rounds_used=1)
    assert "# Review-council next steps" in text
    assert "SEC-0001" in text
    assert "A. Required to meet the minimum" in text
    assert "B. Desirable" in text
    assert text.index("## A.") < text.index("## B."), "required must come first"


def test_plan_is_produced_even_when_satisfied():
    """The plan is the handover artifact on EVERY termination — a satisfied run
    still gets the desirable remainder, ranked."""
    text = loop.render_next_steps(
        result=_verdict(aggregate=91.0), history=[{"round": 1, "aggregate": 91.0,
                                                   "gate_rc": 0}],
        outcome="satisfied", reason="minimum met", threshold=80.0,
        repo=Path("."), mode="full", rounds_used=1)
    assert "SATISFIED" in text
    assert "meets the minimum" in text
    assert "Nothing outstanding" in text, "no required work when satisfied"


def test_plan_ranks_desirable_work_by_points_potential():
    """Priority is a number, not prose: higher-weight dimensions with more
    headroom must sort first."""
    verdict = _verdict(aggregate=85.0, dims=[
        {"dimension": "security", "score": 70.0, "beta": 1.0, "det": 70.0,
         "llm": 70.0, "tools_missing": []},        # weight .30 -> .30*30 = 9.0
        {"dimension": "performance", "score": 70.0, "beta": 1.0, "det": 70.0,
         "llm": 70.0, "tools_missing": []},        # weight .10 -> .10*30 = 3.0
    ])
    text = loop.render_next_steps(
        result=verdict, history=[], outcome="satisfied", reason="minimum met",
        threshold=80.0, repo=Path("."), mode="full", rounds_used=1)
    assert text.index("security: 70.0") < text.index("performance: 70.0")


def test_plan_includes_the_trajectory_and_how_to_resume():
    text = loop.render_next_steps(
        result=_verdict(), history=[
            {"round": 1, "aggregate": 46.07, "gate_rc": 1},
            {"round": 2, "aggregate": 85.23, "gate_rc": 1},
        ],
        outcome="escalate", reason="round cap reached", threshold=80.0,
        repo=Path("."), mode="full", rounds_used=2)
    assert "46.07" in text and "85.23" in text
    assert "+39.16" in text, "net movement across the run"
    assert "## C. How to resume" in text
    assert "council_loop.py" in text


def test_plan_handles_a_verdict_with_no_dimensions():
    """A gate error must not crash the handover."""
    text = loop.render_next_steps(
        result={"aggregate": None, "threshold": 80.0, "blocking": [],
                "per_dimension": []},
        history=[], outcome="escalate", reason="gate error", threshold=80.0,
        repo=Path("."), mode="full", rounds_used=1)
    assert "# Review-council next steps" in text


def test_plan_does_not_call_a_blocked_run_below_the_minimum():
    """The score requirement and the blocking gate are independent.

    A run whose aggregate clears the minimum but is blocked by a finding must NOT
    be described as 'BELOW the minimum' — that was a real bug, and it sent the
    reader looking at the wrong thing entirely.
    """
    verdict = _verdict(aggregate=85.23, blocking=[
        {"dimension": "readability", "id": "RD-0001", "severity": "high",
         "claim": "no docstring"}])
    text = loop.render_next_steps(
        result=verdict, history=[], outcome="escalate",
        reason="round cap reached", threshold=80.0,
        repo=Path("."), mode="full", rounds_used=2)
    assert "meets the minimum" in text
    assert "BELOW the minimum" not in text
    assert "Blocked by" in text and "RD-0001" in text


def test_plan_marks_dimensions_required_only_when_the_score_is_short():
    """With the aggregate already above the minimum, no dimension is 'required'
    even if that dimension's own score is under the threshold."""
    verdict = _verdict(aggregate=85.0, dims=[
        {"dimension": "security", "score": 40.0, "beta": 1.0, "det": 40.0,
         "llm": 40.0, "tools_missing": []},
        {"dimension": "correctness", "score": 100.0, "beta": 1.0, "det": 100.0,
         "llm": 100.0, "tools_missing": []},
    ])
    text = loop.render_next_steps(
        result=verdict, history=[], outcome="satisfied", reason="minimum met",
        threshold=80.0, repo=Path("."), mode="full", rounds_used=1)
    assert "Nothing outstanding" in text
    assert "security: 40.0 -> " not in text, (
        "a dimension below the threshold is not 'required' once the aggregate passes"
    )
    assert "security: 40.0 — raise toward 100" in text


def test_priority_digest_marks_required_and_desirable():
    verdict = _verdict(blocking=[{"dimension": "security", "id": "SEC-0001",
                                  "severity": "critical", "claim": "key"}])
    digest = loop.priority_digest(verdict, 80.0)
    assert "[REQUIRED]" in digest
    assert "SEC-0001" in digest


def test_plan_is_written_to_the_run_dir_on_escalate():
    """The handover artifact must exist on disk, not just in the return value."""
    with tempfile.TemporaryDirectory() as td:
        rc, outcome, _ = run_loop(Path(td), [FAIL, FAIL], mode="full", max_rounds=2)
        assert rc == 1, outcome
        plan = Path(td) / "rc" / "next-steps.md"
        assert plan.exists(), "next-steps.md must be written on every termination"
        text = plan.read_text(encoding="utf-8")
        assert "Required to meet the minimum" in text
        assert outcome["next_steps"] == str(plan)


def test_plan_is_written_even_when_satisfied():
    """A satisfied run still hands over the desirable remainder."""
    with tempfile.TemporaryDirectory() as td:
        rc, outcome, _ = run_loop(Path(td), [PASS, PASS], mode="full", max_rounds=2)
        assert rc == 0, outcome
        plan = Path(td) / "rc" / "next-steps.md"
        assert plan.exists()
        text = plan.read_text(encoding="utf-8")
        assert "SATISFIED" in text
        assert "B. Desirable" in text


def test_loop_keeps_climbing_above_the_minimum_while_improving():
    """The minimum is the requirement, not the ceiling: while the score is still
    rising the loop keeps going rather than stopping at the first pass."""
    with tempfile.TemporaryDirectory() as td:
        rc, outcome, calls = run_loop(Path(td), [PASS, BETTER, BETTER2],
                                      mode="full", max_rounds=3)
        assert rc == 0, outcome
        assert len(outcome["scores"]) == 3, (
            "a satisfied-but-improving run must keep going to the cap, got "
            f"{outcome['scores']}"
        )
        assert outcome["scores"] == sorted(outcome["scores"]), outcome["scores"]


def test_loop_stops_once_gains_stall_above_the_minimum():
    """...and stops as soon as they stop, rather than grinding to the cap."""
    with tempfile.TemporaryDirectory() as td:
        rc, outcome, calls = run_loop(Path(td), [PASS, PASS, PASS],
                                      mode="full", max_rounds=6)
        assert rc == 0, outcome
        assert len(outcome["scores"]) == 2, (
            f"no gain between rounds 1-2, so stop at 2; got {outcome['scores']}"
        )
        assert "planning the remainder" in outcome["reason"]


def test_budget_stops_the_run_and_reports_it():
    """A spent budget ends the run and the reason says so."""
    with tempfile.TemporaryDirectory() as td:
        rc, outcome, _ = run_loop(Path(td), [FAIL, FAIL, FAIL, FAIL],
                                  mode="full", max_rounds=8, budget_seconds=0.0001)
        assert rc == 1, outcome
        assert len(outcome["scores"]) == 1, (
            f"an exhausted budget must stop after the first round, got "
            f"{outcome['scores']}"
        )
        assert "budget" in outcome["reason"], outcome["reason"]


def test_min_rounds_prevents_a_single_round_ending_the_run():
    with tempfile.TemporaryDirectory() as td:
        rc, outcome, _ = run_loop(Path(td), [FAIL, FAIL], mode="full",
                                  max_rounds=4, min_rounds=2)
        assert len(outcome["scores"]) >= 2, outcome["scores"]


def test_outcome_records_the_adaptive_parameters():
    with tempfile.TemporaryDirectory() as td:
        _, outcome, _ = run_loop(Path(td), [FAIL, FAIL], mode="full",
                                 max_rounds=3, min_rounds=1)
        assert outcome["met_minimum"] is False
        assert outcome["max_rounds"] == 3
        assert outcome["min_rounds"] == 1


# --- the fan-out: reviewers must be real profiles (the defect this fixes) ----
# `delegate_task` children inherit the PARENT's HERMES_HOME, so a rubric in a
# reviewer's own profile was unreachable — the council ran five generic subagents
# in dimension labels. Each now spawns under its own profile, prompt naming it.

def test_the_reviewer_is_one_generalist_profile_sampled_n_times():
    """M8.5's result, pinned: ONE profile sampled, not five specialists.

    Five per-dimension profiles used to be spawned here. The ablation measured that
    against one generalist sampled five times at equal cost and the generalist won
    (22/22 injected defects against 13/22), so the profiles were deleted. What must
    not regress is that every reviewer turn runs under a profile that really carries
    the rubrics -- a generic subagent would load none of them.
    """
    with tempfile.TemporaryDirectory() as td:
        _, _, calls = run_loop(Path(td), [FAIL], mode="advisory", max_rounds=1)
        reviewers = [s for s in calls["spawns"] if _is_reviewer(s["prompt"])]
        assert len(reviewers) == SAMPLES, reviewers
        assert {s["profile"] for s in reviewers} == {loop.GENERALIST_PROFILE}, reviewers


def test_the_reviewer_prompt_names_all_five_rubrics():
    """A reviewer that cannot name a rubric cannot load it. The profile is what
    makes the skills reachable; the prompt is what makes the agent ask for them."""
    with tempfile.TemporaryDirectory() as td:
        _, _, calls = run_loop(Path(td), [FAIL], mode="advisory", max_rounds=1)
        prompts = [s["prompt"] for s in calls["spawns"] if _is_reviewer(s["prompt"])]
        assert prompts, "the round must have convened the reviewer"
        for prompt in prompts:
            for dim in DIMS:
                assert loop.DIMENSION_SPEC[dim]["rubric"] in prompt, dim


def test_reviewer_prompts_carry_no_threshold():
    """§9 anti-gaming: the pass threshold stays out of every child's context."""
    with tempfile.TemporaryDirectory() as td:
        _, _, calls = run_loop(Path(td), [FAIL], mode="advisory",
                               max_rounds=1, threshold=91.5)
        for spawn in calls["spawns"]:
            if _is_reviewer(spawn["prompt"]):
                assert "91.5" not in spawn["prompt"], "threshold leaked to a reviewer"


def test_harness_writes_meta_json():
    """The harness owns meta.json — it knows the sha and the stacks, the LLM does not."""
    with tempfile.TemporaryDirectory() as td:
        run_loop(Path(td), [FAIL], mode="advisory", max_rounds=1)
        meta = json.loads((Path(td) / "rc" / "round-1" / "meta.json").read_text(encoding="utf-8"))
        assert meta["target_sha"] == "stub-sha"
        assert meta["round"] == 1
        assert isinstance(meta["stacks"], list)


def test_aggregation_prompt_forbids_refanning_out():
    """The orchestrator aggregates; it must not delegate or re-review."""
    with tempfile.TemporaryDirectory() as td:
        _, _, calls = run_loop(Path(td), [FAIL], mode="advisory", max_rounds=1)
        agg = [s["prompt"] for s in calls["spawns"] if _is_aggregate(s["prompt"])]
        assert len(agg) == 1, "exactly one aggregation per round"
        assert "Do NOT fan out" in agg[0]
        assert "you do not decide the verdict" in agg[0].lower()


def test_missing_reviewer_output_is_an_error_not_a_pass():
    """A reviewer that produced no file must never read as 'clean'. The gate
    returns exit 2, and the loop reports the missing dimension."""
    with tempfile.TemporaryDirectory() as td:
        stub, _ = make_stub([FAIL])
        orig = (loop.run_hermes, loop.hermes_bin, loop.run_probes, loop.git_sha)
        loop.hermes_bin = lambda: "hermes-stub"
        loop.run_probes = lambda *a, **k: []
        loop.git_sha = lambda *a, **k: "stub-sha"

        def write_nothing(binary, repo, prompt, timeout, log, profile=None):
            """Exit 0 but leave no file -- the failure the retry must not hide."""
            rc, out = stub(binary, repo, prompt, timeout, log, profile=profile)
            path_match = _GENERALIST_RE.search(prompt)
            if path_match:
                Path(path_match.group(1).strip()).unlink(missing_ok=True)
            return rc, out

        loop.run_hermes = write_nothing
        try:
            with profiles_installed():
                rc = loop.main([str(td), "--run-root", str(Path(td) / "rc"),
                                "--timeout", "5", "--mode", "advisory", "--max-rounds", "1"])
        finally:
            (loop.run_hermes, loop.hermes_bin, loop.run_probes, loop.git_sha) = orig
        assert rc == 1, "a council that produced no output must not exit 0"
        outcome = json.loads((Path(td) / "rc" / "outcome.json").read_text(encoding="utf-8"))
        assert "gate could not evaluate" in outcome["reason"], outcome["reason"]


def test_run_hermes_reports_a_blocked_spawn_instead_of_raising(tmp_path):
    """A refused CreateProcess must not abort the whole council.

    On Windows an Application Control policy refuses the spawn with WinError 4551.
    run_hermes caught only TimeoutExpired, so the OSError propagated out of the
    fan-out's ThreadPoolExecutor and killed every sibling reviewer's finished work
    -- a 37-minute run that had already produced two good reviews reported nothing
    at all. The docstring already promised "a non-zero code is reported but never
    fatal"; this pins the implementation to that promise.
    """
    import subprocess as _sp

    real_run = _sp.run

    def refuse(*a, **kw):
        raise OSError("[WinError 4551] An Application Control policy has blocked this file")

    _sp.run = refuse
    try:
        rc, out = loop.run_hermes("hermes", tmp_path, "prompt", 5, tmp_path / "l.log")
    finally:
        _sp.run = real_run

    assert rc != 0, "a blocked spawn must not look like success"
    assert "could not start" in out, out
    assert "4551" in out, "the reason must survive, not be swallowed"
def test_default_goals_covers_every_dimension():
    """The fail-open set must be complete, or a goal-less round would silently
    review only some dimensions."""
    goals = loop.default_goals(3)
    assert goals["round"] == 3
    assert [g["dimension"] for g in goals["goals"]] == DIMS
    for goal in goals["goals"]:
        assert goal["objective"], goal
        assert goal["acceptance"], goal


def test_default_goals_never_name_a_score_or_the_threshold():
    """Anti-gaming (§9): a goal that names a number invites gaming it, and the
    threshold must stay out of every child's context."""
    for goal in loop.default_goals(1)["goals"]:
        text = f"{goal['objective']} {goal['acceptance']}"
        assert not re.search(r"\b\d{2,3}\b", text), text
        assert "threshold" not in text.lower(), text


def test_read_goals_accepts_a_complete_set(tmp_path):
    p = tmp_path / "goals.json"
    p.write_text(json.dumps({"goals": [
        {"dimension": d, "objective": f"o-{d}", "acceptance": f"a-{d}"}
        for d in reversed(DIMS)
    ]}), encoding="utf-8")
    goals = loop.read_goals(p, 2)
    assert goals is not None
    # Normalised into DIMENSIONS order, so a report reads the same regardless of
    # what order the orchestrator emitted.
    assert [g["dimension"] for g in goals["goals"]] == DIMS


def test_read_goals_rejects_an_incomplete_or_malformed_set(tmp_path):
    """A partial goal set is treated as absent, never partially applied."""
    p = tmp_path / "goals.json"
    for payload in [
        "{ not json",
        "{}",
        '{"goals": "nope"}',
        json.dumps({"goals": [{"dimension": "security", "objective": "only one"}]}),
    ]:
        p.write_text(payload, encoding="utf-8")
        assert loop.read_goals(p, 1) is None, payload


def test_read_goals_missing_file_is_none(tmp_path):
    assert loop.read_goals(tmp_path / "absent.json", 1) is None


def test_goal_for_fills_a_missing_field_from_the_default():
    """A goal that names an objective but no acceptance criterion is still
    usable — the default fills the gap rather than leaving it blank."""
    goals = {"round": 1, "goals": [{"dimension": "security", "objective": "custom"}]}
    merged = loop.goal_for(goals, "security")
    assert merged["objective"] == "custom"
    assert merged["acceptance"] == loop.DEFAULT_GOALS["security"]["acceptance"]


def test_goal_for_an_absent_dimension_falls_back():
    merged = loop.goal_for({"goals": []}, "performance")
    assert merged["objective"] == loop.DEFAULT_GOALS["performance"]["objective"]


def test_probe_summary_renders_every_probe():
    probes = [
        {"tool": "statix", "ran": True, "signal": 64.9, "findings": [{"a": 1}],
         "note": "3 lints"},
        {"tool": "nix", "ran": False, "signal": None, "findings": [], "note": "absent"},
    ]
    text = loop.probe_summary(probes)
    assert "statix" in text and "64.9" in text and "3 lints" in text
    assert "NOT RUN" in text
    assert loop.probe_summary([]).strip() == "(no probes ran)"


def test_the_reviewer_prompt_carries_the_goal_and_keeps_the_rubrics_authoritative():
    prompt = loop.GENERALIST_PROMPT.format(
        rubrics=", ".join(loop.DIMENSION_SPEC[d]["rubric"] for d in loop.DIMENSIONS),
        repo="/r", scope="diff", round=1, sha="abc", stacks="nix",
        goal_objective="OBJECTIVE_SENTINEL", goal_acceptance="ACCEPTANCE_SENTINEL",
        goal_focus="path/to/file.nix:12", probe_json="[]",
        carry_block="",
        out_path="/r/generalist-1.json", profile=loop.GENERALIST_PROFILE, prefix="GEN",
    )
    assert "OBJECTIVE_SENTINEL" in prompt
    assert "ACCEPTANCE_SENTINEL" in prompt
    assert "path/to/file.nix:12" in prompt
    assert "rubrics define" in prompt, "the rubrics must stay authoritative"


def test_the_goals_prompt_forbids_naming_a_score():
    """The goal-setter must not be told how the round will be judged."""
    assert "Do NOT state a target score" in loop.GOALS_PROMPT


def test_the_goal_review_may_not_override_the_gate():
    """The gate decides; the orchestrator explains. Stated in the prompt so the
    two cannot disagree in the run report."""
    assert "AUTHORITATIVE" in loop.GOAL_REVIEW_PROMPT
    assert "do not recompute" in loop.GOAL_REVIEW_PROMPT.lower()


def test_the_loop_sets_goals_before_it_reviews_and_reviews_after():
    """One goal-setting turn per round, ahead of the reviewers, and a goal review
    at the end — in that order."""
    with tempfile.TemporaryDirectory() as td:
        rc, outcome, calls = run_loop(Path(td), [PASS], mode="advisory", max_rounds=1)
        assert rc == 0, outcome
        assert calls["goals"] == 1, "one goal-setting turn per round"
        assert calls["goal_reviews"] == 1, "one goal review per round"
        assert calls["reviewers"] == SAMPLES

        kinds = []
        for spawn in calls["spawns"]:
            p = spawn["prompt"]
            if "set this round's goals" in p:
                kinds.append("goals")
            elif "THE GOALS YOU SET FOR THIS ROUND" in p:
                kinds.append("goal_review")
            elif _is_reviewer(p):
                kinds.append("reviewer")
        assert kinds[0] == "goals", kinds
        assert kinds[-1] == "goal_review", kinds
        assert kinds.count("reviewer") == SAMPLES, kinds


def test_goal_setting_failure_does_not_abort_the_round():
    """Fail-open: a goal-setting failure is not a review failure. The round runs
    on the built-in goals and still reaches a verdict."""
    with tempfile.TemporaryDirectory() as td:
        rc, outcome, calls = run_loop(Path(td), [PASS], mode="advisory",
                                      max_rounds=1, goals_fail=True)
        assert rc == 0, outcome
        assert outcome["outcome"] == "satisfied", "the round still completed"
        assert calls["reviewers"] == SAMPLES
        assert calls["goal_reviews"] == 1


def test_the_loop_default_threshold_is_the_calibrated_one():
    """The number the loop enforces and the number the calibration recommends are
    ONE value, read from the manifest — not a literal in two files."""
    assert loop.build_parser().parse_args([]).threshold is None
    gate = loop._gate_module()
    manifest = json.loads(
        (REPO / "scripts" / "calibration.json").read_text(encoding="utf-8"))
    assert gate.calibrated_threshold() == manifest["threshold"]["recommended"]


def main() -> int:
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    passed = failed = 0
    for name, fn in tests:
        try:
            # pytest-style: hand tmp_path to tests that declare it, so the suite
            # runs under both this harness and `pytest`.
            import inspect
            if "tmp_path" in inspect.signature(fn).parameters:
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


# --- collapsed mode: bucketing a generalist's findings by dimension -----------
# The ablation (M8.5) found one generalist sampled N times better than five
# specialists at equal cost, so it is the default. The scorer still reads one file
# per dimension, and every failure here is silent: a drop just lowers a score.

def _sample(tmp: Path, name: str, doc: dict) -> Path:
    p = tmp / name
    p.write_text(json.dumps(doc), encoding="utf-8", newline="\n")
    return p


def test_merge_buckets_findings_by_their_declared_dimension():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        s = _sample(tmp, "generalist-1.json", {
            "scores": {"security": 80, "correctness": 100, "readability": 100,
                       "architecture": 100, "performance": 100},
            "findings": [
                {"dimension": "security", "severity": "high",
                 "location": {"path": "a.nix", "line_range": "1"}, "claim": "one"},
                {"dimension": "performance", "severity": "low",
                 "location": {"path": "b.nix", "line_range": "2"}, "claim": "two"}]})
        counts = loop.merge_generalist_samples([s], tmp)
        assert counts["security"] == 1, counts
        assert counts["performance"] == 1, counts
        assert counts["correctness"] == 0, counts
        sec = json.loads((tmp / "security.json").read_text())
        assert sec["score"] == 80, sec
        assert len(sec["findings"]) == 1, sec


def test_merge_dedupes_the_same_defect_across_samples():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        same = {"dimension": "security", "severity": "high",
                "location": {"path": "a.nix", "line_range": "1"}, "claim": "one defect"}
        paths = [_sample(tmp, f"generalist-{i}.json", {"findings": [same]})
                 for i in (1, 2, 3)]
        assert loop.merge_generalist_samples(paths, tmp)["security"] == 1


def test_merge_drops_a_finding_with_no_usable_dimension():
    """Guessing a dimension would invent data and corrupt the score it feeds."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        s = _sample(tmp, "generalist-1.json", {"findings": [
            {"severity": "high", "location": {"path": "a.nix", "line_range": "1"},
             "claim": "no dimension"},
            {"dimension": "nonsense", "severity": "high",
             "location": {"path": "b.nix", "line_range": "2"}, "claim": "bad dimension"},
            {"dimension": "security", "severity": "high",
             "location": {"path": "c.nix", "line_range": "3"}, "claim": "fine"}]})
        counts = loop.merge_generalist_samples([s], tmp)
        assert counts["dropped"] == 2, counts
        assert counts["security"] == 1, counts


def test_merge_averages_the_per_dimension_scores():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        paths = [_sample(tmp, f"generalist-{i}.json",
                         {"scores": {"security": v}, "findings": []})
                 for i, v in ((1, 80), (2, 90))]
        loop.merge_generalist_samples(paths, tmp)
        assert json.loads((tmp / "security.json").read_text())["score"] == 85.0


def test_merge_scores_100_when_a_dimension_reported_nothing():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        loop.merge_generalist_samples([_sample(tmp, "generalist-1.json",
                                               {"findings": []})], tmp)
        for dim in DIMS:
            assert json.loads((tmp / f"{dim}.json").read_text())["score"] == 100.0, dim


def test_merge_tolerates_a_fenced_or_prose_wrapped_sample():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        p = tmp / "generalist-1.json"
        p.write_text("Here you go:\n```json\n" + json.dumps({"findings": [
            {"dimension": "security", "severity": "low",
             "location": {"path": "a.nix", "line_range": "1"}, "claim": "x"}]})
            + "\n```\n", encoding="utf-8", newline="\n")
        assert loop.merge_generalist_samples([p], tmp)["security"] == 1


def test_merge_ignores_a_missing_sample():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        counts = loop.merge_generalist_samples([tmp / "nope.json"], tmp)
        assert counts["samples"] == 0, counts
        for dim in DIMS:
            assert counts[dim] == 0, counts
        # And it must NOT leave empty dimension files: five empty files score a
        # clean 100 and PASS, turning total reviewer failure into reported success.
        for dim in DIMS:
            assert not (tmp / f"{dim}.json").exists(), dim


def test_the_generalist_prompt_carries_every_rubric_and_an_output_path():
    prompt = loop.GENERALIST_PROMPT.format(
        rubrics=", ".join(loop.DIMENSION_SPEC[d]["rubric"] for d in loop.DIMENSIONS),
        repo="r", scope="whole-repo", round=1, sha="abc", stacks="nix",
        goal_objective="o", goal_acceptance="a", goal_focus="f", probe_json="[]",
        carry_block="",
        out_path="/tmp/x.json", profile=loop.GENERALIST_PROFILE, prefix="GEN")
    for dim in loop.DIMENSIONS:
        assert loop.DIMENSION_SPEC[dim]["rubric"] in prompt, dim
    assert "/tmp/x.json" in prompt
    # Every finding must declare a dimension, or the merge silently drops it.
    assert "MUST name the dimension" in prompt


# --- baseline-relative carry ------------------------------------------------

def test_the_carry_block_is_absent_without_a_baseline():
    """A whole-repo review must not be told about a baseline it does not have."""
    assert loop.carry_block(None) == ""
    assert loop.carry_block({}) == ""


def test_the_carry_block_names_the_changed_files():
    """The reviewer was never given a file list before -- `--scope` only ever
    interpolated the literal word, so it had to guess the changed set."""
    ctx = {"baseline_sha": "abc123def456", "changed": ["a.nix", "b/c.nix"],
           "carried": []}
    block = loop.carry_block(ctx)
    assert "a.nix" in block and "b/c.nix" in block
    assert "abc123def456" in block


def test_the_carry_block_lists_carried_findings_and_forbids_re_reporting():
    ctx = {"baseline_sha": "abc", "changed": ["a.nix"],
           "carried": [{"location": {"path": "z.nix", "line_range": "3-4"},
                        "claim": "CARRIED_CLAIM_SENTINEL", "_dimension": "security"}]}
    block = loop.carry_block(ctx)
    assert "CARRIED_CLAIM_SENTINEL" in block, block
    assert "z.nix" in block
    assert "Do NOT report" in block


def test_the_carry_block_truncates_a_large_change():
    """A 5000-file change must not blow the prompt budget."""
    ctx = {"baseline_sha": "abc", "changed": [f"f{i}.nix" for i in range(100)],
           "carried": []}
    block = loop.carry_block(ctx)
    assert "and 40 more" in block, block


def test_apply_carry_merges_findings_and_carries_the_llm_score():
    """The wiring that makes an incremental score comparable to its baseline.

    Two things must happen before the gate reads the files:

    - the carried findings land in the round, so `carried + new` covers the whole
      repository and the density denominator still describes the same population;
    - the reviewer's self-score -- taken over the changed files alone -- is
      replaced by the baseline's, because a reviewer that saw six files cannot
      honestly score a fifty-file repo.

    A dimension the baseline scored nothing for keeps the reviewer's own number,
    which is the honest fallback rather than a fabricated carry.
    """
    with tempfile.TemporaryDirectory() as td:
        round_dir = Path(td)
        for dim in loop.DIMENSIONS:
            (round_dir / f"{dim}.json").write_text(
                json.dumps({"findings": [], "score": 11.0}), encoding="utf-8")

        ctx = {
            "baseline_sha": "abc123", "changed": ["new.nix"],
            "carried": [{"location": {"path": "old.nix", "line_range": "5"},
                         "claim": "a carried claim", "severity": "low",
                         "id": "C-1", "_dimension": "security"}],
            "dropped": [], "scores": {"security": 77.5},
        }
        added = loop.apply_carry(round_dir, ctx)
        assert added == {"security": 1}, added

        review = json.loads((round_dir / "security.json").read_text(encoding="utf-8"))
        assert len(review["findings"]) == 1, review["findings"]
        assert review["score"] == 77.5, review["score"]
        assert review["llm_carried_from_baseline"] is True
        # The internal tag must not leak into the scored finding.
        assert not any(k.startswith("_") for k in review["findings"][0])

        other = json.loads((round_dir / "readability.json").read_text(encoding="utf-8"))
        assert other["score"] == 11.0, other["score"]


def test_apply_carry_skips_a_missing_dimension():
    """A dimension the reviewer never wrote stays missing, so the gate errors
    rather than scoring a round that reviewed nothing."""
    with tempfile.TemporaryDirectory() as td:
        round_dir = Path(td)
        (round_dir / "security.json").write_text(
            json.dumps({"findings": [], "score": 1.0}), encoding="utf-8")
        ctx = {"baseline_sha": "abc", "changed": [], "dropped": [],
               "scores": {"readability": 99.0},
               "carried": [{"location": {"path": "x.nix", "line_range": "1"},
                            "claim": "c", "severity": "low", "_dimension": "readability"}]}
        added = loop.apply_carry(round_dir, ctx)
        assert added == {}, added
        assert not (round_dir / "readability.json").exists()


def test_carry_is_off_by_default():
    """Changing the default would silently narrow every existing invocation."""
    args = loop.build_parser().parse_args(["repo"])
    assert args.baseline == "off", args


def test_the_reviewer_is_one_generalist_sampled_five_times_by_default():
    """M8.5 measured one generalist sampled five times beating five specialists at
    equal cost (22/22 injected defects against 13/22), so this is the only reviewer
    mode and five is the default sample count."""
    args = loop.build_parser().parse_args(["repo"])
    _, samples, _, _ = loop.resolve_review_defaults(
        args.mode, args.samples, args.max_rounds, args.threshold, {})
    assert samples == 5, args
    # The specialists mode and its spawner were deleted, not merely defaulted away.
    assert not hasattr(args, "reviewer_mode"), args
    assert not hasattr(loop, "run_reviewers"), "the fan-out spawner still exists"



# ---------------------------------------------------------------------------
# tools_run -> beta. The generalist prompt never asked for it and
# merge_generalist_samples hardcoded [], so beta was 0 everywhere and the score
# collapsed to the LLM's judgement, silently — and since every other merge test
# supplies its own fixture, both halves could drop it and still pass. Real path.
# ---------------------------------------------------------------------------

_spec = importlib.util.spec_from_file_location(
    "score_reviews", REPO / "scripts" / "score_reviews.py")
score_reviews = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(score_reviews)


def test_merge_unions_tools_run_across_samples():
    """A tool counts as run if ANY sample ran it.

    The samples are independent attempts at the same round, so a tool one of
    them exercised was exercised. Keeping only the intersection (or nothing, as
    the bug did) discards real evidence.
    """
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        paths = [
            _sample(tmp, "generalist-1.json", {
                "findings": [],
                "tools_run": [{"cmd": "statix check .", "ran": True, "parsed": True}]}),
            _sample(tmp, "generalist-2.json", {
                "findings": [],
                "tools_run": [
                    {"cmd": "statix check .", "ran": True, "parsed": True},
                    {"cmd": "secret-grep", "ran": True, "parsed": False}]}),
        ]
        loop.merge_generalist_samples(paths, tmp)
        doc = json.loads((tmp / "security.json").read_text())
        by_cmd = {t["cmd"]: t for t in doc["tools_run"]}
        assert set(by_cmd) == {"statix check .", "secret-grep"}, doc["tools_run"]
        assert by_cmd["statix check ."]["ran"] is True
        assert by_cmd["secret-grep"]["ran"] is True
        assert by_cmd["secret-grep"]["parsed"] is False, "a failed parse must survive"
        assert doc["beta_note"], "the run must say how beta was derived"


def test_merge_marks_a_tool_parsed_if_any_sample_parsed_it():
    """One sample reading the output is enough; a failed parse elsewhere is not
    evidence that the tool cannot be read."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        paths = [
            _sample(tmp, "generalist-1.json", {"findings": [], "tools_run": [
                {"cmd": "flake-check", "ran": True, "parsed": False}]}),
            _sample(tmp, "generalist-2.json", {"findings": [], "tools_run": [
                {"cmd": "flake-check", "ran": True, "parsed": True}]}),
        ]
        loop.merge_generalist_samples(paths, tmp)
        doc = json.loads((tmp / "security.json").read_text())
        assert doc["tools_run"] == [
            {"cmd": "flake-check", "ran": True, "parsed": True}], doc["tools_run"]


def test_merge_yields_a_nonzero_beta_for_a_nix_repo():
    """merge -> deterministic_score, the path the gate actually walks.

    beta == 1 means the score IS the deterministic term, so the half the bug made
    inert is what decides the number.
    """
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        s = _sample(tmp, "generalist-1.json", {
            "scores": {"security": 80}, "findings": [],
            "tools_run": [
                {"cmd": "statix check .", "ran": True, "parsed": True},
                {"cmd": "gitleaks detect", "ran": True, "parsed": True},
                {"cmd": "secret-grep", "ran": True, "parsed": True}]})
        loop.merge_generalist_samples([s], tmp)
        review = json.loads((tmp / "security.json").read_text())
        det, beta, missing = score_reviews.deterministic_score(
            review, "security", stacks=["nix"])
        assert beta == 1.0, (beta, review["tools_run"], missing)
        assert isinstance(det, float), det


def test_an_empty_tools_run_makes_beta_zero():
    """The failure mode, pinned as a test so it cannot come back unnoticed.

    beta == 0 makes det inert by construction, which is CORRECT for a reviewer
    that ran nothing -- the scorer is honest. The bug was that the loop produced
    an empty tools_run for a reviewer that had run things, and nothing checked.
    """
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        s = _sample(tmp, "generalist-1.json", {"scores": {"security": 80}, "findings": []})
        loop.merge_generalist_samples([s], tmp)
        review = json.loads((tmp / "security.json").read_text())
        _det, beta, missing = score_reviews.deterministic_score(
            review, "security", stacks=["nix"])
        assert beta == 0.0, (beta, review["tools_run"])
        assert missing, "the tools it did not run must be reported, not hidden"


def test_the_generalist_prompt_asks_for_tools_run():
    """The prompt is the other half of the contract. Assert it directly: the
    merge can carry tools_run through, but if the prompt never asks for them the
    reviewer never sends them, and beta is 0 again."""
    assert '"tools_run"' in loop.GENERALIST_PROMPT, "the shape must request it"
    assert "parsed" in loop.GENERALIST_PROMPT, "the flags must be specified"



def test_merge_seeds_tools_run_from_the_harness_probes():
    """The harness's probes ARE the deterministic tools running.

    STACK_TOOLS states that builtin names "are satisfied by the framework's own
    probes.py". Counting only what the reviewer reports leaves beta at 0 for
    every dimension whose expected tools are builtin -- the probe ran, the
    reviewer was handed its result, and the dimension scored as if nothing had
    been exercised. architecture expects exactly two builtin probes, so it is the
    clearest case: with the seed it is 1.0, without it 0.0.
    """
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        s = _sample(tmp, "generalist-1.json",
                    {"scores": {"architecture": 90}, "findings": []})
        probes = [
            {"tool": "dep-graph", "ran": True, "parsed": True, "signal": 100.0},
            {"tool": "declared-rules", "ran": True, "parsed": True, "signal": 100.0},
        ]
        loop.merge_generalist_samples([s], tmp, probes)
        review = json.loads((tmp / "architecture.json").read_text())
        _det, beta, missing = score_reviews.deterministic_score(
            review, "architecture", stacks=["nix"])
        assert beta == 1.0, (beta, review["tools_run"], missing)

        # And the same round WITHOUT the seed is the bug, pinned beside it.
        tmp2 = Path(td) / "noseed"
        tmp2.mkdir()
        s2 = _sample(tmp2, "generalist-1.json",
                     {"scores": {"architecture": 90}, "findings": []})
        loop.merge_generalist_samples([s2], tmp2)
        review2 = json.loads((tmp2 / "architecture.json").read_text())
        _det2, beta2, _missing2 = score_reviews.deterministic_score(
            review2, "architecture", stacks=["nix"])
        assert beta2 == 0.0, (beta2, review2["tools_run"])


def test_merge_still_works_without_probe_results():
    """The probe seed is optional, so the two-argument call stays valid."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        s = _sample(tmp, "generalist-1.json", {"findings": []})
        assert loop.merge_generalist_samples([s], tmp)["samples"] == 1



# --- asking for the project (the no-hardcoded-paths rule) --------------------
# find_project_root (session route) is tested above; these cover the fallback: a
# terminal gets asked, anything else gets the refusal.

class _FakeStdin:
    def __init__(self, tty: bool):
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


def test_ask_for_project_is_silent_without_a_tty():
    """A scheduled job or an agent turn has nobody to answer, so it must not block."""
    real = loop.sys.stdin
    loop.sys.stdin = _FakeStdin(False)
    try:
        assert loop._ask_for_project(Path("/tmp")) is None
    finally:
        loop.sys.stdin = real


def test_ask_for_project_returns_what_the_user_typed():
    import builtins

    real_stdin, real_input = loop.sys.stdin, builtins.input
    loop.sys.stdin = _FakeStdin(True)
    builtins.input = lambda prompt="": "/tmp"
    try:
        assert loop._ask_for_project(Path("/tmp")) == Path("/tmp").resolve()
    finally:
        loop.sys.stdin, builtins.input = real_stdin, real_input


def test_ask_for_project_cancels_on_a_blank_answer():
    import builtins

    real_stdin, real_input = loop.sys.stdin, builtins.input
    loop.sys.stdin = _FakeStdin(True)
    builtins.input = lambda prompt="": "   "
    try:
        assert loop._ask_for_project(Path("/tmp")) is None
    finally:
        loop.sys.stdin, builtins.input = real_stdin, real_input


def test_ask_for_project_cancels_on_interrupt():
    """Ctrl-C at the prompt is a cancel, not a traceback."""
    import builtins

    def boom(prompt=""):
        raise KeyboardInterrupt

    real_stdin, real_input = loop.sys.stdin, builtins.input
    loop.sys.stdin = _FakeStdin(True)
    builtins.input = boom
    try:
        assert loop._ask_for_project(Path("/tmp")) is None
    finally:
        loop.sys.stdin, builtins.input = real_stdin, real_input


def test_unanchored_session_without_a_tty_still_refuses():
    """The refusal is what protects a non-interactive caller from the wrong tree."""
    import tempfile

    real = loop.sys.stdin
    cwd = Path.cwd()
    with tempfile.TemporaryDirectory() as td:
        # No git root and no marker above cannot be built reliably, so assert the
        # branch: with no TTY the prompt returns None and resolve_target gains nothing.
        loop.sys.stdin = _FakeStdin(False)
        try:
            assert loop._ask_for_project(Path(td)) is None
        finally:
            loop.sys.stdin = real
    assert Path.cwd() == cwd, "the test must not change the working directory"



# --- the profile preflight (the newcomer's first failure) --------------------
# With no profiles every sample was rc=1 NO FILE and the gate reported "could not
# evaluate the run" — the SYMPTOM. These cover the check that names the cause.

def test_hermes_home_honours_the_env_var():
    import os
    import tempfile

    real = os.environ.get("HERMES_HOME")
    with tempfile.TemporaryDirectory() as td:
        os.environ["HERMES_HOME"] = td
        try:
            # Compared RAW, like the siblings below: hermes_home() returns the env
            # value expanduser'd, not resolved. Resolving passes on Linux only
            # because /tmp is real; on macOS TMPDIR is under /var -> /private/var,
            # so Path(td).resolve() is a different string for the same directory.
            assert loop.hermes_home() == Path(td)
        finally:
            if real is None:
                os.environ.pop("HERMES_HOME", None)
            else:
                os.environ["HERMES_HOME"] = real


def test_missing_profiles_reports_both_on_an_empty_home():
    import os
    import tempfile

    real = os.environ.get("HERMES_HOME")
    with tempfile.TemporaryDirectory() as td:
        os.environ["HERMES_HOME"] = td
        try:
            assert loop.missing_profiles() == [
                loop.ORCHESTRATOR_PROFILE, loop.GENERALIST_PROFILE]
        finally:
            if real is None:
                os.environ.pop("HERMES_HOME", None)
            else:
                os.environ["HERMES_HOME"] = real


def test_missing_profiles_is_empty_when_both_are_installed():
    import os
    import tempfile

    real = os.environ.get("HERMES_HOME")
    with tempfile.TemporaryDirectory() as td:
        for name in (loop.ORCHESTRATOR_PROFILE, loop.GENERALIST_PROFILE):
            (Path(td) / "profiles" / name).mkdir(parents=True)
        os.environ["HERMES_HOME"] = td
        try:
            assert loop.missing_profiles() == []
        finally:
            if real is None:
                os.environ.pop("HERMES_HOME", None)
            else:
                os.environ["HERMES_HOME"] = real


def test_missing_profiles_names_only_the_one_absent():
    """A half-installed machine is the common case -- one verb was run, not two."""
    import os
    import tempfile

    real = os.environ.get("HERMES_HOME")
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / "profiles" / loop.GENERALIST_PROFILE).mkdir(parents=True)
        os.environ["HERMES_HOME"] = td
        try:
            assert loop.missing_profiles() == [loop.ORCHESTRATOR_PROFILE]
        finally:
            if real is None:
                os.environ.pop("HERMES_HOME", None)
            else:
                os.environ["HERMES_HOME"] = real


def test_preflight_is_silent_when_configured():
    import os
    import tempfile

    real = os.environ.get("HERMES_HOME")
    with tempfile.TemporaryDirectory() as td:
        for name in (loop.ORCHESTRATOR_PROFILE, loop.GENERALIST_PROFILE):
            (Path(td) / "profiles" / name).mkdir(parents=True)
        os.environ["HERMES_HOME"] = td
        try:
            assert loop.profile_preflight() is None
        finally:
            if real is None:
                os.environ.pop("HERMES_HOME", None)
            else:
                os.environ["HERMES_HOME"] = real


def test_preflight_names_the_profiles_and_the_fix():
    """The message has to be actionable: what is missing, and the command."""
    import os
    import tempfile

    real = os.environ.get("HERMES_HOME")
    with tempfile.TemporaryDirectory() as td:
        os.environ["HERMES_HOME"] = td
        try:
            msg = loop.profile_preflight()
        finally:
            if real is None:
                os.environ.pop("HERMES_HOME", None)
            else:
                os.environ["HERMES_HOME"] = real
    assert msg, "a bare home must produce a refusal"
    for expected in (loop.ORCHESTRATOR_PROFILE, loop.GENERALIST_PROFILE,
                     "setup bots", "credentials"):
        assert expected in msg, f"{expected!r} missing from:\n{msg}"


def test_main_refuses_before_running_when_profiles_are_missing():
    """The integration: exit 2, and nothing written."""
    import os
    import tempfile

    real = os.environ.get("HERMES_HOME")
    real_bin = loop.hermes_bin
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td) / "repo"
        repo.mkdir()
        (repo / "pyproject.toml").write_text("[project]\n")
        home = Path(td) / "home"
        home.mkdir()
        os.environ["HERMES_HOME"] = str(home)
        # Pretend hermes is installed, so the profile check is what refuses.
        loop.hermes_bin = lambda: "/usr/bin/hermes"
        try:
            rc = loop.main([str(repo), "--dry-run"])
        finally:
            loop.hermes_bin = real_bin
            if real is None:
                os.environ.pop("HERMES_HOME", None)
            else:
                os.environ["HERMES_HOME"] = real
        assert rc == 2, rc
        # A refusal must not leave a run directory behind.
        assert not (repo / ".review-council").exists(), "wrote a run dir on refusal"



def test_hermes_home_falls_back_to_asking_hermes():
    """The last resort: a home that is neither in the environment nor a default.

    This is the branch the cheap-path reordering could have broken. The defaults
    are stubbed away so the only answer left is the one `hermes` gives.
    """
    import os
    import tempfile

    real_home = Path.home
    real_bin = loop.hermes_bin
    real_sub = loop.subprocess
    real_env = os.environ.pop("HERMES_HOME", None)
    real_local = os.environ.pop("LOCALAPPDATA", None)

    with tempfile.TemporaryDirectory() as td:
        # The home `hermes` reports must EXIST: hermes_home() validates with
        # is_dir(), so a stub at a nonexistent path is rejected and the branch untested.
        custom = Path(td) / "custom-home"
        custom.mkdir()
        stdout = f"Path: {custom}\n"

        class _Result:
            pass

        _Result.stdout = stdout

        class _Sub:
            @staticmethod
            def run(*a, **k):
                return _Result()

            TimeoutExpired = Exception

        # No ~/.hermes and no LOCALAPPDATA/hermes.
        Path.home = staticmethod(lambda: Path(td) / "nohome")
        loop.hermes_bin = lambda: "/usr/bin/hermes"
        loop.subprocess = _Sub
        try:
            assert loop.hermes_home() == custom
        finally:
            Path.home = real_home
            loop.hermes_bin = real_bin
            loop.subprocess = real_sub
            if real_env is not None:
                os.environ["HERMES_HOME"] = real_env
            if real_local is not None:
                os.environ["LOCALAPPDATA"] = real_local


def test_hermes_home_prefers_a_default_over_spawning():
    """The cheap path must win, or the reorder bought nothing.

    If this fails, the subprocess is being spawned even when a standard location
    exists -- which is the ~550 ms the reorder removed.
    """
    import os
    import tempfile

    real_home = Path.home
    real_bin = loop.hermes_bin
    real_env = os.environ.pop("HERMES_HOME", None)

    spawned = []

    def _no_spawn():
        spawned.append(1)
        return "/usr/bin/hermes"

    with tempfile.TemporaryDirectory() as td:
        (Path(td) / ".hermes").mkdir()
        Path.home = staticmethod(lambda: Path(td))
        loop.hermes_bin = _no_spawn
        try:
            assert loop.hermes_home() == (Path(td) / ".hermes")
            assert not spawned, "spawned hermes even though a default home exists"
        finally:
            Path.home = real_home
            loop.hermes_bin = real_bin
            if real_env is not None:
                os.environ["HERMES_HOME"] = real_env

def test_concurrent_samples_do_not_share_a_prompt_file(tmp_path: Path):
    """Regression: every concurrent sample wrote and read ONE prompt file.

    The prompt file was derived from the log path, and the five samples run in one
    ThreadPoolExecutor that shares that log. So whichever sample wrote last decided
    the `out_path` embedded in every child's prompt, all five wrote the same
    `generalist-N.json`, and the round reviewed a single sample while reporting
    five. A real run left one sample file and 41 log mentions of `generalist-4.json`
    against zero for 1, 2, 3 and 5.

    Asserted at the spawn boundary, because that is where it went wrong and nothing
    afterwards can detect it: the round still reports the sample count it intended.
    """
    import subprocess
    import threading

    log = tmp_path / "council.log"
    barrier = threading.Barrier(5, timeout=15)
    mine: dict = {}
    seen: dict = {}

    def fake_run(cmd, **kwargs):
        path = Path(cmd[cmd.index("--query-file") + 1])
        # Hold every caller here so all five have written before any reads — the
        # interleaving the real parallel spawn produces.
        barrier.wait()
        seen[threading.get_ident()] = (path, path.read_text(encoding="utf-8"))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    real_run = loop.subprocess.run
    loop.subprocess.run = fake_run
    try:
        def sample(i: int) -> None:
            mine[threading.get_ident()] = f"PROMPT-{i}"
            loop.run_hermes("hermes", tmp_path, f"PROMPT-{i}", 5, log,
                            profile="council-generalist")

        threads = [threading.Thread(target=sample, args=(i,)) for i in range(1, 6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        loop.subprocess.run = real_run

    paths = sorted(str(p) for p, _ in seen.values())
    assert len(set(paths)) == 5, f"the samples shared a prompt file: {paths}"
    for tid, (_path, text) in seen.items():
        assert text == mine[tid], (
            f"a sample was handed another sample's prompt: {text!r} != {mine[tid]!r}")


if __name__ == "__main__":
    sys.exit(main())
