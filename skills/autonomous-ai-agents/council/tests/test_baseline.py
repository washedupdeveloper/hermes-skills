#!/usr/bin/env python3
"""Tests for baseline-relative review.

No model is called. What is pinned here is the part that decides the verdict --
what counts as "the same finding", what invalidates a carried one, and what
qualifies as a baseline. A bug in any of those produces a confidently wrong
score, which is the failure this whole module exists to avoid.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS))

import baseline  # noqa: E402


def _load(name: str, path: Path):
    """Load a sibling module by path, registering it so dataclasses resolve."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# --- the drift guard --------------------------------------------------------

def test_fingerprint_matches_ablate():
    """The two must agree, or a carried finding and a re-found one both count.

    `ablate.py` fingerprints findings to compare arms; `baseline.py` fingerprints
    them to decide whether a finding is already known. If the algorithms drift,
    a baseline finding that the reviewer re-finds is counted twice -- inflating
    density and lowering the score for a repository that did not get worse.
    """
    ablate = _load("ablate", SCRIPTS / "ablate.py")
    samples = [
        {"location": {"path": "src/a.py", "line_range": "10"}, "claim": "A live API key!"},
        {"location": {"path": "a\\b.nix", "line_range": "1-4"}, "claim": "Mixed CASE claim."},
        {"location": {}, "claim": ""},
        {"location": {"path": "./x/y.sh"}, "claim": "  padded   spaces  "},
    ]
    for finding in samples:
        assert baseline.fingerprint(finding) == ablate._fingerprint(finding), finding


def test_fingerprint_ignores_case_and_punctuation():
    a = {"location": {"path": "src/a.py", "line_range": "10"},
         "claim": "A live API credential is committed as a plaintext literal!"}
    b = {"location": {"path": "src/a.py", "line_range": "10"},
         "claim": "a live api credential is committed as a plaintext literal"}
    assert baseline.fingerprint(a) == baseline.fingerprint(b)


def test_fingerprint_separates_different_locations():
    a = {"location": {"path": "src/a.py", "line_range": "10"}, "claim": "same words"}
    b = {"location": {"path": "src/b.py", "line_range": "10"}, "claim": "same words"}
    assert baseline.fingerprint(a) != baseline.fingerprint(b)


def test_fingerprint_normalises_backslashes():
    """A Windows checkout may echo backslashes; identity must not care."""
    a = {"location": {"path": "src\\a.py", "line_range": "1"}, "claim": "x"}
    b = {"location": {"path": "src/a.py", "line_range": "1"}, "claim": "x"}
    assert baseline.fingerprint(a) == baseline.fingerprint(b)


# --- claim path extraction --------------------------------------------------

def test_claim_paths_finds_paths():
    assert "docs/adr/0003.md" in baseline.claim_paths("contradicts docs/adr/0003.md")
    assert "modules/wsl/default.nix" in baseline.claim_paths(
        "see modules/wsl/default.nix line 20"
    )


def test_claim_paths_ignores_urls_and_versions():
    assert baseline.claim_paths("see https://example.com/a/b for details") == []
    assert baseline.claim_paths("pinned to 2.35.2") == []


def test_claim_paths_strips_trailing_punctuation():
    got = baseline.claim_paths("the file topology.nix, which models")
    assert got == ["topology.nix"], got


def test_claim_paths_empty_on_prose():
    assert baseline.claim_paths("the comment is misleading about the default") == []


# --- carry / invalidation ---------------------------------------------------

def _finding(path: str, claim: str, dim: str = "readability"):
    return {"location": {"path": path, "line_range": "1"}, "claim": claim,
            "severity": "low", "id": "X-1", "_dimension": dim}


def test_carry_keeps_an_untouched_finding():
    carried, dropped = baseline.carry([_finding("a.nix", "something wrong here")], ["b.nix"])
    assert len(carried) == 1 and dropped == []


def test_carry_drops_a_finding_whose_own_file_changed():
    carried, dropped = baseline.carry([_finding("a.nix", "something wrong")], ["a.nix"])
    assert carried == []
    assert dropped[0]["_drop"] == "self"


