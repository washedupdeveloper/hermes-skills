"""Tests for pr.py — posting a verdict to a pull request.

Run standalone (no pytest needed):
    python tests/test_pr.py

The posting path is exercised against a stub GitHub API (stdlib `http.server`) that
records what the module actually sends. That proves the request shape, the auth
header, the idempotency check and the error reporting without a credential or a live
pull request. What it cannot prove is that github.com accepts the payload — see
`test_the_real_api_path_answers` for the read-only half of that, which runs when the
network allows and skips when it does not.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
_spec = importlib.util.spec_from_file_location("pr", REPO / "scripts" / "pr.py")
pr = importlib.util.module_from_spec(_spec)
sys.modules["pr"] = pr
_spec.loader.exec_module(pr)

GOLDEN = REPO / "tests" / "golden" / "rounds" / "defects"


# --- a stub GitHub API -------------------------------------------------------

class State:
    """What the stub answers, and what it was asked."""

    def __init__(self):
        self.reviews = []          # GET /reviews returns this
        self.post_status = 200
        self.post_body = {"id": 7, "html_url": "https://example.invalid/r/7"}
        self.requests = []         # (method, path, headers, parsed body)

    def reset(self):
        self.reviews = []
        self.post_status = 200
        self.post_body = {"id": 7, "html_url": "https://example.invalid/r/7"}
        self.requests = []


STATE = State()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep the test output clean
        pass

    def _send(self, status, payload):
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        STATE.requests.append(("GET", self.path, dict(self.headers), None))
        if self.path.endswith("/reviews?per_page=100"):
            self._send(200, STATE.reviews)
            return
        self._send(404, {"message": "Not Found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        STATE.requests.append(("POST", self.path, dict(self.headers), body))
        if STATE.post_status >= 400:
            self._send(STATE.post_status, STATE.post_body)
            return
        self._send(STATE.post_status, STATE.post_body)


def serve():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


SERVER, API = serve()


def _with_token(value: Optional[str] = "stub-token"):
    """A context manager-ish helper: set the token, return the previous value."""
    previous = os.environ.get("GITHUB_TOKEN")
    if value is None:
        os.environ.pop("GITHUB_TOKEN", None)
    else:
        os.environ["GITHUB_TOKEN"] = value
    return previous


def _restore_token(previous):
    if previous is None:
        os.environ.pop("GITHUB_TOKEN", None)
    else:
        os.environ["GITHUB_TOKEN"] = previous


def _run(*args, token="stub-token"):
    """Call main() with the stub API, restoring the environment afterwards."""
    previous = _with_token(token)
    try:
        return pr.main([str(GOLDEN), "--repo", "owner/name", "--pr", "42",
                        "--api", API, *args])
    finally:
        _restore_token(previous)


# --- the body is the gate's ---------------------------------------------------

def test_the_body_reports_the_gates_own_numbers():
    """Every figure comes from score_reviews.evaluate, so a PR cannot disagree
    with `council gate` about the same run."""
    result = pr.verdict(GOLDEN)
    body = pr.body_for(result, GOLDEN, 42)

    assert "Council verdict: FAIL" in body, body[:200]
    assert f"{result['aggregate']:.2f}" in body, "the aggregate must appear"
    assert f"{result['threshold']:g}" in body, "the threshold must appear"
    assert result["reason"] in body, "the gate's reason must appear"


def test_the_body_carries_a_per_dimension_table():
    body = pr.body_for(pr.verdict(GOLDEN), GOLDEN, 42)
    for dim in ("security", "correctness", "readability", "architecture", "performance"):
        assert f"| {dim} |" in body, f"{dim} missing from the table"


def test_blocking_findings_are_listed_worst_first():
    result = pr.verdict(GOLDEN)
    body = pr.body_for(result, GOLDEN, 42)
    severities = [str(f.get("severity")) for f in result["blocking"]]
    positions = [body.find(str(f.get("claim"))) for f in result["blocking"]]
    assert all(p >= 0 for p in positions), "every blocking finding must appear"
    assert positions == sorted(positions), "worst severity must come first"
    assert "CRITICAL" in body or "critical" in body.lower(), severities


def test_the_body_carries_the_run_marker():
    """Invisible when rendered, and the whole basis of not posting twice."""
    body = pr.body_for(pr.verdict(GOLDEN), GOLDEN, 42)
    assert pr.marker_for(GOLDEN, 42) in body


def test_the_marker_differs_per_pull_request():
    """One run may legitimately be posted to two PRs."""
    assert pr.marker_for(GOLDEN, 42) != pr.marker_for(GOLDEN, 43)


def test_an_oversized_body_is_truncated_and_still_marked():
    """The backstop for a pathological finding, not for a long list: the body lists
    at most 20 findings, so only a very long `claim` can reach the API's size limit."""
    result = pr.verdict(GOLDEN)
    result["blocking"] = [
        {"dimension": "security", "severity": "high", "claim": "x" * 5_000,
         "location": {"path": "a.nix", "line_range": "1"}, "falsifiable_check": "y"}
    ] * 20
    payload = pr.payload_for(result, GOLDEN, 42)
    assert len(payload["body"]) < 62_000, len(payload["body"])
    assert "Truncated" in payload["body"], "an oversized body must say it was cut"
    assert pr.marker_for(GOLDEN, 42) in payload["body"], "the marker must survive"


