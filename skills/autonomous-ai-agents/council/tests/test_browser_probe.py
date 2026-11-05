"""The runtime lane: what the page does when a browser loads it.

Run standalone (no pytest needed):
    python tests/test_browser_probe.py

A stub driver is the point, not a shortcut: the probe's contract is an argv plus a stdout DOM, so
the logic can be gated on a machine with no browser — which is every machine that runs
`nix flake check` for this repository.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("probes", REPO / "scripts" / "probes.py")
probes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(probes)

_sspec = importlib.util.spec_from_file_location("score_reviews", REPO / "scripts" / "score_reviews.py")
score = importlib.util.module_from_spec(_sspec)
sys.modules["score_reviews"] = score
_sspec.loader.exec_module(score)

STUB = r'''"""A stand-in for chromium: same argv contract, no browser."""
import pathlib
import sys

args = sys.argv[1:]
url = args[-1]
shot = next((a.split("=", 1)[1] for a in args if a.startswith("--screenshot=")), None)
if shot:
    pathlib.Path(shot).write_bytes(b"\x89PNG\r\n")
mode = pathlib.Path(__file__).with_name("mode.txt").read_text().strip() if pathlib.Path(__file__).with_name("mode.txt").exists() else "clean"
if mode == "clean":
    print("<html><body><div id='app'><h1>Hello</h1><p>rendered content here</p></div></body></html>")
elif mode == "empty":
    print("<html><body><div id='app'></div></body></html>")
elif mode == "error":
    print("<html><body><div id='app'><p>app shell</p></div></body></html>")
    print("Uncaught TypeError: Cannot read properties of undefined (reading 'map')", file=sys.stderr)
elif mode == "crash":
    print("Fatal: cannot launch", file=sys.stderr)
    sys.exit(3)
'''


def _stub(tmp: Path, mode: str) -> str:
    """A driver command that runs the stub under this interpreter (no shebang, no chmod)."""
    script = tmp / "chromium_stub.py"
    script.write_text(STUB, encoding="utf-8")
    (tmp / "mode.txt").write_text(mode, encoding="utf-8")
    return f"{sys.executable} {script}"


def _repo(tmp: Path, entry: str | None = "index.html") -> Path:
    root = tmp / "repo"
    root.mkdir()
    if entry:
        (root / entry).write_text("<html><body></body></html>", encoding="utf-8")
    return root


def _run(root: Path, driver: str | None, url: str | None = None) -> dict:
    old = dict(os.environ)
    try:
        if driver is None:
            os.environ["COUNCIL_BROWSER_CMD"] = ""
            os.environ["PATH"] = str(Path(tempfile.gettempdir()) / "no-such-path")
        else:
            os.environ["COUNCIL_BROWSER_CMD"] = driver
        if url is None:
            os.environ.pop("COUNCIL_WEB_URL", None)
        else:
            os.environ["COUNCIL_WEB_URL"] = url
        return probes.run_probe("browser", root)
    finally:
        os.environ.clear()
        os.environ.update(old)


# --- the contract ---------------------------------------------------------------


def test_the_argv_contract_is_pinned():
    argv = probes.browser_argv("/usr/bin/chromium", "file:///x/index.html", Path("/tmp/shot.png"))
    assert argv[0] == "/usr/bin/chromium"
    assert "--dump-dom" in argv and argv[-1] == "file:///x/index.html"
    assert "--screenshot=/tmp/shot.png" in argv
    assert any(a.startswith("--virtual-time-budget=") for a in argv)
    assert "--headless=new" in argv


def test_a_driver_command_may_carry_arguments():
    argv = probes.browser_argv("/usr/bin/chromium --no-first-run", "file:///x", Path("/tmp/s.png"))
    assert argv[:2] == ["/usr/bin/chromium", "--no-first-run"]


# --- the three ways the lane cannot answer -------------------------------------


def test_no_entry_point_and_no_url_is_not_observed():
    with tempfile.TemporaryDirectory() as tmp:
        root = _repo(Path(tmp), entry=None)
        out = _run(root, driver=None)
    assert out["ran"] is False and out["parsed"] is False
    assert "not observed" in out["note"]
    assert out["signal"] is None


def test_no_driver_is_not_observed_and_names_the_fix():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        root = _repo(tmp_path)
        out = _run(root, driver=None)
    assert out["ran"] is False
    assert "COUNCIL_BROWSER_CMD" in out["note"]
    assert "not observed" in out["note"]
    assert out["signal"] is None, "an unobserved runtime must never carry a score"


# --- what an observation looks like -------------------------------------------


def test_a_clean_page_scores_100_and_reports_artifacts():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        out = _run(_repo(tmp_path), _stub(tmp_path, "clean"))
    assert out["ran"] is True and out["parsed"] is True
    assert out["signal"] == 100.0
    assert out["findings"] == []
    assert "screenshot=" in out["note"] and "dom=" in out["note"]


def test_a_page_error_is_a_major_finding():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        out = _run(_repo(tmp_path), _stub(tmp_path, "error"))
    assert out["signal"] == 80.0
    assert len(out["findings"]) == 1
    assert out["findings"][0]["severity"] == "major"
    assert "Uncaught" in out["findings"][0]["claim"]
    assert "--dump-dom" in out["findings"][0]["falsifiable_check"]


def test_an_empty_render_is_critical():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        out = _run(_repo(tmp_path), _stub(tmp_path, "empty"))
    assert out["signal"] == 60.0
    assert out["findings"][0]["severity"] == "critical"
    assert "did not mount" in out["findings"][0]["claim"]


def test_a_browser_that_crashes_is_critical_not_a_pass():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        out = _run(_repo(tmp_path), _stub(tmp_path, "crash"))
    assert out["ran"] is True
    assert out["parsed"] is False and out["signal"] is None
    assert out["findings"][0]["severity"] == "critical"
    assert "exit 3" in out["findings"][0]["claim"]


# --- declared assertions -------------------------------------------------------


def test_assertions_are_checked_against_the_rendered_dom():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        root = _repo(tmp_path)
        (root / ".review-council").mkdir()
        (root / ".review-council" / "web-assertions.json").write_text(
            json.dumps({"assertions": [
                {"selector": "#app", "why": "the root node must exist"},
                {"selector": ".dashboard", "why": "the dashboard must render"},
                {"selector": "text:Hello", "why": "the heading must be visible"},
            ]}),
            encoding="utf-8",
        )
        out = _run(root, _stub(tmp_path, "clean"))
    assert out["signal"] == 80.0
    claims = [f["claim"] for f in out["findings"]]
    assert any(".dashboard" in c for c in claims)
    assert not any("#app" in c for c in claims)
    assert not any("text:Hello" in c for c in claims)


def test_an_unparseable_assertions_file_is_minor_not_silent():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        root = _repo(tmp_path)
        (root / ".review-council").mkdir()
        (root / ".review-council" / "web-assertions.json").write_text("{not json", encoding="utf-8")
        out = _run(root, _stub(tmp_path, "clean"))
    assert out["signal"] == 95.0
    assert out["findings"][0]["severity"] == "minor"


# --- the review is a read ------------------------------------------------------


def test_the_probe_writes_nothing_into_the_reviewed_repo():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        root = _repo(tmp_path)
        before = sorted(p.name for p in root.rglob("*"))
        _run(root, _stub(tmp_path, "clean"))
        after = sorted(p.name for p in root.rglob("*"))
    assert before == after


# --- the gate's stack table ----------------------------------------------------


def test_a_page_puts_the_repo_in_the_web_stack():
    with tempfile.TemporaryDirectory() as tmp:
        root = _repo(Path(tmp))
        assert "web" in score.detect_stacks(root)


def test_a_server_rendered_app_is_web_even_with_no_html_to_load():
    """Next App Router: no root index.html, so the stack must come from its entry file.

    Without this the repo is not in the runtime lane at all, and a correctness review of a Next
    app quietly scores as if there were nothing to observe.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "repo"
        (root / "app").mkdir(parents=True)
        (root / "app" / "page.tsx").write_text("export default function Page(){return null}",
                                               encoding="utf-8")
        (root / "package.json").write_text('{"name":"app"}', encoding="utf-8")
        assert "web" in score.detect_stacks(root)


def test_javascript_without_a_page_is_not_in_the_runtime_lane():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "repo"
        root.mkdir()
        (root / "package.json").write_text('{"name":"lib"}', encoding="utf-8")
        stacks = score.detect_stacks(root)
    assert "javascript" in stacks
    assert "web" not in stacks, "a CLI package has no page to load and must not be scored on one"


def test_the_runtime_lane_is_expected_only_for_the_web_stack():
    assert score.STACK_TOOLS["correctness"]["web"] == ["browser"]
    for stack in ("python", "nix", "javascript", "rust", "go", "shell"):
        assert "browser" not in score.STACK_TOOLS["correctness"][stack], stack


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