def test_carry_drops_a_finding_that_references_a_changed_file():
    """The cross-cutting class: a claim about a file that has since changed."""
    finding = _finding("docs/adr/0003.md", "claims .wslconfig has no processors key")
    carried, dropped = baseline.carry([finding], ["docs/adr/0003.md", ".wslconfig"])
    assert carried == []
    # `self` fires first, which is the correct and cheaper reason.
    assert dropped[0]["_drop"] == "self"


def test_carry_reference_rule_fires_when_only_the_referenced_file_changed():
    finding = _finding("docs/adr/0003.md", "claims .wslconfig has no processors key")
    carried, dropped = baseline.carry([finding], [".wslconfig"])
    assert carried == []
    assert dropped[0]["_drop"] == "reference"


def test_carry_keeps_a_finding_with_no_path_and_no_claim_paths():
    """Conservative: a claim that mentions no path cannot be invalidated this way."""
    finding = _finding("", "the default is misleading")
    carried, dropped = baseline.carry([finding], ["a.nix"])
    assert len(carried) == 1 and dropped == []


def test_carry_handles_a_windows_style_changed_path():
    carried, dropped = baseline.carry([_finding("a/b.nix", "wrong")], ["a\\b.nix"])
    assert carried == [] and dropped[0]["_drop"] == "self"


# --- is_baseline ------------------------------------------------------------

def _make_run(root: Path, *, stamp="20260101-000000", scope="whole-repo",
              sha="deadbeef", dims=None, dropped=None, round_no=1) -> Path:
    run_root = root / ".review-council" / stamp
    round_dir = run_root / f"round-{round_no}"
    round_dir.mkdir(parents=True)
    meta = {"target_sha": sha, "mode": scope, "round": round_no,
            "stacks": ["nix"], "repo": str(root)}
    if dropped is not None:
        meta["dropped"] = dropped
    (round_dir / "meta.json").write_text(json.dumps(meta))
    for dim in (dims if dims is not None else baseline.DIMENSIONS):
        (round_dir / f"{dim}.json").write_text(json.dumps({"findings": [], "score": 90.0}))
    return run_root


def test_is_baseline_accepts_a_complete_whole_repo_run():
    with tempfile.TemporaryDirectory() as td:
        ok, reasons = baseline.is_baseline(_make_run(Path(td), dropped=0))
        assert ok, reasons


def test_is_baseline_rejects_a_narrower_scope():
    with tempfile.TemporaryDirectory() as td:
        ok, reasons = baseline.is_baseline(_make_run(Path(td), scope="diff", dropped=0))
        assert not ok and any("scope" in r for r in reasons), reasons


def test_is_baseline_rejects_a_missing_dimension():
    with tempfile.TemporaryDirectory() as td:
        run = _make_run(Path(td), dims=("security", "correctness"), dropped=0)
        ok, reasons = baseline.is_baseline(run)
        assert not ok and any("dimension files missing" in r for r in reasons), reasons


def test_is_baseline_rejects_a_dropped_finding():
    """A baseline missing findings it never reported carries that hole forever."""
    with tempfile.TemporaryDirectory() as td:
        ok, reasons = baseline.is_baseline(_make_run(Path(td), dropped=3))
        assert not ok and any("dropped" in r for r in reasons), reasons


def test_is_baseline_rejects_an_unrecorded_dropped_count():
    """Older runs predate the field; treating them as complete would be a guess."""
    with tempfile.TemporaryDirectory() as td:
        ok, reasons = baseline.is_baseline(_make_run(Path(td)))
        assert not ok and any("not recorded" in r for r in reasons), reasons


def test_is_baseline_rejects_an_unpinned_sha():
    with tempfile.TemporaryDirectory() as td:
        ok, reasons = baseline.is_baseline(_make_run(Path(td), sha="", dropped=0))
        assert not ok and any("unchanged" in r for r in reasons), reasons


