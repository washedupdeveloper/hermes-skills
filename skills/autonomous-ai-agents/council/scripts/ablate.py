#!/usr/bin/env python3
"""Measure whether five isolated specialists beat one generalist at equal cost.

The pre-registered rule: the specialists must find 1.5x the distinct true
defects of the best single-agent arm at equal cost, or the council collapses
to one reviewer. Method and result: docs/MILESTONES.md M8.5.
"""
from __future__ import annotations

import argparse
import difflib
import importlib.util as _shared_util
import json
import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from council_loop import (  # noqa: E402  (path shim must run first)
    DIMENSION_SPEC,
    DIMENSIONS,
    git_sha,
    hermes_bin,
    run_hermes,
    run_probes,
)

# `_shared` by path, like every sibling here -- see its own docstring for why a
# plain import would not be safe.
_SHARED_SPEC = _shared_util.spec_from_file_location(
    "_shared", Path(__file__).resolve().parent / "_shared.py")
assert _SHARED_SPEC is not None and _SHARED_SPEC.loader is not None, "_shared.py"
_shared = _shared_util.module_from_spec(_SHARED_SPEC)
_SHARED_SPEC.loader.exec_module(_shared)

GENERALIST = "council-generalist"
GENERALIST_BARE = "council-generalist-bare"
RUBRICS: Tuple[str, ...] = tuple(DIMENSION_SPEC[d]["rubric"] for d in DIMENSIONS)

#: The rule, fixed in advance. Changing this after a run invalidates the run.
MARGIN = 1.5

ARMS: Dict[str, Dict[str, Any]] = {
    "single":             {"profile": GENERALIST,      "rubrics": True,  "samples": 1},
    "generalist-rubrics": {"profile": GENERALIST,      "rubrics": True,  "samples": 5},
    "generalist-bare":    {"profile": GENERALIST_BARE, "rubrics": False, "samples": 5},
    "specialists":        {"profile": None,            "rubrics": True,  "samples": 1},
}


def specialist_profile(dimension: str) -> str:
    """The per-dimension reviewer profile the `specialists` arm spawns.

    These profiles are NO LONGER installed. M8.5 ran this arm against
    `generalist-rubrics` at equal cost and it lost (13/22 injected defects against
    22/22), so the profiles and the reviewer mode that spawned them were deleted
    from the framework rather than left as a mode nothing installs.

    The arm stays here because it IS the comparison the pre-registered rule was
    written against. Restoring the profiles from the commit that deleted them
    re-runs it unchanged -- which is the point of keeping the losing arm in the
    experiment rather than only in the prose.
    """
    return f"{dimension}-reviewer"


# Only the `specialists` arm below reads this, so it lives beside that arm.
SPECIALIST_PROMPT = """Load your {rubric_skill} skill and review this change.

Target repository: {repo}
Scope: {scope}
Round: {round}
Pinned revision: {sha}
Your dimension: {dimension}
Detected language stacks: {stacks}

YOUR GOAL THIS ROUND:

  Objective:    {goal_objective}
  Accepts when: {goal_acceptance}
  Focus:        {goal_focus}

Review ONLY the changed set ({scope}). Follow your rubric exactly — it defines what
counts as a finding in your dimension, how to score it, and what evidence is
mandatory. Do not review other dimensions.

DETERMINISTIC TOOLING — this is what makes beta real, do not skip it. These probes
have already run against the repository. Read them before forming a view:

{probe_json}

Each probe reports {{"tool","ran","parsed","signal","findings"}} where signal is a
normalized 0-100 deterministic score. Report every tool you attempted in
`tools_run` with `ran` true/false. A tool that is NOT installed must be
{{"ran": false, "parsed": false}} — that lowers beta honestly. NEVER invent a tool
result, and never mark a tool as run when it was not.

CRITICAL — machine-readable output. Write your result to exactly this path:

  {out_path}

in this shape:

  {{"reviewer": "{profile}", "dimension": "{dimension}", "score": <0-100 int>,
    "rationale": "<one line>", "beta_note": "<what could not run>",
    "tools_run": [{{"name": "<tool>", "cmd": "<cmd>", "ran": <bool>,
                    "parsed": <bool>, "signal": <0-100 or null>}}],
    "findings": [{{"id": "{dim_prefix}-0001", "severity": "critical|high|medium|low|info",
                   "status": "open|accepted|fixed|wontfix|rejected",
                   "location": {{"path": "<p>", "line_range": "<a-b>"}},
                   "claim": "<verbatim-grounded claim>",
                   "falsifiable_check": "<how to verify>"}}],
    "schema_valid": true}}

Use the exact tool names from the probe slice (e.g. "py-compile", not "py_compile")
so beta matches. When done, reply with a short summary; the gate reads the file.
"""

