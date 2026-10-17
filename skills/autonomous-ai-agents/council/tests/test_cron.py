"""Tests for cron.py — the scheduled unattended review (M7).

Run standalone (no pytest needed):
    python tests/test_cron.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("cron", REPO / "scripts" / "cron.py")
cron = importlib.util.module_from_spec(_spec)
sys.modules["cron"] = cron
_spec.loader.exec_module(cron)


# --- the plan is data, and it is the command a person would type ------------------

def test_the_plan_is_the_hermes_cron_create_call():
    plan = cron.build(REPO)
    argv = plan["argv"]
    assert argv[:4] == ["hermes", "cron", "create", "--name"], argv
    # schedule and prompt are the two positionals, in that order
    assert plan["schedule"] in argv
    assert argv.index(plan["schedule"]) < argv.index(plan["prompt"] if "prompt" in plan
                                                     else argv[-1])


def test_the_repo_is_the_workdir():
    """The job must run in the repository, not wherever the scheduler happens to be."""
    plan = cron.build(REPO)
    assert "--workdir" in plan["argv"]
    assert plan["argv"][plan["argv"].index("--workdir") + 1] == str(REPO)


def test_the_default_schedule_is_daily():
    assert cron.build(REPO)["schedule"] == "0 9 * * *"


def test_a_custom_schedule_survives_quoting():
    """`0 9 * * 1` has spaces, so the printed command must quote it."""
    plan = cron.build(REPO, schedule="0 9 * * 1")
    assert "'0 9 * * 1'" in plan["command"], plan["command"]


def test_samples_are_passed_only_when_asked_for():
    assert "--samples" not in cron.build(REPO)["command"]
    assert "--samples 5" in cron.build(REPO, samples=5)["command"]


# --- the prompt: run it, do not re-review it -------------------------------------

def test_the_prompt_tells_the_agent_to_run_the_council():
    prompt = cron.prompt_for(REPO, None)
    assert f"council review {REPO}" in prompt, prompt


def test_the_prompt_forbids_a_second_unaudited_reviewer():
    """A cron agent that reviews the code itself is a reviewer outside the framework,
    and its score would not be the score the gate enforces."""
    prompt = cron.prompt_for(REPO, None)
    assert "Do NOT review the code yourself" in prompt, prompt
    assert "verbatim" in prompt, prompt


def test_the_prompt_forbids_inventing_a_missing_run():
    prompt = cron.prompt_for(REPO, None)
    assert "invented" in prompt or "invented one is not" in prompt, prompt


# --- print, do not act -----------------------------------------------------------

def test_rendering_names_the_install_path_and_the_opt_in():
    text = "\n".join(cron.render(cron.build(REPO)))
    assert "--install" in text, text
    assert "hermes cron list" in text, text


def test_rendering_states_that_a_reviewer_cannot_schedule():
    """The M7 note: cron.allow_agent_scheduling is false, so an agent cannot create
    its own follow-up reviews."""
    text = "\n".join(cron.render(cron.build(REPO)))
    assert "cron.allow_agent_scheduling" in text, text


def test_json_is_the_same_plan():
    plan = cron.build(REPO, schedule="30m")
    assert json.loads(json.dumps(plan))["schedule"] == "30m"


# --- argument handling -----------------------------------------------------------

def test_a_missing_directory_is_refused():
    assert cron.main(["/nonexistent/repo/for/cron"]) == 2


def test_zero_samples_is_refused():
    assert cron.main([str(REPO), "--samples", "0"]) == 2


def test_printing_does_not_install():
    """The default must be a read: printing a schedule must not create one."""
    assert cron.main([str(REPO), "--json"]) == 0


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
