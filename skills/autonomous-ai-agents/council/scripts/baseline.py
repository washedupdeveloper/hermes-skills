#!/usr/bin/env python3
"""Carry a baseline's findings for unchanged files, and re-derive the rest.

The denominator stays the whole repo, so the aggregate keeps meaning what it
meant at baseline. Invariants and invalidation rules: docs/BASELINE.md.
"""
from __future__ import annotations

import argparse
import importlib.util as _shared_util
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

# `_shared` by path, like every sibling here -- see its own docstring for why a
# plain import would not be safe.
_SHARED_SPEC = _shared_util.spec_from_file_location(
    "_shared", Path(__file__).resolve().parent / "_shared.py")
assert _SHARED_SPEC is not None and _SHARED_SPEC.loader is not None, "_shared.py"
_shared = _shared_util.module_from_spec(_SHARED_SPEC)
_SHARED_SPEC.loader.exec_module(_shared)

#: The five dimension files a complete round must have.
DIMENSIONS = ("security", "correctness", "readability", "architecture", "performance")

#: Scopes whose findings cover the whole repository and so may be a baseline.
BASELINE_SCOPES = ("whole-repo",)


# --- fingerprints -----------------------------------------------------------

def norm_path(value: Any) -> str:
    """Repo-relative, forward-slashed. A Windows checkout may echo backslashes."""
    return _shared.norm_path(value)


def fingerprint(finding: Dict[str, Any]) -> str:
    """A stable identity for a finding.

    MUST stay identical to `ablate._fingerprint`: the ablation and the baseline
    have to agree on what "the same finding" means, or a carried finding and a
    re-found one would both be counted. `tests/test_baseline.py` pins the two
    together so they cannot drift apart.

    Deliberately coarse -- the claim is normalised hard, because two passes
    describing the same defect will not phrase it identically.
    """
    return _shared.fingerprint(finding)


#: A URL is stripped before scanning, so its host and path cannot be mistaken
#: for a repository path.
_URL = re.compile(r"\b[a-z][a-z0-9+.-]*://\S+", re.IGNORECASE)

#: Tokens in a claim that name a file. Three shapes, because claims use all
#: three: a path (`docs/adr/0003.md`), a dotfile (`.wslconfig`), and a bare
#: filename (`topology.nix`). The bare filename matters most -- it is the common
#: way a comment refers to a file it does not live in.
_PATHISH = re.compile(
    r"(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+"      # docs/adr/0003.md
    r"|\.[A-Za-z0-9_-]{2,}"                      # .wslconfig
    r"|[A-Za-z0-9_-]+\.[A-Za-z][A-Za-z0-9]{0,7}"  # topology.nix
)


def claim_paths(claim: str) -> List[str]:
    """File-like tokens in a claim, normalised.

    Used for the `reference` invalidation rule: a claim that names a file is
    treated as being about that file, so a change to it invalidates the finding.

    Deliberately coarse, but not reckless. Over-matching is the dangerous
    direction -- a dropped finding is gone until the next baseline, because the
    reviewer is no longer reading that file -- so anything that is not
    recognisably a filename is left alone. A version (`2.35.2`) is excluded by
    requiring a letter in the extension, and a claim that names nothing simply
    cannot be invalidated this way.
    """
    text = _URL.sub(" ", str(claim or ""))
    out: List[str] = []
    for token in _PATHISH.findall(text):
        token = norm_path(token.rstrip(".,;:)"))
        if not token or token in out or token.endswith("/"):
            continue
        if not any(ch.isalpha() for ch in token):
            continue
        out.append(token)
    return out


# --- git --------------------------------------------------------------------

def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True, text=True
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed in {repo}: {proc.stderr.strip()}"
        )
    return proc.stdout


def changed_files(repo: Path, since_sha: str) -> List[str]:
    """Everything that differs from *since_sha*, working tree included.

    `git diff <sha>` compares that commit to the working tree, so it covers
    committed AND uncommitted edits in one call. Untracked files come from
    `ls-files --others --exclude-standard`, which honours `.gitignore` -- so the
    set is exactly "what a reviewer would consider source", not what happens to
    be on disk.
    """
    out: List[str] = []
    for line in _git(repo, "diff", "--name-only", since_sha).splitlines():
        line = norm_path(line)
        if line:
            out.append(line)
    for line in _git(repo, "ls-files", "--others", "--exclude-standard").splitlines():
        line = norm_path(line)
        if line:
            out.append(line)
    return sorted(set(out))