GENERALIST_PROMPT = """You are reviewing a change as ONE generalist reviewer. You are not \
split into specialists: you cover every dimension yourself, in a single pass.

Target repository: {repo}
Scope: {scope}
Pinned revision: {sha}
Detected language stacks: {stacks}

Dimensions you are responsible for: {dimensions}

{rubric_instruction}

Deterministic probe results for this repository. This is the same data every
reviewer is given, so use it as evidence rather than re-deriving it:

{probe_json}

Review ONLY the changed set ({scope}). For every defect, give the file, the line
range, the claim, and a falsifiable check. Do not report a style preference as a
defect. Do not pad: an unreported non-defect costs you nothing, a false positive
costs you precision.

Write ONE JSON file to this exact path: {out_path}

Shape (no prose around it, no code fence):

{{
  "reviewer": "{profile}",
  "findings": [
    {{
      "id": "{prefix}-0001",
      "dimension": "security|correctness|readability|architecture|performance",
      "severity": "info|low|medium|high|critical",
      "status": "open",
      "location": {{"path": "relative/path", "line_range": "12"}},
      "claim": "what is wrong, and why it matters",
      "falsifiable_check": "the command or observation that would settle it"
    }}
  ],
  "tools_run": [
    {{"cmd": "the command you actually ran", "ran": true, "parsed": true}}
  ]
}}

If you find nothing in a dimension, report nothing for it. An empty findings
list is a legitimate answer.

`tools_run` lists the deterministic tools you actually invoked -- `parsed` false
if one ran but you could not read its output. Report what you ran, not what you
would have run.
"""

RUBRIC_INSTRUCTION = """Load and apply these five skills - one per dimension. Each defines what
counts as a finding in its dimension, how to score it, and what evidence is
mandatory: {rubrics}."""

NO_RUBRIC_INSTRUCTION = """No dimension rubric is provided. Apply your own judgement about what
counts as a defect in each dimension, and say so when you are unsure."""

#: Appended to EVERY arm, so no arm is told to work differently. Without it an arm
#: re-derives the probes with a hundred tool calls: hours, measuring patience.
TOOL_BUDGET = """
Work from the repository itself. The probe results above are already computed --
do not re-run them. Read the files you need, reason about them, and write your
output file. A handful of file reads is expected; driving the toolchain again is
not, and a long exploration is not a better review.
"""


# --- findings ---------------------------------------------------------------

def _norm_path(value: Any) -> str:
    """A repo-relative path in ONE canonical form: forward slashes, no `./`.

    Windows and POSIX disagree about the separator, and this scorer compares paths
    for EQUALITY in three places -- finding fingerprints, truth matching, and the
    dedup that decides how many distinct findings an arm produced.

    The two sides come from different producers. Truth is built with
    `Path.relative_to`, which is platform-dependent (backslash-separated on Windows);
    findings come from the reviewer's JSON, whose documented shape is
    `"relative/path"` (forward slashes). Compared raw, on Windows EVERY finding
    failed the path check in `_distance`, so recall was 0 and every finding counted
    as a false positive -- silently, for every arm, on the platform this framework
    claims to support.

    Normalising BOTH sides is the fix rather than only making the truth canonical,
    because a reviewer handed a Windows checkout may well echo back backslashes. A
    path comparison that only works when both producers happen to agree on a
    separator is not a comparison, it is a coincidence.

    Note this is stricter than the `.lstrip("./")` it replaces, which stripped any
    leading run of `.` and `/` characters and so would have mangled a path like
    `...`. Repo-relative paths do not begin with those, so nothing observable moves.
    """
    return _shared.norm_path(value)


