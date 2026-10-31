"""Tests for swarm.py — the durable council (M7).

Nothing here creates a card or calls a model. What is pinned is the SHAPE of the
graph and, above all, the verifier's body: the verifier must be told to run the
deterministic gate rather than to form an opinion. A shape bug here produces a swarm
that runs, reports success, and scores the code with a model — which is the failure
the beta defect already taught us to fear.

Run standalone (no pytest needed):
    python tests/test_swarm.py
"""
from __future__ import annotations

import importlib.util
import shlex
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("swarm", REPO / "scripts" / "swarm.py")
swarm = importlib.util.module_from_spec(spec)
# Registered BEFORE exec_module because swarm.py uses @dataclass, and dataclasses
# resolves `cls.__module__` through sys.modules — loading by path without this raises
# "AttributeError: 'NoneType' object has no attribute '__dict__'" at the decorator.
# Harmless in production (the dispatcher runs it as __main__).
sys.modules["swarm"] = swarm
spec.loader.exec_module(swarm)


def _plan(tmp: Path, samples: int = 5, round_no: int = 1):
    return swarm.build_plan(tmp, samples=samples, round_no=round_no)


def _by_key(cards) -> dict:
    return {c.key: c for c in cards}


# --- the graph --------------------------------------------------------------

def test_the_graph_has_one_root_n_workers_a_verifier_and_a_synthesizer(tmp_path: Path):
    cards = _plan(tmp_path, samples=3)
    assert [c.key for c in cards] == ["root", "worker1", "worker2", "worker3",
                                      "verifier", "synthesizer"]


def test_the_root_has_no_parents_and_everything_else_does(tmp_path: Path):
    cards = _by_key(_plan(tmp_path))
    assert cards["root"].parents == []
    for key, card in cards.items():
        if key != "root":
            assert card.parents, f"{key} has no parent — it could start too early"


def test_workers_depend_on_the_root_so_goals_land_first(tmp_path: Path):
    """The root sets the round's goals; a worker that starts before it reviews
    against the built-in goals instead of the round's."""
    cards = _by_key(_plan(tmp_path, samples=4))
    for i in range(1, 5):
        assert cards[f"worker{i}"].parents == ["root"], cards[f"worker{i}"].parents


def test_the_verifier_depends_on_every_worker(tmp_path: Path):
    """Gating before the samples land would score a partial round. A partial council
    is an error in the gate, not a pass, but it must not be *attempted* either."""
    cards = _by_key(_plan(tmp_path, samples=3))
    assert cards["verifier"].parents == ["worker1", "worker2", "worker3"]


def test_the_synthesizer_depends_on_the_verifier(tmp_path: Path):
    cards = _by_key(_plan(tmp_path))
    assert cards["synthesizer"].parents == ["verifier"]


def test_every_worker_is_the_one_generalist_profile(tmp_path: Path):
    """M8.5 collapsed the roster. A second reviewer profile reappearing here would
    re-open a question that was measured and answered."""
    cards = _plan(tmp_path, samples=3)
    workers = [c for c in cards if c.key.startswith("worker")]
    assert len(workers) == 3
    assert {c.assignee for c in workers} == {swarm.GENERALIST}
    assert swarm.GENERALIST not in {swarm.ORCHESTRATOR}


def test_the_orchestrator_owns_the_root_the_verifier_and_the_synthesizer(tmp_path: Path):
    cards = _by_key(_plan(tmp_path))
    assert cards["root"].assignee == swarm.ORCHESTRATOR
    assert cards["verifier"].assignee == swarm.ORCHESTRATOR
    assert cards["synthesizer"].assignee == swarm.ORCHESTRATOR


def test_one_worker_card_per_sample(tmp_path: Path):
    for n in (1, 2, 5):
        workers = [c for c in _plan(tmp_path, samples=n) if c.key.startswith("worker")]
        assert len(workers) == n


# --- the verifier's body: the load-bearing string ---------------------------

def test_the_verifier_is_told_to_run_the_gate():
    """The single most important string in this file.

    A verifier asked to "verify the score" will produce a plausible number; the gate
    produces the actual one. If this instruction ever loses that distinction, the
    swarm silently becomes a model grading itself.
    """
    body = _by_key(_plan(Path("/tmp/x")))["verifier"].body
    assert "gate" in body, body
    assert "Do NOT score the code yourself" in body, body
    assert "not the score the framework enforces" in body, body


def test_the_verifier_merges_before_it_gates(tmp_path: Path):
    """The samples are written by separate cards, so nothing has bucketed them into
    the per-dimension files the gate reads. A verifier that gates a swarm round
    without merging first gets exit 2 and "no reviewer output found" — observed on a
    real run, which is why this is pinned."""
    body = _by_key(_plan(tmp_path))["verifier"].body
    assert "merge" in body, body
    assert body.index("merge") < body.index("gate"), (
        "merge must come before gate", body)


def test_the_verifier_body_names_the_run_directory_it_must_gate(tmp_path: Path):
    body = _by_key(_plan(tmp_path, round_no=2))["verifier"].body
    assert "round-2" in body, body


def test_the_synthesizer_takes_its_numbers_from_the_gate(tmp_path: Path):
    body = _by_key(_plan(tmp_path))["synthesizer"].body
    assert "gate's output" in body, body
    assert "not from your own reading" in body, body


# --- no card restates the review prompt ------------------------------------