# --- runs -------------------------------------------------------------------

def round_dirs(run_root: Path) -> List[Path]:
    return sorted(p for p in run_root.glob("round-*") if p.is_dir())


def read_meta(round_dir: Path) -> Dict[str, Any]:
    path = round_dir / "meta.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def load_findings(round_dir: Path) -> List[Dict[str, Any]]:
    """Every finding in a round, tagged with the dimension file it came from."""
    out: List[Dict[str, Any]] = []
    for dim in DIMENSIONS:
        path = round_dir / f"{dim}.json"
        if not path.exists():
            continue
        try:
            review = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for finding in review.get("findings") or []:
            if isinstance(finding, dict):
                out.append({**finding, "_dimension": dim})
    return out


def dimension_scores(round_dir: Path) -> Dict[str, float]:
    """The LLM self-score per dimension, for carrying forward."""
    out: Dict[str, float] = {}
    for dim in DIMENSIONS:
        path = round_dir / f"{dim}.json"
        if not path.exists():
            continue
        try:
            review = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        score = review.get("score")
        if isinstance(score, (int, float)):
            out[dim] = float(score)
    return out


def is_baseline(run_root: Path) -> Tuple[bool, List[str]]:
    """Can this run serve as a baseline?

    Four conditions, each of which would otherwise make the carried findings a
    partial and therefore misleading picture of the repository:

    - a completed round whose recorded scope covers the whole repo
    - a pinned revision, so "unchanged" is well defined
    - all five dimension files present, so every dimension is covered
    - no findings dropped by the merge, so nothing was silently lost

    The last one is why `merge_generalist_samples` records `dropped` in
    `meta.json`: a baseline missing findings it never reported would carry that
    hole forward forever.
    """
    reasons: List[str] = []
    rounds = round_dirs(run_root)
    if not rounds:
        reasons.append("no round-* directory")
        return False, reasons

    last = rounds[-1]
    meta = read_meta(last)
    if not meta:
        reasons.append(f"{last.name}/meta.json missing or unreadable")
        return False, reasons

    if meta.get("mode") not in BASELINE_SCOPES:
        reasons.append(f"scope is {meta.get('mode')!r}, not one of {BASELINE_SCOPES}")

    if not meta.get("target_sha"):
        reasons.append("no target_sha recorded, so 'unchanged' is undefined")

    missing = [d for d in DIMENSIONS if not (last / f"{d}.json").exists()]
    if missing:
        reasons.append(f"dimension files missing: {', '.join(missing)}")

    dropped = meta.get("dropped")
    if dropped is None:
        reasons.append("dropped count not recorded (older run)")
    elif dropped:
        reasons.append(f"{dropped} finding(s) were dropped by the merge")

    return (not reasons), reasons


def find_baseline(project: Path) -> Tuple[Optional[Path], List[str]]:
    """The most recent run that qualifies as a baseline, newest first."""
    root = project / ".review-council"
    if not root.is_dir():
        return None, [f"{root} does not exist -- no run has been recorded"]

    notes: List[str] = []
    for run_root in sorted((p for p in root.iterdir() if p.is_dir()), reverse=True):
        ok, reasons = is_baseline(run_root)
        if ok:
            return run_root, notes
        notes.append(f"{run_root.name}: {'; '.join(reasons)}")
    return None, notes


# --- carry ------------------------------------------------------------------