def _fingerprint(finding: Dict[str, Any]) -> str:
    """A stable identity for a finding, so the same defect from two arms matches.

    Deliberately coarse: the claim text is normalised hard, because two arms
    describing the same defect will not phrase it identically.
    """
    return _shared.fingerprint(finding)


def _lines_of(line_range: Any) -> Tuple[int, int]:
    """'12' -> (12, 12); '12-18' -> (12, 18); junk -> (0, 0)."""
    text = str(line_range or "")
    nums = [int(n) for n in re.findall(r"\d+", text)]
    if not nums:
        return (0, 0)
    return (min(nums), max(nums))


def read_findings(path: Path) -> List[Dict[str, Any]]:
    """Read one arm's output. Tolerates a code fence or leading prose."""
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    try:
        doc = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return []
        try:
            doc = json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            return []
    found = doc.get("findings") if isinstance(doc, dict) else None
    return [f for f in (found or []) if isinstance(f, dict)]


def collect(arm_dir: Path) -> Dict[str, Any]:
    """Every finding the arm produced, deduped across its samples."""
    raw: List[Dict[str, Any]] = []
    for f in sorted(arm_dir.glob("findings*.json")):
        raw.extend(read_findings(f))
    seen: Dict[str, Dict[str, Any]] = {}
    for finding in raw:
        seen.setdefault(_fingerprint(finding), finding)
    return {"total": len(raw), "distinct": len(seen), "findings": list(seen.values())}


# --- arms -------------------------------------------------------------------

def _generalist_prompt(repo: Path, scope: str, sha: str, stacks: List[str],
                       probe_json: str, out_path: Path, with_rubrics: bool,
                       sample: int) -> str:
    return GENERALIST_PROMPT.format(
        repo=repo, scope=scope, sha=sha,
        stacks=", ".join(stacks) or "none detected",
        dimensions=", ".join(DIMENSIONS),
        rubric_instruction=(RUBRIC_INSTRUCTION.format(rubrics=", ".join(RUBRICS))
                            if with_rubrics else NO_RUBRIC_INSTRUCTION),
        probe_json=probe_json,
        out_path=out_path,
        profile=GENERALIST if with_rubrics else GENERALIST_BARE,
        prefix="GEN",
    ) + TOOL_BUDGET


def run_arm(arm: str, repo: Path, out_dir: Path, scope: str, sha: str,
            stacks: List[str], probe_json: str, slice_json: str,
            binary: str, timeout: int, log: Path) -> Dict[str, Any]:
    """Run one arm. `specialists` spawns five profiles (see specialist_profile);
    the rest sample one."""
    spec = ARMS[arm]
    arm_dir = out_dir / arm
    arm_dir.mkdir(parents=True, exist_ok=True)

    if arm == "specialists":
        def one(dimension: str) -> Tuple[str, int]:
            dspec = DIMENSION_SPEC[dimension]
            profile = specialist_profile(dimension)
            out_path = arm_dir / f"findings-{dimension}.json"
            prompt = SPECIALIST_PROMPT.format(
                rubric_skill=dspec["rubric"], repo=repo, scope=scope, round=1,
                sha=sha, dimension=dimension, dim_prefix=dspec["prefix"],
                profile=profile, stacks=", ".join(stacks) or "none detected",
                probe_json=slice_json, out_path=out_path,
                goal_objective="find every real defect in your dimension",
                goal_acceptance="every finding is evidence-backed and falsifiable",
                goal_focus="wherever your rubric points",
            ) + TOOL_BUDGET
            rc, _ = run_hermes(binary, repo, prompt, timeout, log, profile=profile)
            if rc == 0 and not out_path.exists():
                rc, _ = run_hermes(binary, repo, prompt, timeout, log, profile=profile)
            return dimension, rc

        with ThreadPoolExecutor(max_workers=len(DIMENSIONS)) as pool:
            codes = dict(pool.map(one, DIMENSIONS))
        return {"arm": arm, "exit_codes": codes,
                "failed": sorted(d for d, rc in codes.items() if rc != 0)}

    def sample(i: int) -> Tuple[int, int]:
        out_path = arm_dir / f"findings-{i}.json"
        prompt = _generalist_prompt(repo, scope, sha, stacks, probe_json,
                                    out_path, spec["rubrics"], i)
        rc, _ = run_hermes(binary, repo, prompt, timeout, log, profile=spec["profile"])
        # Exit 0 with no file silently understates recall -- the number the rule compares.
        if rc == 0 and not out_path.exists():
            rc, _ = run_hermes(binary, repo, prompt, timeout, log, profile=spec["profile"])
        return i, rc

    with ThreadPoolExecutor(max_workers=spec["samples"]) as pool:
        # Not `codes`: one function scope, and mypy then typed this from the earlier
        # dict[str, int].
        sample_codes: Dict[int, int] = dict(pool.map(sample, range(1, spec["samples"] + 1)))
    return {"arm": arm, "exit_codes": {str(k): v for k, v in sample_codes.items()},
            "failed": sorted(i for i, rc in sample_codes.items() if rc != 0)}