def test_no_card_body_restates_the_reviewer_prompt(tmp_path: Path):
    """The prompt lives in council_loop.py. A card restating it would be a second
    definition of what a review is, free to drift from the first — the mistake this
    repository has already paid for twice.

    Matched on markers distinctive to GENERALIST_PROMPT, not on vocabulary the cards
    legitimately share with it: the root card says "one entry per dimension" when
    describing the goals shape, and a test banning the word "dimension" would fail
    on a card that is doing the right thing.
    """
    joined = " ".join(c.body for c in _plan(tmp_path))
    for fragment in ("Load these five skills", "falsifiable_check",
                     "Write ONE JSON file", "REPORT WHAT YOU RAN"):
        assert fragment not in joined, (fragment, joined[:400])


def test_a_worker_card_delegates_to_the_sample_verb(tmp_path: Path):
    body = _by_key(_plan(tmp_path, samples=3))["worker2"].body
    assert "sample" in body, body
    assert "--index 2" in body, body
    assert "generalist-2.json" in body, body


# --- the invocation is resolved, not hardcoded ------------------------------

def test_the_invocation_is_resolved_from_this_scripts_own_location():
    """`council` is NOT on the gateway's PATH, so a card saying `council sample`
    would fail on its first line. The invocation must therefore name a concrete way
    to reach the framework, derived from where this script actually is.

    Asserted by PARSING it the way the shell that consumes it will, not by a suffix.
    A suffix check was brittle and wrong: on Windows the paths contain backslashes,
    so shlex.quote wraps them in quotes and the string ends with a quote rather than
    `--` or `.py`. The invocation was correct; the test was not.
    """
    invocation = swarm.council_invocation()
    assert invocation, invocation
    root = str(swarm.FRAMEWORK)
    assert root in invocation or "council_loop.py" in invocation, invocation

    parts = shlex.split(invocation)
    assert len(parts) >= 2, (invocation, parts)
    assert all(p.strip() for p in parts), (invocation, parts)
    # Either `nix run <root>#council --` or `<interpreter> <council_loop.py>`.
    assert parts[-1] == "--" or parts[-1].endswith(".py"), (invocation, parts)


def test_the_invocation_survives_a_shell_round_trip():
    """A path with a space must not split into two arguments.

    The previous form of this test was conditional on the framework path containing
    a space, so on a path without one it asserted nothing at all. This asserts the
    property unconditionally: re-quoting every token and re-parsing must reproduce
    the same tokens, which is what "the quoting mangled nothing" means. shlex is the
    same tokenisation the consuming shell performs.
    """
    invocation = swarm.council_invocation()
    parts = shlex.split(invocation)
    reparsed = shlex.split(" ".join(shlex.quote(p) for p in parts))
    assert reparsed == parts, (invocation, parts, reparsed)


# --- identifiers travel through shells and SQLite ---------------------------

def test_slugify_collapses_anything_that_would_need_quoting():
    assert swarm.slugify("Review Council") == "review-council"
    assert swarm.slugify("a/b\\c d_e") == "a-b-c-d-e"
    assert swarm.slugify("--weird--") == "weird"
    # Never empty: an empty tenant is a board-wide write.
    assert swarm.slugify("///") == "repo"
    assert swarm.slugify("") == "repo"


def test_no_card_title_contains_a_shell_metacharacter(tmp_path: Path):
    for card in _plan(tmp_path):
        for bad in (";", "|", "&", "$(", "`", ">", "<"):
            assert bad not in card.title, (bad, card.title)


# --- the CLI ----------------------------------------------------------------

def test_dry_run_prints_the_plan_and_creates_nothing(tmp_path: Path):
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = swarm.main([str(tmp_path), "--dry-run", "--samples", "2"])
    out = buf.getvalue()
    assert rc == 0, rc
    for key in ("root", "worker1", "worker2", "verifier", "synthesizer"):
        assert key in out, (key, out)
    assert "hermes kanban create" in out, out
    # --dry-run must not have created the run root or any body file.
    assert not (tmp_path / ".review-council").exists()


def test_a_missing_repo_is_a_clean_error_not_a_traceback(tmp_path: Path):
    import contextlib
    import io
    buf, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
        rc = swarm.main([str(tmp_path / "nope"), "--dry-run"])
    assert rc == 2, rc
    assert "not a directory" in err.getvalue(), err.getvalue()


def test_samples_must_be_at_least_one(tmp_path: Path):
    import contextlib
    import io
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        rc = swarm.main([str(tmp_path), "--samples", "0", "--dry-run"])
    assert rc == 2, rc
    assert "--samples" in err.getvalue(), err.getvalue()


# --- standalone runner ------------------------------------------------------

def main() -> int:
    import inspect
    import tempfile
    failures = 0
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    for name, fn in tests:
        try:
            if "tmp_path" in inspect.signature(fn).parameters:
                with tempfile.TemporaryDirectory() as td:
                    fn(Path(td))
            else:
                fn()
            print(f"  ok    {name}")
        except AssertionError as exc:
            failures += 1
            print(f"  FAIL  {name}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"  ERROR {name}: {type(exc).__name__}: {exc}")
    print(f"\n{'FAILED' if failures else 'all passed'} ({failures} failure(s))")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())


def test_the_sample_count_comes_from_the_config_unless_flagged():
    """swarm hardcoded 5 and never loaded the config, so `samples = 2` changed
    `council review` and not `council swarm`."""
    assert swarm.resolve_samples(None, {"review": {"samples": 2}}) == 2
    assert swarm.resolve_samples(4, {"review": {"samples": 2}}) == 4
    assert swarm.resolve_samples(None, {}) == swarm.DEFAULT_SAMPLES