# --- the request --------------------------------------------------------------

def test_printing_sends_no_post():
    STATE.reset()
    assert _run() == 0
    methods = [r[0] for r in STATE.requests]
    assert "POST" not in methods, f"a dry run posted: {methods}"


def test_posting_sends_the_documented_request():
    STATE.reset()
    assert _run("--post") == 0

    posts = [r for r in STATE.requests if r[0] == "POST"]
    assert len(posts) == 1, posts
    _, path, headers, body = posts[0]
    assert path == "/repos/owner/name/pulls/42/reviews", path
    assert body["event"] == "COMMENT", body
    assert "Council verdict" in body["body"]
    # the token travels in a header, never in the body or the URL
    assert headers.get("Authorization") == "Bearer stub-token", headers.get("Authorization")
    assert "stub-token" not in json.dumps(body), "the token must not appear in the payload"


def test_a_second_post_is_skipped_rather_than_duplicated():
    """GitHub has no idempotency key for reviews, so a re-run must not double-post."""
    STATE.reset()
    assert _run("--post") == 0
    first = [r for r in STATE.requests if r[0] == "POST"]
    assert len(first) == 1

    # the review now exists on the server, carrying the marker
    STATE.reviews = [{"id": 7, "body": pr.marker_for(GOLDEN, 42)}]
    assert _run("--post") == 0
    second = [r for r in STATE.requests if r[0] == "POST"]
    assert len(second) == 1, "a marked run must not be posted twice"


def test_printing_reports_an_existing_review():
    """A re-run must tell the operator it is already there, not stay silent."""
    import contextlib
    import io

    STATE.reset()
    STATE.reviews = [{"id": 7, "body": pr.marker_for(GOLDEN, 42)}]
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        assert _run() == 0
    assert "Already posted as review 7" in buffer.getvalue(), buffer.getvalue()


def test_the_plan_names_the_endpoint_and_the_opt_in():
    payload = pr.payload_for(pr.verdict(GOLDEN), GOLDEN, 42)
    text = "\n".join(pr.render_plan(API, "owner/name", 42, payload, GOLDEN, None))
    assert "POST " in text and "/pulls/42/reviews" in text
    assert "--post" in text, "the plan must say how to actually send it"


# --- refusals -----------------------------------------------------------------

def test_no_token_is_refused_and_nothing_is_posted():
    STATE.reset()
    assert _run("--post", token=None) == 2
    assert not [r for r in STATE.requests if r[0] == "POST"], "posted without a token"


def test_a_bad_token_reports_githubs_message():
    STATE.reset()
    STATE.post_status = 401
    STATE.post_body = {"message": "Bad credentials"}
    assert _run("--post") == 1
    # the message is on stderr; the exit code is what this asserts


def test_a_missing_pull_request_reports_404():
    STATE.reset()
    STATE.post_status = 404
    STATE.post_body = {"message": "Not Found"}
    assert _run("--post") == 1


def test_a_rejected_payload_reports_422_with_its_errors():
    STATE.reset()
    STATE.post_status = 422
    STATE.post_body = {"message": "Validation Failed",
                       "errors": [{"resource": "PullRequestReview", "code": "custom"}]}
    assert _run("--post") == 1
    text = pr.api_message(422, STATE.post_body)
    assert "Validation Failed" in text
    assert "PullRequestReview" in text, "GitHub's own error detail must be surfaced"
    assert "size limit" in text, "the likely cause must be named"


def test_the_api_message_names_the_likely_cause_for_each_code():
    for code, expected in ((401, "expired"), (403, "rate-limiting"),
                           (404, "does not exist"), (422, "size limit")):
        assert expected in pr.api_message(code, {"message": "m"}), code