def test_is_baseline_rejects_an_empty_run_root():
    with tempfile.TemporaryDirectory() as td:
        ok, reasons = baseline.is_baseline(Path(td))
        assert not ok and any("no round" in r for r in reasons), reasons


def test_find_baseline_picks_the_newest_qualifying_run():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _make_run(root, stamp="20260101-000000", dropped=0)
        _make_run(root, stamp="20260202-000000", dropped=0)
        found, _ = baseline.find_baseline(root)
        assert found is not None and found.name == "20260202-000000", found


def test_find_baseline_skips_a_disqualified_newer_run():
    """Newest-first, but a disqualified run must not shadow a valid older one."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _make_run(root, stamp="20260101-000000", dropped=0)
        _make_run(root, stamp="20260202-000000", scope="diff", dropped=0)
        found, notes = baseline.find_baseline(root)
        assert found is not None and found.name == "20260101-000000", found
        assert any("scope" in n for n in notes), notes


def test_find_baseline_reports_why_each_was_rejected():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _make_run(root, scope="diff", dropped=0)
        found, notes = baseline.find_baseline(root)
        assert found is None
        assert notes and "scope" in notes[0], notes


# --- merge_into_round -------------------------------------------------------

def test_merge_adds_carried_findings_to_the_right_dimension():
    with tempfile.TemporaryDirectory() as td:
        round_dir = Path(td)
        for dim in baseline.DIMENSIONS:
            (round_dir / f"{dim}.json").write_text(json.dumps({"findings": []}))
        carried = [_finding("a.nix", "wrong", dim="readability")]
        added = baseline.merge_into_round(round_dir, carried)
        assert added == {"readability": 1}
        got = json.loads((round_dir / "readability.json").read_text())["findings"]
        assert len(got) == 1
        assert not any(k.startswith("_") for k in got[0]), got[0]


def test_merge_does_not_double_count_a_refound_finding():
    """The reviewer re-found it, so the carried copy must not also land."""
    with tempfile.TemporaryDirectory() as td:
        round_dir = Path(td)
        for dim in baseline.DIMENSIONS:
            (round_dir / f"{dim}.json").write_text(json.dumps({"findings": []}))
        finding = _finding("a.nix", "wrong", dim="readability")
        (round_dir / "readability.json").write_text(
            json.dumps({"findings": [{k: v for k, v in finding.items() if not k.startswith("_")}]})
        )
        added = baseline.merge_into_round(round_dir, [finding])
        assert added == {}
        got = json.loads((round_dir / "readability.json").read_text())["findings"]
        assert len(got) == 1, got


def test_merge_ignores_a_missing_dimension_file():
    with tempfile.TemporaryDirectory() as td:
        round_dir = Path(td)
        (round_dir / "security.json").write_text(json.dumps({"findings": []}))
        added = baseline.merge_into_round(round_dir, [_finding("a.nix", "x", dim="readability")])
        assert added == {}


# --- changed_files ----------------------------------------------------------

def test_changed_files_respects_gitignore():
    """The user's requirement: the file set honours .ignore, or it is not data."""
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "t@e"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
        (repo / ".gitignore").write_text("ignored/\n")
        (repo / "kept.nix").write_text("{ }\n")
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)
        sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                             capture_output=True, text=True).stdout.strip()

        (repo / "ignored").mkdir()
        (repo / "ignored" / "junk.nix").write_text("{ }\n")
        (repo / "added.nix").write_text("{ }\n")

        got = baseline.changed_files(repo, sha)
        assert "added.nix" in got, got
        assert not any("ignored" in p for p in got), got


def test_changed_files_covers_committed_and_working_tree():
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "t@e"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
        (repo / "a.nix").write_text("{ }\n")
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)
        sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                             capture_output=True, text=True).stdout.strip()

        (repo / "a.nix").write_text("{ x = 1; }\n")          # uncommitted edit
        subprocess.run(["git", "commit", "-qam", "change"], cwd=repo, check=True)

        got = baseline.changed_files(repo, sha)
        assert got == ["a.nix"], got


if __name__ == "__main__":
    import traceback

    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"  PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"  FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n  {len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