# --- ground truth -----------------------------------------------------------

def planted_defects(rung0: Path, rungN: Path) -> List[Dict[str, Any]]:
    """Recover the ladder's planted defects by diffing the rungs.

    The ladder plants defects deterministically from a seed, so the difference
    between the clean rung and rung N IS the ground truth - no manifest needed.
    """
    planted: List[Dict[str, Any]] = []
    for path in sorted(rungN.rglob("*")):
        if not path.is_file() or ".git" in path.parts or "__pycache__" in path.parts:
            continue
        rel = path.relative_to(rungN)
        base = rung0 / rel
        # as_posix(), not str(): str() emits `src\\keep.py` on Windows, matching nothing.
        rel_text = rel.as_posix()
        if not base.exists():
            planted.append({"path": rel_text, "line_range": "1", "kind": "new-file"})
            continue
        try:
            a = base.read_text(encoding="utf-8", errors="replace").splitlines()
            b = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        if a == b:
            continue
        changed: List[int] = []
        for tag, i1, i2, _j1, _j2 in difflib.SequenceMatcher(None, a, b).get_opcodes():
            if tag != "equal":
                changed.extend(range(i1 + 1, max(i2, i1 + 1) + 1))
        if changed:
            planted.append({"path": rel_text,
                            "line_range": f"{min(changed)}-{max(changed)}",
                            "kind": "changed", "lines": sorted(set(changed))})
    return planted


def matches(finding: Dict[str, Any], truth: Dict[str, Any], slack: int = 3) -> bool:
    """Does a finding point at a known-true defect?"""
    loc = finding.get("location") or {}
    fp = str(loc.get("path") or "").strip().lstrip("./")
    tp = str(truth.get("path") or "").strip().lstrip("./")
    if fp != tp:
        return False
    if truth.get("kind") == "new-file":
        return True
    f1, f2 = _lines_of(loc.get("line_range"))
    t1, t2 = _lines_of(truth.get("line_range"))
    if f1 == 0 or t1 == 0:
        return True  # path matched but no usable line: give the benefit of the doubt
    return not (f2 + slack < t1 or f1 - slack > t2)


def _distance(finding: Dict[str, Any], truth: Dict[str, Any], slack: int) -> Optional[int]:
    """Line distance from a finding to a truth entry, or None if out of range.

    0 means the ranges overlap or the entry names a whole file. A path mismatch is
    always None: without this check a finding matched a defect in a DIFFERENT file
    whenever the line numbers happened to be close, which made every false positive
    disappear and every arm look precise.
    """
    loc = finding.get("location") or {}
    fp = _norm_path(loc.get("path"))
    tp = _norm_path(truth.get("path"))
    if fp != tp:
        return None
    f1, f2 = _lines_of(loc.get("line_range"))
    if truth.get("kind") == "new-file":
        return 0
    t1, t2 = _lines_of(truth.get("line_range"))
    if f1 == 0 or t1 == 0:
        return 0
    if f2 < t1:
        gap = t1 - f2
    elif f1 > t2:
        gap = f1 - t2
    else:
        return 0
    return gap if gap <= slack else None


