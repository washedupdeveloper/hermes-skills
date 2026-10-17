#!/usr/bin/env python3
"""pr.py — post a council verdict to a GitHub pull request (M7's last gap).

The council already produces a verdict; this puts it where the reviewer of a pull
request is already looking. Two rules shape it:

**The body is the gate's, not this module's.** Every number comes from
`score_reviews.evaluate`, the same function the gate runs, so a PR comment cannot
disagree with `council gate` about the same run. Re-implementing the summary here
would create a second opinion with no authority.

**It does not post unless asked.** Like `council goal` and `council cron`, the default
is to print the request it *would* send. Posting a public comment is a side effect on
someone else's pull request; that is a person's decision, not a default.

Posting twice is the other hazard: GitHub has no idempotency key for reviews, so a
re-run would leave a second copy of the same verdict on the PR. The body therefore
carries an HTML-comment marker naming the run and the PR, and a run that is already
there is skipped rather than reposted. The marker is invisible when GitHub renders it.

    council pr <run-dir> --repo owner/name --pr 42              print the request
    council pr <run-dir> --repo owner/name --pr 42 --post       send it
    council pr <run-dir> --repo owner/name --pr 42 --post \
        --event auto                                            REQUEST_CHANGES when
                                                                the gate fails

The token is read from `GITHUB_TOKEN` or `GH_TOKEN` and is never accepted on the
command line, where it would be visible in `ps` and in shell history.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent

#: Overridable so the request shape can be exercised against a stub server. Also
#: how GitHub Enterprise is addressed.
DEFAULT_API = "https://api.github.com"

#: A review body is capped at 65536 characters by the API. Leave room for the
#: truncation notice rather than discovering the limit with a 422.
BODY_LIMIT = 60_000

#: The review event. COMMENT never blocks a merge; REQUEST_CHANGES does.
EVENTS = ("COMMENT", "REQUEST_CHANGES", "APPROVE", "auto")

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


def load(name: str, path: Path) -> Any:
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def marker_for(run_dir: Path, pr: int) -> str:
    """The idempotency marker: invisible in rendered markdown, unique per run + PR.

    The PR number is in it so one run can legitimately be posted to two pull
    requests, and re-posting to the same one is still caught.
    """
    return f"<!-- council-run:{run_dir.resolve().name} pr:{pr} -->"


def target_sha(run_dir: Path) -> Optional[str]:
    """The commit the run actually reviewed, from the harness's own meta.json.

    Pinned into the review so the comment is attached to the commit that was scored.
    Without it GitHub attaches the review to the PR's latest commit, which may be
    newer than what the council saw.
    """
    path = run_dir / "meta.json"
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    sha = payload.get("target_sha")
    return sha if isinstance(sha, str) and sha.strip() else None


def verdict(run_dir: Path) -> Dict[str, Any]:
    """The gate's own result for this run. Not a re-derivation of it."""
    score = load("score_reviews", HERE / "score_reviews.py")
    return score.evaluate(run_dir, score.calibrated_threshold())


def _location(finding: Dict[str, Any]) -> str:
    loc = finding.get("location") or {}
    path = str(loc.get("path") or "?")
    lines = str(loc.get("line_range") or "").strip()
    return f"`{path}{':' + lines if lines else ''}`"


def _table(result: Dict[str, Any]) -> List[str]:
    rows = [
        "| dimension | score | det | llm | β |",
        "|---|---:|---:|---:|---:|",
    ]
    for dim in result.get("per_dimension") or []:
        rows.append(
            f"| {dim['dimension']} | **{dim['score']:.2f}** | {dim['det']:.2f} | "
            f"{dim['llm']:.1f} | {dim['beta']:.2f} |")
    return rows


def _findings_block(result: Dict[str, Any], limit: int = 20) -> Tuple[List[str], int]:
    """Open blocking findings, worst first, and how many were left out."""
    blocking = sorted(result.get("blocking") or [],
                      key=lambda f: SEVERITY_ORDER.get(str(f.get("severity")), 9))
    lines: List[str] = []
    for finding in blocking[:limit]:
        severity = str(finding.get("severity") or "?").upper()
        lines.append(f"- **{severity}** {_location(finding)} — {finding.get('claim') or ''}")
        check = str(finding.get("falsifiable_check") or "").strip()
        if check:
            lines.append(f"  - check: `{check}`")
    return lines, max(0, len(blocking) - limit)