def carry(
    findings: Sequence[Dict[str, Any]],
    changed: Iterable[str],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Split baseline findings into (carried, dropped) against the changed set.

    See the module docstring for the two rules and why they are conservative.
    """
    changed_set = {norm_path(p) for p in changed}

    carried: List[Dict[str, Any]] = []
    dropped: List[Dict[str, Any]] = []

    for finding in findings:
        loc = finding.get("location") or {}
        path = norm_path(loc.get("path"))

        if path and path in changed_set:
            dropped.append({**finding, "_drop": "self", "_why": f"{path} changed"})
            continue

        # `claim` is optional in a finding, so default to empty: `claim_paths`
        # takes a str, and a missing claim simply references no paths.
        hit = [p for p in claim_paths(finding.get("claim") or "") if p in changed_set]
        if hit:
            dropped.append({
                **finding, "_drop": "reference",
                "_why": f"claim references {', '.join(sorted(set(hit)))}",
            })
            continue

        carried.append(finding)

    return carried, dropped


def merge_into_round(round_dir: Path, carried: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    """Add carried findings to a round's dimension files, in place.

    Called after the reviewers have written their files and before the gate
    reads them, so the gate scores `carried + new` exactly as it would score a
    whole-repo round. The carried finding is tagged so a reader can tell which
    findings came from the baseline rather than this pass.
    """
    added: Dict[str, int] = {}
    for dim in DIMENSIONS:
        path = round_dir / f"{dim}.json"
        if not path.exists():
            continue
        try:
            review = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        existing = review.get("findings") or []
        seen = {fingerprint(f) for f in existing if isinstance(f, dict)}

        for finding in carried:
            if finding.get("_dimension") != dim:
                continue
            if fingerprint(finding) in seen:
                continue  # the reviewer re-found it; do not double-count
            existing.append({k: v for k, v in finding.items() if not k.startswith("_")})
            seen.add(fingerprint(finding))
            added[dim] = added.get(dim, 0) + 1

        review["findings"] = existing
        path.write_text(
            json.dumps(review, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8", newline="\n",
        )
    return added


# --- CLI --------------------------------------------------------------------

def _cmd_status(args: argparse.Namespace) -> int:
    project = Path(args.repo).resolve()
    run_root, notes = find_baseline(project)
    if run_root is None:
        print(f"no baseline for {project}")
        for note in notes:
            print(f"  rejected {note}")
        return 1

    rounds = round_dirs(run_root)
    last = rounds[-1]
    meta = read_meta(last)
    findings = load_findings(last)
    print(f"baseline:  {run_root}")
    print(f"  round:   {last.name}")
    print(f"  sha:     {meta.get('target_sha')}")
    print(f"  scope:   {meta.get('mode')}")
    print(f"  findings:{len(findings)}")
    return 0


def _cmd_changed(args: argparse.Namespace) -> int:
    project = Path(args.repo).resolve()
    run_root, notes = find_baseline(project)
    if run_root is None:
        print(f"no baseline for {project}")
        for note in notes:
            print(f"  rejected {note}")
        return 1

    last = round_dirs(run_root)[-1]
    since = read_meta(last).get("target_sha")
    # `find_baseline` only returns a run that passed `is_baseline`, which requires a
    # recorded `target_sha` — so this holds. Stated as an assert because the type
    # checker cannot see across the two functions: without it mypy and pyright both
    # report `Any | None` here. If `find_baseline` ever stops requiring the sha, this
    # fires at the invariant instead of a confusing subscript error downstream.
    assert since, f"baseline {last.name} has no target_sha; find_baseline should reject it"
    changed = changed_files(project, since)
    print(f"since {since[:12]}: {len(changed)} file(s) changed")
    for path in changed:
        print(f"  {path}")

    carried, dropped = carry(load_findings(last), changed)
    print(f"\ncarried {len(carried)}, dropped {len(dropped)}")
    for finding in dropped:
        loc = (finding.get("location") or {}).get("path")
        print(f"  drop [{finding['_drop']}] {loc}: {finding['_why']}")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--repo", required=True, help="the project to inspect")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="report the baseline and why it qualifies")
    sub.add_parser("changed", help="list what changed and what it invalidates")
    args = parser.parse_args(argv)
    return _cmd_status(args) if args.cmd == "status" else _cmd_changed(args)


if __name__ == "__main__":
    # Not a program: reached through `council <verb>`. See council.py.
    from council import require_dispatch

    require_dispatch("baseline")
    sys.exit(main())