def test_a_bad_repo_spec_is_refused():
    previous = _with_token()
    try:
        assert pr.main([str(GOLDEN), "--repo", "no-slash", "--pr", "1"]) == 2
        assert pr.main([str(GOLDEN), "--repo", "a/b/c", "--pr", "1"]) == 2
    finally:
        _restore_token(previous)


def test_a_missing_run_directory_is_refused():
    previous = _with_token()
    try:
        assert pr.main(["/nonexistent/run", "--repo", "o/n", "--pr", "1"]) == 2
    finally:
        _restore_token(previous)


def test_a_non_positive_pr_number_is_refused():
    previous = _with_token()
    try:
        assert pr.main([str(GOLDEN), "--repo", "o/n", "--pr", "0"]) == 2
    finally:
        _restore_token(previous)


# --- the event ----------------------------------------------------------------

def test_comment_never_blocks_a_merge():
    """The default must not be able to block someone's merge."""
    assert pr.payload_for(pr.verdict(GOLDEN), GOLDEN, 42)["event"] == "COMMENT"


def test_auto_requests_changes_only_when_the_gate_fails():
    failing = pr.verdict(GOLDEN)
    assert failing["status"] == "not_satisfied"
    assert pr.payload_for(failing, GOLDEN, 42, "auto")["event"] == "REQUEST_CHANGES"

    passing = dict(failing, status="satisfied")
    assert pr.payload_for(passing, GOLDEN, 42, "auto")["event"] == "COMMENT"


# --- pinning to the reviewed commit -------------------------------------------

def test_the_review_is_pinned_to_the_commit_the_run_reviewed():
    """Without commit_id GitHub attaches the review to the PR's latest commit,
    which may be newer than what the council actually scored."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        run = Path(td)
        for name in ("security", "correctness", "readability", "architecture",
                     "performance"):
            source = GOLDEN / f"{name}.json"
            (run / f"{name}.json").write_text(source.read_text(encoding="utf-8"),
                                              encoding="utf-8")
        (run / "meta.json").write_text(
            json.dumps({"target_sha": "a" * 40, "stacks": ["nix"]}), encoding="utf-8")
        payload = pr.payload_for(pr.verdict(run), run, 42)
        assert payload.get("commit_id") == "a" * 40, payload.get("commit_id")


def test_no_meta_file_means_no_commit_id_rather_than_a_guess():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        run = Path(td)
        for name in ("security", "correctness", "readability", "architecture",
                     "performance"):
            source = GOLDEN / f"{name}.json"
            (run / f"{name}.json").write_text(source.read_text(encoding="utf-8"),
                                              encoding="utf-8")
        assert "commit_id" not in pr.payload_for(pr.verdict(run), run, 42)


# --- the real API, read-only ---------------------------------------------------

def test_the_real_api_path_answers():
    """The URL shape and response parsing, against github.com itself.

    Read-only and unauthenticated: it lists a public repository's reviews, which needs
    no credential. Skips when the network is unavailable rather than failing, because
    a unit suite must not depend on github.com being reachable.
    """
    try:
        with urllib.request.urlopen(
                "https://api.github.com/repos/cli/cli/pulls/1/reviews?per_page=1",
                timeout=20) as response:
            status = response.status
            body = json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"    (skipped: {type(exc).__name__})")
        return
    assert status == 200, status
    assert isinstance(body, list), body
    if body:
        assert "id" in body[0] and "body" in body[0], body[0]


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


# --- the API base is a boundary ------------------------------------------------

def test_the_api_base_is_a_boundary():
    """`--api` / GITHUB_API_URL are operator input, so they are untrusted.

    Without validation a `file:` base reads local paths through urlopen, and a plain-http
    host receives the bearer token in cleartext.
    """
    try:
        pr.request("GET", "file:///etc/hostname", None)
    except ValueError as exc:
        assert "file" in str(exc).lower(), exc
    else:
        raise AssertionError("a file: URL was not refused")

    try:
        pr.request("GET", "http://example.com/x", None)
    except ValueError as exc:
        assert "https" in str(exc).lower(), exc
    else:
        raise AssertionError("cleartext http off loopback was not refused")

    # Loopback http stays allowed: the stub server and a local proxy need it.
    assert pr.validate_api_url("http://127.0.0.1:9/x") == "http://127.0.0.1:9/x"
    assert pr.validate_api_url("http://localhost:9/x") == "http://localhost:9/x"
    assert pr.validate_api_url("https://api.github.com") == "https://api.github.com"

    # And the CLI reports a usage error rather than a traceback.
    assert pr.main([str(GOLDEN), "--repo", "o/n", "--pr", "1",
                    "--api", "file:///etc/hostname"]) == 2