def body_for(result: Dict[str, Any], run_dir: Path, pr: int) -> str:
    """The review body: the verdict, then the evidence, then the marker."""
    satisfied = result.get("status") == "satisfied"
    head = "**Council verdict: PASS**" if satisfied else "**Council verdict: FAIL**"
    lines = [
        head,
        "",
        f"aggregate **{result['aggregate']:.2f}** / threshold {result['threshold']:g} — "
        f"{result.get('reason') or ''}",
        "",
        *_table(result),
        "",
    ]

    findings, omitted = _findings_block(result)
    if findings:
        lines += ["### Blocking findings", "", *findings, ""]
        if omitted:
            lines += [f"_{omitted} further blocking finding(s) omitted._", ""]
    elif satisfied:
        lines += ["No open high or critical findings.", ""]

    stacks = ", ".join(result.get("stacks") or []) or "none detected"
    lines += [
        "---",
        f"<sub>review-council · {result.get('size_kloc', 0):.1f} KLOC · "
        f"stacks: {stacks} · run `{run_dir.resolve().name}` · "
        f"recomputed from the reviewer files by the deterministic gate</sub>",
        marker_for(run_dir, pr),
    ]
    return "\n".join(lines)


def payload_for(result: Dict[str, Any], run_dir: Path, pr: int,
                event: str = "COMMENT") -> Dict[str, Any]:
    """The JSON body for `POST /pulls/{n}/reviews`."""
    if event == "auto":
        event = "COMMENT" if result.get("status") == "satisfied" else "REQUEST_CHANGES"
    body = body_for(result, run_dir, pr)
    if len(body) > BODY_LIMIT:
        # Cut on a line boundary so the markdown stays well-formed.
        body = body[:BODY_LIMIT].rsplit("\n", 1)[0] + (
            f"\n\n_Truncated at {BODY_LIMIT} characters; run `council gate {run_dir}` "
            f"for the full report._\n\n" + marker_for(run_dir, pr))
    payload: Dict[str, Any] = {"body": body, "event": event}
    sha = target_sha(run_dir)
    if sha:
        payload["commit_id"] = sha
    return payload


def request(method: str, url: str, token: Optional[str],
            payload: Optional[Dict[str, Any]] = None) -> Tuple[int, Any]:
    """One API call. Returns (status, parsed body or raw text).

    A non-2xx is returned, not raised: the caller reports GitHub's own message, which
    is the only text that explains why a token or a payload was refused.
    """
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "review-council")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read().decode("utf-8", "replace")
            status = response.status
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        status = exc.code
    except urllib.error.URLError as exc:
        return 0, f"could not reach {url}: {exc.reason}"
    try:
        return status, json.loads(raw)
    except json.JSONDecodeError:
        return status, raw


def api_message(status: int, body: Any) -> str:
    """GitHub's own explanation, and the one thing to check for the common codes."""
    if isinstance(body, dict):
        message = str(body.get("message") or "").strip()
        errors = body.get("errors")
        if errors:
            message += " (" + "; ".join(str(e) for e in errors) + ")"
    else:
        message = str(body)[:300].strip()
    hints = {
        401: "the token is missing, expired or malformed",
        403: "the token lacks permission, or the API is rate-limiting this account",
        404: "the repository or pull request does not exist, or the token cannot see it",
        422: "the payload was rejected — often a review body over the size limit",
    }
    hint = hints.get(status)
    return f"HTTP {status}: {message}" + (f" — {hint}" if hint else "")


def find_existing(api: str, repo: str, pr: int, token: Optional[str],
                  marker: str) -> Optional[int]:
    """The id of a review already carrying this run's marker, if any."""
    url = f"{api}/repos/{repo}/pulls/{pr}/reviews?per_page=100"
    status, body = request("GET", url, token)
    if status != 200 or not isinstance(body, list):
        return None
    for review in body:
        if isinstance(review, dict) and marker in str(review.get("body") or ""):
            return int(review.get("id") or 0)
    return None