def assign(finding: Dict[str, Any], truth: List[Dict[str, Any]],
           slack: int = 3) -> Optional[int]:
    """The truth entry this finding BEST describes, or None if it describes none.

    Nearest match, not first match. Two injected defects can sit within the slack
    window of each other (a setting and the commented-out block three lines below
    it, say), and first-match attribution silently credits whichever happens to
    come first in the manifest -- which both double-counts one defect and
    under-counts the other.
    """
    loc = finding.get("location") or {}
    fp = str(loc.get("path") or "").strip().lstrip("./")
    best: Optional[int] = None
    best_dist: Optional[int] = None
    for idx, entry in enumerate(truth):
        tp = str(entry.get("path") or "").strip().lstrip("./")
        if fp != tp:
            continue
        dist = _distance(finding, entry, slack)
        if dist is None:
            continue
        if best_dist is None or dist < best_dist:
            best, best_dist = idx, dist
    return best


def found_by(collected: Dict[str, Any], truth: List[Dict[str, Any]],
             slack: int = 3) -> set:
    """Which truth entries ANY finding points at.

    Non-exclusive on purpose. Exclusive nearest-match looked tidier and was wrong:
    when two defects sit on adjacent lines, one finding covering both was credited
    to whichever the manifest listed first, and the other read as *missed* even
    though the arm had reported it. Recall asks "did any finding point here", which
    is a question about the defect, not about resolving ownership between findings.
    """
    hit: set = set()
    for finding in collected["findings"]:
        for idx, entry in enumerate(truth):
            if _distance(finding, entry, slack) is not None:
                hit.add(idx)
    return hit


def is_true(finding: Dict[str, Any], truth: List[Dict[str, Any]],
            slack: int = 3) -> bool:
    """Does a finding point at any known defect? Non-exclusive, for symmetry with
    `found_by`: precision asks whether the finding describes something real."""
    return any(_distance(finding, entry, slack) is not None for entry in truth)


def score_arm(collected: Dict[str, Any], truth: Optional[List[Dict[str, Any]]],
              known_good: bool) -> Dict[str, Any]:
    """Recall against truth, false positives, and the signal-quality pair.

    On the clean rung every finding is a false positive by construction. Where
    truth exists, an unmatched finding is a false positive.

    **Recall alone rewards volume.** An arm that reports more findings raises its
    chance of covering a defect while burying it in noise, and the research is
    explicit that this is a trust hazard: CR-Bench measured the trade directly —
    a Reflexion agent lifted recall 27.01% -> 32.76% while SNR fell 5.11 -> 1.95
    (`research/sota-multi-agent-code-review.md` §3.6). So the pair is reported
    beside recall: `snr` is signal/noise **over findings**, and `usefulness_rate`
    is the share of findings that describe something real.

    `snr` is None when there is no noise at all. That is the best case, not an
    unknown: read `signal` and `noise` together to tell them apart, since a
    genuinely unknown value has both set to None.

    Both are **floors**, for the reason the record already gives about false
    positives: the matcher is location-based, so a finding that is true but
    points somewhere the manifest does not name counts as noise. CR-Bench's
    second signal class — a *valid suggestion* that is not a bug — has no
    representation in a planted-defect manifest, so it lands in noise too. Read
    them as a lower bound on quality, never as the whole picture.
    """
    findings = collected["findings"]
    distinct = collected["distinct"]
    if known_good:
        # Nothing is planted, so every finding is noise by construction.
        return {"distinct": distinct, "true": 0,
                "false_positives": distinct, "recall": None,
                "signal": 0, "noise": distinct, "snr": 0.0,
                "usefulness_rate": 0.0}
    if truth is None:
        return {"distinct": distinct, "true": None,
                "false_positives": None, "recall": None,
                "signal": None, "noise": None, "snr": None,
                "usefulness_rate": None}

    hit_truth = found_by(collected, truth)
    tp_findings = sum(1 for f in findings if is_true(f, truth))
    noise = distinct - tp_findings
    return {
        "distinct": distinct,
        # `true` counts DISTINCT planted defects, not matching findings: an arm that
        # describes one defect three ways must not out-score one that says it once.
        # `true_findings` keeps the raw count for the record.
        "true": len(hit_truth),
        "true_findings": tp_findings,
        "false_positives": noise,
        "recall": round(len(hit_truth) / len(truth), 4) if truth else None,
        "found_of_planted": f"{len(hit_truth)}/{len(truth)}",
        "signal": tp_findings,
        "noise": noise,
        "snr": round(tp_findings / noise, 4) if noise else None,
        "usefulness_rate": round(tp_findings / distinct, 4) if distinct else None,
    }