def render_plan(api: str, repo: str, pr: int, payload: Dict[str, Any],
                run_dir: Path, existing: Optional[int]) -> List[str]:
    lines = [
        f"  run       {run_dir.resolve()}",
        f"  target    {repo}#{pr}",
        f"  endpoint  POST {api}/repos/{repo}/pulls/{pr}/reviews",
        f"  event     {payload['event']}"
        + (f"  (pinned to {payload['commit_id'][:12]})" if payload.get("commit_id") else ""),
        f"  body      {len(payload['body'])} characters",
        "",
    ]
    if existing:
        lines += [f"  Already posted as review {existing}. A re-post would duplicate it,",
                  "  so --post will skip. Delete that review on the PR to post again.", ""]
    lines += ["  --- body ---", ""]
    lines += [f"  {line}" if line else "" for line in payload["body"].splitlines()]
    lines += ["", "  --- end body ---", "",
              "  Add --post to send it. Without it, nothing is sent."]
    return lines


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="council pr",
        description="Post a council verdict to a GitHub pull request. Prints the "
                    "request by default; --post sends it.")
    parser.add_argument("run", metavar="RUN_DIR", help="the run directory to report")
    parser.add_argument("--repo", required=True, metavar="OWNER/NAME",
                        help="the GitHub repository the pull request belongs to")
    parser.add_argument("--pr", required=True, type=int, metavar="N",
                        help="the pull request number")
    parser.add_argument("--event", default="COMMENT", choices=EVENTS,
                        help="COMMENT (default, never blocks), REQUEST_CHANGES, "
                             "APPROVE, or auto (REQUEST_CHANGES when the gate fails)")
    parser.add_argument("--api", default=os.environ.get("GITHUB_API_URL", DEFAULT_API),
                        help=f"API base URL (default: {DEFAULT_API})")
    parser.add_argument("--post", action="store_true",
                        help="actually send it (default: print only)")
    parser.add_argument("--json", action="store_true", help="the payload as JSON")
    args = parser.parse_args(argv)

    run_dir = Path(args.run).expanduser().resolve()
    if not run_dir.is_dir():
        print(f"pr: not a directory: {run_dir}", file=sys.stderr)
        return 2
    if args.repo.count("/") != 1 or not all(args.repo.split("/")):
        print(f"pr: --repo must be OWNER/NAME, got {args.repo!r}", file=sys.stderr)
        return 2
    if args.pr < 1:
        print("pr: --pr must be a positive number", file=sys.stderr)
        return 2

    try:
        result = verdict(run_dir)
    except Exception as exc:  # noqa: BLE001 - the gate reports its own reasons
        print(f"pr: could not score {run_dir}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    if result.get("status") == "error":
        print(f"pr: the gate refused this run: {result.get('reason')}", file=sys.stderr)
        return 2

    payload = payload_for(result, run_dir, args.pr, args.event)
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    marker = marker_for(run_dir, args.pr)

    if not args.post:
        existing = find_existing(args.api, args.repo, args.pr, token, marker)
        if args.json:
            print(json.dumps({"payload": payload, "existing_review": existing}, indent=2,
                             ensure_ascii=False))
            return 0
        for line in render_plan(args.api, args.repo, args.pr, payload, run_dir, existing):
            print(line)
        return 0

    if not token:
        print("pr: no token. Set GITHUB_TOKEN or GH_TOKEN to a token with `pull_request`\n"
              "  write access. The token is never accepted on the command line, where it\n"
              "  would be visible in `ps` and in your shell history.", file=sys.stderr)
        return 2

    existing = find_existing(args.api, args.repo, args.pr, token, marker)
    if existing:
        print(f"  already posted as review {existing} — not posting again")
        return 0

    status, body = request(
        "POST", f"{args.api}/repos/{args.repo}/pulls/{args.pr}/reviews", token, payload)
    if status not in (200, 201):
        print(f"pr: {api_message(status, body)}", file=sys.stderr)
        return 1

    url = body.get("html_url") if isinstance(body, dict) else None
    review_id = body.get("id") if isinstance(body, dict) else None
    print(f"  posted review {review_id} to {args.repo}#{args.pr}")
    if url:
        print(f"  {url}")
    return 0


if __name__ == "__main__":
    # Not a program: reached through `council <verb>`. See council.py.
    from council import require_dispatch

    require_dispatch("pr")
    sys.exit(main())