# --- commands ---------------------------------------------------------------

def cmd_profiles(repo: Path, _args: argparse.Namespace) -> int:
    """Create the two generalist profiles. Idempotent, machine-agnostic."""
    binary = hermes_bin() or "hermes"
    home = Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))
    profiles = home / "profiles"

    library = subprocess.run([binary, "config", "get", "skills.external_dirs", "--json"],
                             capture_output=True, text=True).stdout.strip() or "[]"

    for name, with_rubrics in ((GENERALIST, True), (GENERALIST_BARE, False)):
        target = profiles / name
        if not target.exists():
            subprocess.run([binary, "profile", "create", name, "--clone",
                            "--no-alias", "--description",
                            f"Ablation control arm ({'with' if with_rubrics else 'without'}"
                            " dimension rubrics)"],
                           capture_output=True, text=True, check=False)
        if library and library != "[]":
            subprocess.run([binary, "config", "set", "skills.external_dirs", library],
                           capture_output=True, text=True, check=False,
                           env={**os.environ, "HERMES_HOME": str(target)})
        if with_rubrics:
            for rubric in RUBRICS:
                src = repo / "skills" / rubric / "SKILL.md"
                dst = target / "skills" / rubric / "SKILL.md"
                if src.exists():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
        else:
            for rubric in RUBRICS:
                stale = target / "skills" / rubric
                if stale.exists():
                    shutil.rmtree(stale)
        print(f"  {name:24s} rubrics={'yes' if with_rubrics else 'no ':3s} "
              f"-> {target}")
    print("  library mount:", library)
    return 0


def cmd_truth(_repo: Optional[Path], args: argparse.Namespace) -> int:
    rung0, rungN = Path(args.rung0), Path(args.rungN)
    truth = planted_defects(rung0, rungN)
    out = Path(args.out) if args.out else rungN.parent / "truth.json"
    out.write_text(json.dumps(truth, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"  planted defects: {len(truth)}")
    for t in truth:
        print(f"    {t['path']}:{t['line_range']}  ({t['kind']})")
    print(f"  written: {out}")
    return 0


def cmd_run(_repo: Optional[Path], args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    binary = hermes_bin()
    if not binary:
        print("ablate: `hermes` not found on PATH", file=sys.stderr)
        return 2

    out_dir = Path(args.out).resolve() if args.out else repo / ".review-council" / (
        time.strftime("%Y%m%d-%H%M%S") + "-ablation")
    out_dir.mkdir(parents=True, exist_ok=True)
    log = out_dir / "ablation.log"

    stacks = args.stacks.split(",") if args.stacks else []
    sha = git_sha(repo)
    print(f"  repo:  {repo}\n  sha:   {sha}\n  out:   {out_dir}\n  arms:  {', '.join(args.arms)}")

    print("  running probes (once, shared by every arm)…")
    probes = run_probes(repo, timeout=args.probe_timeout)
    probe_json = json.dumps(probes, indent=2)
    slice_json = json.dumps(probes, indent=2)
    print(f"  probes: {len(probes)}")

    started = time.time()
    report: Dict[str, Any] = {"repo": str(repo), "sha": sha, "scope": args.scope,
                              "stacks": stacks, "arms": {}}
    for arm in args.arms:
        t0 = time.time()
        print(f"  --- {arm}")
        result = run_arm(arm, repo, out_dir, args.scope, sha, stacks, probe_json,
                         slice_json, binary, args.timeout, log)
        collected = collect(out_dir / arm)
        result.update(collected)

        # Count missing files: recall is the number the rule compares.
        expected = len(DIMENSIONS) if arm == "specialists" else ARMS[arm]["samples"]
        produced = len(list((out_dir / arm).glob("findings*.json")))
        result["samples_expected"] = expected
        result["samples_produced"] = produced
        if produced < expected:
            print(f"      WARNING: only {produced}/{expected} samples wrote a findings "
                  f"file — this arm's recall is understated")

        result["seconds"] = round(time.time() - t0, 1)
        report["arms"][arm] = result
        flag = f"  FAILED: {result['failed']}" if result["failed"] else ""
        print(f"      {collected['distinct']} distinct findings "
              f"({collected['total']} raw) in {result['seconds']}s{flag}")

    report["seconds"] = round(time.time() - started, 1)
    (out_dir / "ablation.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")

    # Always emit it: without the operator's verdicts there is no precision number.
    labels = write_labels(out_dir, report, blind=True)
    print(f"  labelling sheet -> {labels}")
    print(f"\n  done in {report['seconds']}s -> {out_dir / 'ablation.json'}")
    return 0


def cmd_score(_repo: Optional[Path], args: argparse.Namespace) -> int:
    run_dir = Path(args.run)
    report = json.loads((run_dir / "ablation.json").read_text(encoding="utf-8"))
    truth: Optional[List[Dict[str, Any]]] = None
    known_good = args.known_good
    if args.truth:
        truth = json.loads(Path(args.truth).read_text(encoding="utf-8"))

    scored: Dict[str, Dict[str, Any]] = {}
    for arm, result in report["arms"].items():
        collected = collect(run_dir / arm)
        scored[arm] = score_arm(collected, truth, known_good)

    print(f"  {'arm':22s} {'distinct':>8s} {'true':>6s} {'FP':>5s} {'recall':>8s}"
          f" {'SNR':>7s} {'useful':>7s}")
    for arm, s in scored.items():
        print(f"  {arm:22s} {s['distinct']:>8d} "
              f"{str(s['true'] if s['true'] is not None else '-'):>6s} "
              f"{str(s['false_positives'] if s['false_positives'] is not None else '-'):>5s} "
              f"{str(s['recall'] if s['recall'] is not None else '-'):>8s} "
              f"{str(s.get('snr') if s.get('snr') is not None else '-'):>7s} "
              f"{str(s.get('usefulness_rate') if s.get('usefulness_rate') is not None else '-'):>7s}")
    # Recall can be bought by volume, so SNR prints beside it: same recall at a
    # lower SNR is not the same result.
    print("  ('-' in SNR means no noise at all -- the best case, not an unknown)")

    # The rule: only arms at equal cost are comparable.
    equal_cost = [a for a in ("generalist-rubrics", "specialists") if a in scored]
    verdict = "UNDECIDED - need both equal-cost arms"
    if len(equal_cost) == 2 and scored["specialists"]["true"] is not None:
        best_single = scored["generalist-rubrics"]["true"]
        five = scored["specialists"]["true"]
        if best_single == 0 and five == 0:
            # Neither side found anything true: the corpus does not discriminate, so
            # this decides nothing.
            verdict = ("UNDECIDED - neither arm found a true defect; the corpus "
                       "does not discriminate and this run decides nothing")
        elif best_single == 0:
            verdict = (f"KEEP the five specialists: {five} vs 0 true "
                       f"(the single-agent arm found none at all)")
        else:
            ratio = five / best_single
            verdict = (f"KEEP the five specialists: {five} vs {best_single} true "
                       f"({ratio:.2f}x, rule needs >={MARGIN}x)"
                       if ratio >= MARGIN else
                       f"COLLAPSE to one reviewer: {five} vs {best_single} true "
                       f"({ratio:.2f}x, rule needs >={MARGIN}x)")
    print(f"\n  RULE: {verdict}")
    (run_dir / "scores.json").write_text(
        json.dumps({"scored": scored, "verdict": verdict, "margin": MARGIN},
                   indent=2) + "\n", encoding="utf-8", newline="\n")
    return 0


def write_labels(run_dir: Path, report: Dict[str, Any], blind: bool = True) -> Path:
    """Write the operator's labelling sheet for a run.

    Precision cannot be computed without knowing which findings are true, and on a
    real repository only the operator can say. This writes one row per distinct
    finding with a blank verdict column.

    Blind by default: naming the arm that produced each finding biases the labeller
    toward whatever the five specialists reported, which is the very comparison the
    labels exist to settle. Provenance stays in ablation.json.
    """
    union: Dict[str, Dict[str, Any]] = {}
    for arm in report["arms"]:
        for finding in collect(run_dir / arm)["findings"]:
            entry = union.setdefault(_fingerprint(finding),
                                     {"finding": finding, "arms": []})
            entry["arms"].append(arm)

    def cell(text: Any, width: int = 0) -> str:
        cleaned = str(text or "").replace("|", "\\|").replace("\n", " ")
        return cleaned[:width] if width else cleaned

    header = ("| # | location | severity | claim | verdict |" if blind else
              "| # | arms that found it | location | severity | claim | verdict |")
    rule = "|---|---|---|---|---|" if blind else "|---|---|---|---|---|---|"

    lines = [
        f"# Labelling sheet — {run_dir.name}",
        "",
        f"Target: `{report['repo']}` at `{report['sha']}`  ",
        f"Distinct findings across every arm: **{len(union)}**",
        "",
        "Mark each finding `true` (a real defect), `false` (not a defect) or `?`.",
        "The verdict column is the only thing to fill in.",
    ]
    if blind:
        lines += [
            "",
            "**Blind**: which arm produced each finding is deliberately withheld, so a",
            "finding is judged on its merits rather than on who reported it. Provenance",
            "is recorded in `ablation.json` and recovered at scoring time.",
        ]
    lines += ["", header, rule]

    for i, entry in enumerate(union.values(), 1):
        finding = entry["finding"]
        loc = finding.get("location") or {}
        where = f"`{cell(loc.get('path'))}:{cell(loc.get('line_range'))}`"
        body = (f"| {i} | {where} "
                f"| {cell(finding.get('severity'))} | {cell(finding.get('claim'), 220)} |  |")
        if not blind:
            body = (f"| {i} | {', '.join(sorted(set(entry['arms'])))} " + body[2:])
        lines.append(body)
    if not blind:
        lines += ["", "## Per-arm totals", "", "| arm | distinct findings |", "|---|---|"]
        for arm in report["arms"]:
            lines.append(f"| {arm} | {collect(run_dir / arm)['distinct']} |")

    out = run_dir / "LABELS.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return out


def cmd_label(_repo: Optional[Path], args: argparse.Namespace) -> int:
    run_dir = Path(args.run)
    report = json.loads((run_dir / "ablation.json").read_text(encoding="utf-8"))
    out = write_labels(run_dir, report, blind=getattr(args, "blind", False))
    n = sum(len(collect(run_dir / a)["findings"]) for a in report["arms"])
    print(f"  {n} raw / {out.stat().st_size} bytes -> {out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ablate.py",
                                     description=(__doc__ or "").splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("profiles", help="create the two generalist profiles")
    p.add_argument("--repo", default=str(Path(__file__).resolve().parent.parent))
    p.set_defaults(func=cmd_profiles)

    p = sub.add_parser("run", help="execute every arm against a repository")
    p.add_argument("repo")
    p.add_argument("--out", default=None)
    p.add_argument("--arms", default=",".join(ARMS))
    p.add_argument("--scope", default="whole-repo")
    p.add_argument("--stacks", default="")
    p.add_argument("--timeout", type=int, default=900)
    p.add_argument("--probe-timeout", type=int, default=900)
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("truth", help="recover planted defects by diffing ladder rungs")
    p.add_argument("--rung0", required=True)
    p.add_argument("--rungN", required=True)
    p.add_argument("--out", default=None)
    p.set_defaults(func=cmd_truth)

    p = sub.add_parser("score", help="score a run directory against truth")
    p.add_argument("--run", required=True)
    p.add_argument("--truth", default=None)
    p.add_argument("--known-good", action="store_true",
                   help="every finding is a false positive (the clean rung)")
    p.set_defaults(func=cmd_score)

    p = sub.add_parser("label", help="write the operator's labelling sheet for a run")
    p.add_argument("--run", required=True)
    p.add_argument("--blind", action="store_true",
                   help="withhold which arm produced each finding, so the labels are "
                        "independent of who reported it")
    p.set_defaults(func=cmd_label)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "run":
        args.arms = [a.strip() for a in args.arms.split(",") if a.strip()]
        unknown = [a for a in args.arms if a not in ARMS]
        if unknown:
            print(f"ablate: unknown arm(s) {unknown}; known: {list(ARMS)}",
                  file=sys.stderr)
            return 2
    return args.func(Path(args.repo) if getattr(args, "repo", None) else None, args)


if __name__ == "__main__":
    # Not a program: reached through `council <verb>`. See council.py.
    from council import require_dispatch

    require_dispatch("ablate")
    raise SystemExit(main())
