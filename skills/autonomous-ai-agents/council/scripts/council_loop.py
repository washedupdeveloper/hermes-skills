#!/usr/bin/env python3
"""Drive a review to termination: fan out, validate, score, gate, fix, re-review.

Autonomy modes: full (apply fixes), semi (ask first), advisory (report only).
Exit codes: 0 satisfied, 1 escalated, 2 error. See docs/FRAMEWORK.md.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
GATE = HERE / "score_reviews.py"
BASELINE = HERE / "baseline.py"

# One entry per dimension: the rubric skill and the finding-id prefix. ONE table, because
# the two are always read together and parallel dicts drift. No `profile` field: five
# specialist profiles lost to one generalist (13/22 vs 22/22, M8.5), which loads all five.
DIMENSION_SPEC: Dict[str, Dict[str, str]] = {
    "security": {"rubric": "reviewer-security", "prefix": "SEC"},
    "correctness": {"rubric": "reviewer-correctness", "prefix": "COR"},
    "readability": {"rubric": "reviewer-readability", "prefix": "RD"},
    "architecture": {"rubric": "reviewer-architecture", "prefix": "ARC"},
    "performance": {"rubric": "reviewer-performance", "prefix": "PERF"},
}
DIMENSIONS: List[str] = list(DIMENSION_SPEC)

ORCHESTRATOR_PROFILE = "council-orchestrator"

# The built-in goal per dimension, the fail-open fallback when the orchestrator cannot
# set one. Deliberately QUALITATIVE: a goal naming a score invites gaming, and the
# threshold is held out of every child's context (§9, anti-gaming).
DEFAULT_GOALS: Dict[str, Dict[str, str]] = {
    "security": {
        "objective": "No new secret, credential, injection surface or unsafe default "
                     "in the reviewed scope.",
        "acceptance": "No open high/critical security finding, and the secret-scanning "
                      "probe is clean.",
    },
    "correctness": {
        "objective": "The change evaluates and behaves as intended, with no broken "
                     "invariant, dead branch or wrong default.",
        "acceptance": "No open high/critical correctness finding, and the compile/eval "
                      "probes pass.",
    },
    "readability": {
        "objective": "The change reads as clearly as the code around it, with no dead, "
                     "duplicated or misleading logic.",
        "acceptance": "No open high/critical readability finding, and the formatter and "
                      "dead-code probes are clean.",
    },
    "architecture": {
        "objective": "The change fits the existing structure and neither duplicates nor "
                     "contradicts a decision the repo already made.",
        "acceptance": "No open high/critical architecture finding, and the declared-rules "
                      "probe is satisfied.",
    },
    "performance": {
        "objective": "The change adds no avoidable work to a hot path or to a build or "
                     "evaluation step.",
        "acceptance": "No open high/critical performance finding, and the timing probes "
                      "show no regression.",
    },
}

# --- Prompts ----------------------------------------------------------------
# The HARNESS owns the fan-out: one reviewer per dimension, each in its own profile,
# because `delegate_task` children inherit the PARENT's HERMES_HOME and cannot load a
# rubric installed only there. The threshold stays OUT of every child's context (§9).

AGGREGATE_PROMPT = """Load your review-council-orchestrator skill and aggregate this
round of the council.

Target repository: {repo}
Round: {round}
Run directory: {run_dir}

The five reviewers have ALREADY run — each in its own profile, with its own rubric.
Do NOT fan out, do NOT delegate, and do NOT review the code yourself. The harness
owns the fan-out. Each reviewer wrote its own result into the run directory:

  {run_dir}/security.json
  {run_dir}/correctness.json
  {run_dir}/readability.json
  {run_dir}/architecture.json
  {run_dir}/performance.json

Reviewers that produced a file: {reviewers_ok}
Reviewers that produced NO file (treat as missing, never as clean): {reviewers_failed}

Your job, per your rubric:

1. Validate each file's schema. Record any that is invalid — do not repair it by
   inventing findings.
2. Build the evidence matrix: dedupe findings by path:line + functional claim,
   and mark cells AGREE / DISAGREE / DID_NOT_EXAMINE. Silence is never agreement.
3. Union the VERIFIED facts at full weight. For an AMBIGUOUS fact, record it as
   ambiguous and note which reviewers disagree — a bounded cross-examination round
   is NOT wired yet, so do not claim one ran. (You have no `delegation` toolset:
   the harness is the only thing that spawns agents.)
4. Do NOT compute the aggregate score or the pass/fail. The deterministic gate owns
   both, reading these same files. You do not decide the verdict.

Then reply with the control message your rubric specifies (termination, reason,
iterations, final_scores).

Reply tersely: the control message, plus one line per material disagreement. Do not
narrate what the reviewers said — the reader has their files. Cite finding ids and
`path:line`, never paraphrase a finding back. The `caveman` skill is the voice.
"""

GENERALIST_PROFILE = "council-generalist"

#: The collapsed mode's prompt: one agent, all five rubrics, N samples. M8.5 measured five
#: specialists against this at equal cost and they lost — 22/22 injected defects against
#: 13/22. Findings are reshaped into the per-dimension files the scorer already reads.
GENERALIST_PROMPT = """Load these five skills and review this change as ONE generalist reviewer:
{rubrics}

Target repository: {repo}
Scope: {scope}
Round: {round}
Pinned revision: {sha}
Detected language stacks: {stacks}

YOUR GOAL THIS ROUND — set by the orchestrator. Work THIS, not the dimensions in
the abstract:

  Objective:    {goal_objective}
  Accepts when: {goal_acceptance}
  Focus:        {goal_focus}

The five rubrics define what counts as a finding in each dimension, how to score
it, and what evidence is mandatory. You cover all five yourself, in one pass.
Every finding MUST name the dimension it belongs to — that is how the result is
scored, and a finding with no valid dimension cannot be scored at all.

Review ONLY the changed set ({scope}).
{carry_block}
Deterministic probe results for this repository. This is the same data every
reviewer is given, so use it as evidence rather than re-deriving it. It is SUMMARISED:
findings are ranked by severity and capped per rule, and every entry states
`findings_total` and `omitted_by_rule`, which is how you say "hundreds more of this
kind" without inventing detail. Treat this digest as the probe evidence you were
given: `probes.json` holds the same data unsummarised, so reading it wholesale adds
nothing — open it only to check one finding.

{probe_json}

Write ONE JSON file to exactly this path: {out_path}

Shape (no prose around it, no code fence):

{{
  "reviewer": "{profile}",
  "scores": {{
    "security": 0, "correctness": 0, "readability": 0,
    "architecture": 0, "performance": 0
  }},
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

COMMUNICATION — this file is read by other agents and re-read on every pass. Write
tersely: `claim` is ONE sentence (what is wrong, why it matters), no hedging, no
restating the diff; `falsifiable_check` is the exact command that settles it. Never
drop a negation, path, symbol, number, or rule id — those are the payload. Security
and irreversible findings are the exception: explain those in full.

Replace each score with your 0-100 judgement for that dimension. A dimension in
which you found nothing scores 100. Do not pad the findings list: an unreported
non-defect costs you nothing, a false positive costs you precision.

REPORT WHAT YOU RAN. `tools_run` lists the deterministic tools you actually
invoked — `parsed` false if one ran but you could not read its output. The gate
measures how much of the deterministic half was really exercised, and with an
empty `tools_run` the score collapses to your own judgement alone. So an honest
list is worth more than a short one, and a tool you did not run is worth less
than nothing: it is a claim the gate cannot verify.
"""

GOALS_PROMPT = """Load your review-council-orchestrator skill and set this round's goals.

Target repository: {repo}
Scope: {scope}
Round: {round}
Pinned revision: {sha}
Detected language stacks: {stacks}

The deterministic probes have already run. This is the whole run's summary — it is
ground truth, not a suggestion:

{probe_summary}

Your job is to SET GOALS, one per dimension, that the specialist for that dimension
will then work. A goal is an objective plus the evidence that would show it is met.
Write one for each of: {dimensions}

Rules:
- Concrete and checkable against THIS repository. Point at real locations when the
  probes or the repo suggest them (a path, or path:line).
- Do NOT state a target score, a pass threshold, or anything about how the round
  will be judged. You do not know it, and a goal that names a number invites
  gaming. The deterministic gate owns acceptance.
- A dimension with nothing material to work on gets an honest goal saying so —
  "no material risk found in this scope" is a valid outcome, not a failure to
  produce one.
- Do NOT review the code yourself and do NOT fan out. You set the goals; the
  harness spawns the specialists.

Write to exactly this path:

  {out_path}

in this shape:

  {{"round": {round}, "goals": [
    {{"dimension": "security",
      "objective": "<what must be true when this dimension is done>",
      "acceptance": "<the evidence that would show it>",
      "focus": ["<path or path:line>"]}}
  ]}}

One sentence per field: `objective` states what must be true, `acceptance` names the
evidence that would show it, `focus` lists locations. No preamble, no commentary
around the JSON. The `caveman` skill is the voice.
"""

GOAL_REVIEW_PROMPT = """Load your review-council-orchestrator skill and review this
round against the goals you set.

Target repository: {repo}
Round: {round}
Run directory: {run_dir}

THE GOALS YOU SET FOR THIS ROUND:

{goals_json}

WHAT HAPPENED:

- Reviewer files present: {reviewers_ok}
- Reviewers that produced NO file (a gap, never a clean bill): {reviewers_failed}

- The deterministic gate's verdict. This is AUTHORITATIVE — do not recompute or
  restate a score, and do not contradict it:

{gate_output}

Your job: for EACH goal, judge it MET / PARTIAL / NOT MET, cite the evidence (a
finding id, a reviewer file, a probe result), and name what remains. Where a goal
was not met, say what the next round should target. Where a reviewer produced no
file, that dimension's goal is UNVERIFIED — say so rather than calling it met.

The gate has already decided acceptance. You explain the result; you do not decide
it.

## The handover: an OpenSpec change, written to disk

Your top-level output to the reader is not prose — it is an OpenSpec change, written under the
run directory (a review is a read: write here, never into the target repository):

  {run_dir}/../handover/openspec/changes/<kebab-slug>/
    proposal.md
    specs/<capability>/spec.md
    tasks.md

Follow the `openspec` skill. `openspec instructions proposal|specs|tasks` is the only template
source; the format is not restated here. Concretely:

- **proposal.md** — `## Why` (the verdict, and why the open findings matter), `## What Changes`,
  `## Capabilities` (name the capability you modify or introduce), `## Impact`.
- **specs/<capability>/spec.md** — one `### Requirement:` per CLASS of open finding, not per
  finding and not per file; each carries at least one `#### Scenario:` with `**WHEN**` and
  `**THEN**`. A requirement states observable behaviour plus how it is verified, never "fix
  GEN-0002". If the target repository already has `openspec/specs/`, reuse its capability path
  and write the delta as ADDED or MODIFIED against the requirement text you can read there.
- **tasks.md** — `- [ ] <n>.<m> ...` checkboxes, one commit each, ordered so the blocking
  findings come first, and a final verification task naming the command that settles it.

How to use the templates, exactly:

1. `openspec new change <slug>` in the handover root creates the change directory. If the skill is
   not available, create `proposal.md`, `specs/<capability>/spec.md` and `tasks.md` yourself.
2. Run `openspec instructions <artifact> --change <slug>` and USE the output to fill that artifact.
   Do NOT save the instructions to a file — a `.instructions.txt` in the handover is not a
   handover, and a change directory holding only `.openspec.yaml` is an empty change.
3. Write, in this order: `proposal.md`, then `specs/<capability>/spec.md`, then `tasks.md`.
4. `openspec instructions tasks` warns that `specs` and `design` are missing. That warning is
   expected here: THIS prompt replaces the specs step, and `design.md` is optional — do not write
   one unless the change is cross-cutting. Proceed to write `tasks.md` anyway.
5. The change is not done until all three paths above exist and hold real content. Stop after
   writing them.

Derive the requirements from the gate output above and the reviewer files; do not invent
findings. If the round produced no findings, write the change with one requirement per goal that
was PARTIAL or NOT MET.

Then reply with the control message your rubric specifies.

Reply tersely: per goal, the verdict and the evidence as an id or `path:line`, then one line
naming the change directory you wrote. Do not restate the gate output — the reader has it. The
`caveman` skill is the voice.
"""

FIX_PROMPT = """Continue toward the standing goal: make this repository clear its
own review-council gate.

Target repository: {repo}

The deterministic gate failed. Its output is the concrete evidence to repair
against — fix these, do not argue with them:

--- gate output ---
{gate_output}
--- end gate output ---

PRIORITISED WORK — the minimum score is the requirement; everything above it is
desirable. Work down this list in order:

{next_steps}

Apply the fixes now (autonomy mode: {mode}). After editing, the council will be
re-run at the new revision. Do not weaken or delete tests to pass; fix the
underlying defects. If a finding is wrong, leave the code alone and say why in
your reply.

Fix at the NARROWEST layer that owns each defect. No renaming, reformatting, or
abstraction outside the fix — a drive-by tidy-up makes the diff unreviewable and hides
what closed the finding. Preserve unrelated behavior and the user's uncommitted
changes. Add only the regression proof the finding needs, run it, and stop: the re-run
is the proof, not your summary of it.
"""


# --- Helpers ----------------------------------------------------------------

def find_project_root(start: Path) -> Tuple[Path, str, bool]:
    """Infer the project from a starting directory.

    Walks up from *start* looking for a project marker, and returns
    ``(root, reason, confident)``. ``confident`` is False when no marker was
    found and the fallback is just *start* — the caller should then refuse
    rather than review an arbitrary directory (e.g. a session that is not
    anchored to a project, where cwd is the user's home).

    Marker order matters: a git root is the strongest signal (and is where
    `.hermes.md` discovery stops), then agent context files, then build
    manifests. This mirrors Hermes' own project-context discovery, so the council
    reviews the same tree the session is configured for.
    """
    start = start.resolve()
    # Markers that identify a project root, strongest first.
    markers = (
        (".hermes.md", ".hermes.md project context"),
        ("HERMES.md", "HERMES.md project context"),
        ("AGENTS.md", "AGENTS.md project context"),
        ("agents.md", "agents.md project context"),
        ("CLAUDE.md", "CLAUDE.md project context"),
        ("claude.md", "claude.md project context"),
        ("pyproject.toml", "pyproject.toml"),
        ("package.json", "package.json"),
        ("Cargo.toml", "Cargo.toml"),
        ("go.mod", "go.mod"),
    )
    # Nearest git root wins: that is the boundary Hermes itself uses.
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate, f"git repository root at {candidate}", True
    # No git root: take the nearest directory carrying any other marker.
    for candidate in (start, *start.parents):
        for marker, reason in markers:
            if (candidate / marker).exists():
                return candidate, f"{reason} at {candidate}", True
    return start, f"current directory ({start}) — no project marker found", False


def resolve_project(explicit: Optional[str]) -> Tuple[Path, str, bool]:
    """Resolve the target repo: an explicit path wins, else infer from cwd.

    Returns ``(path, why, confident)``. An explicit path is always confident —
    the user named it, so reviewing a non-repo directory is their call.
    """
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_absolute():
            path = (Path.cwd() / path)
        return path.resolve(), "explicit path", True
    return find_project_root(Path.cwd())


_HERMES_CACHE: Optional[Any] = None


def _hermes_module() -> Any:
    """Import hermes.py ONCE, by path.

    By path, not by name: the tests load this file standalone, where `scripts/`
    is not on sys.path. Same reason _gate_module does it.
    """
    global _HERMES_CACHE
    if _HERMES_CACHE is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("hermes", HERE / "hermes.py")
        assert spec is not None and spec.loader is not None
        _HERMES_CACHE = importlib.util.module_from_spec(spec)
        sys.modules.setdefault("hermes", _HERMES_CACHE)
        spec.loader.exec_module(_HERMES_CACHE)
    return _HERMES_CACHE


def hermes_bin() -> Optional[str]:
    """Locate the hermes launcher cross-platform (DECISIONS #2).

    One implementation, in `hermes.py`, because the search order is a policy: it
    is also what `council doctor` reports, and two copies would drift into
    "doctor finds it and the loop does not", which reads as a flaky agent.
    """
    return _hermes_module().launcher()


def agent_env() -> Dict[str, str]:
    """The environment an agent turn runs under.

    Two deliberate entries:

    * `HERMES_ACCEPT_HOOKS` so a non-interactive run does not stall on hook consent.
    * **No dispatch variable.** The module guard is an environment variable, and an
      agent turn would otherwise inherit it — a reviewer reads untrusted repository
      content, so an agent that ran `python3 scripts/inject_defects.py ...` would
      find the guard inert and the module would execute. The harness runs the probes
      and the gate itself, so nothing in an agent turn needs it.

    This is not a boundary: an agent with a terminal toolset can set the variable
    itself, and no in-repo check can prevent that. It removes the copy the framework
    hands over, which is the part the framework controls.
    """
    env = dict(os.environ)
    env.setdefault("HERMES_ACCEPT_HOOKS", "1")
    env.pop("REVIEW_COUNCIL_DISPATCHED", None)
    return env


def prompt_path_for(log: Path) -> Path:
    """The prompt file for THIS caller — unique per concurrent sample.

    Derived from the log path alone it was SHARED: the samples run in one
    ThreadPoolExecutor and all pass the same `log`, so every sample wrote the same
    `council.prompt` and then spawned a child that read it back. Whichever sample
    wrote last decided the `out_path` embedded in every child's prompt, so all five
    wrote one `generalist-N.json` and the round reviewed a single sample while the
    harness reported five. Scoped by thread because that is the unit of concurrency
    here: sequential calls in one thread may reuse the file, concurrent ones must not.
    """
    return log.parent / f"{log.stem}.{os.getpid()}.{threading.get_ident()}.prompt"


def run_hermes(binary: str, repo: Path, prompt: str, timeout: int, log: Path,
               profile: str = ORCHESTRATOR_PROFILE) -> Tuple[int, str]:
    """One agent turn under *profile*. Streams to *log*, returns (rc, output).

    The profile decides which skills that agent can load, which is exactly why a
    reviewer MUST run under its own profile: its rubric is installed only there.
    """
    # Scoped by cwd, not `--in`: `--in` is Hermes main only and the published wheel
    # (0.19.0) rejects it at argparse, before any agent starts. The container depends on
    # this — Hermes refuses to build from source via pip, so the wheel is all it has.

    # The prompt goes in a FILE: `-q <prompt>` hits MAX_ARG_STRLEN (65536 bytes) and a
    # real repo's probe JSON runs ~400 KB, so the spawn died with `[Errno 7] Argument
    # list too long` / rc=126 on every real repo. `--query-file` has no limit, no shell.
    log.parent.mkdir(parents=True, exist_ok=True)
    prompt_file = prompt_path_for(log)
    prompt_file.write_text(prompt, encoding="utf-8")
    cmd = [binary, "-p", profile, "chat", "--query-file", str(prompt_file)]
    env = agent_env()
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, env=env,
            encoding="utf-8", errors="replace",
            cwd=str(repo),
        )
    except subprocess.TimeoutExpired as exc:
        out = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        with log.open("a", encoding="utf-8") as fh:
            fh.write(out + f"\n[timeout after {timeout}s]\n")
        return 124, out
    except OSError as exc:
        # A spawn can be refused outright: on Windows an Application Control policy blocks
        # CreateProcess with WinError 4551, and letting that propagate aborts the whole
        # ThreadPoolExecutor batch (a 37-minute run reported nothing); rc 126 is a NO FILE gap.
        msg = f"[could not start the reviewer process: {exc}]"
        with log.open("a", encoding="utf-8") as fh:
            fh.write(msg + "\n")
        return 126, msg
    with log.open("a", encoding="utf-8") as fh:
        fh.write(proc.stdout or "")
        if proc.stderr:
            fh.write("\n--- stderr ---\n" + proc.stderr)
    return proc.returncode, (proc.stdout or "")


_GATE_CACHE: Optional[Any] = None


def _gate_module() -> Any:
    """Import score_reviews ONCE and reuse it.

    Re-executing the module on every call is wasteful and, worse, gives the caller
    a *different* module object each time — so a table read here cannot be compared
    Executing it repeatedly also hands the caller a *different* module
    object each time, so a table read here cannot be compared with the
    same table read a moment later.
    """
    global _GATE_CACHE
    if _GATE_CACHE is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("score_reviews", GATE)
        assert spec is not None and spec.loader is not None, GATE
        _GATE_CACHE = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_GATE_CACHE)
    return _GATE_CACHE


_BASELINE_CACHE: Optional[Any] = None


def baseline_mod() -> Any:
    """`scripts/baseline.py`, loaded by path.

    By path rather than by import so it resolves the same way whether the loop
    is run directly or loaded by the tests -- which import this module from
    `tests/`, where `scripts/` is not on sys.path.
    """
    global _BASELINE_CACHE
    if _BASELINE_CACHE is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("baseline", BASELINE)
        assert spec is not None and spec.loader is not None, BASELINE
        _BASELINE_CACHE = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_BASELINE_CACHE)
    return _BASELINE_CACHE


def run_gate(run_dir: Path, threshold: float, tail_chars: int = 3000,
             repo: Optional[Path] = None) -> Tuple[int, str, Dict[str, Any]]:
    """Run the deterministic gate. Returns (rc, continuation_prompt, parsed_json).

    *repo* is passed through so the gate can measure findings DENSITY rather than
    counting them. Without it the gate falls back to the uncalibrated count curve,
    and the same run dir scores differently from the loop than from a manual
    re-run — the loop's number must be the one a re-run reproduces.
    """
    base = [sys.executable, str(GATE), str(run_dir), "--threshold", str(threshold)]
    if repo is not None:
        base += ["--repo", str(repo)]
    proc = subprocess.run(base + ["--tail-chars", str(tail_chars)],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    parsed: Dict[str, Any] = {}
    try:
        jp = subprocess.run(
            base + ["--json"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if jp.stdout.strip():
            parsed = json.loads(jp.stdout)
    except (json.JSONDecodeError, OSError):
        parsed = {}
    return proc.returncode, (proc.stdout or "").strip(), parsed


def count_new_verified(round_dir: Path, previous_ids: set) -> Tuple[int, set]:
    """Novelty signal: how many findings are new this round (§8, k=2)."""
    ids: set = set()
    for dim in DIMENSIONS:
        path = round_dir / f"{dim}.json"
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        for finding in payload.get("findings") or []:
            fid = str(finding.get("id") or "").strip()
            if fid:
                ids.add(fid)
    return len(ids - previous_ids), ids


# --- Convening the review ---------------------------------------------------
# ONE generalist profile sampled `samples` times, bucketed by the dimension each finding
# declares. Five specialist profiles lost to this at equal cost: 13/22 against 22/22 (M8.5).



def git_sha(repo: Path) -> str:
    """The revision under review, for the run's provenance. Never fatal."""
    try:
        out = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                             capture_output=True, text=True, timeout=30)
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def run_probes(repo: Path, timeout: int = 900) -> List[Dict[str, Any]]:
    """Run every built-in probe ONCE and return the results.

    Run here, not by the orchestrator: the probes are deterministic, so running
    them once in the harness removes a class of LLM-mediated variance and lets
    each reviewer be handed exactly its own slice.
    """
    try:
        proc = subprocess.run(
            [sys.executable, str(HERE / "probes.py"), "--all", "--repo", str(repo)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    try:
        data = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def write_meta(run_dir: Path, repo: Path, scope: str, round_no: int,
               stacks: List[str], sha: str,
               extra: Optional[Dict[str, Any]] = None) -> None:
    """meta.json is the harness's to write — it knows the facts, the LLM does not.

    *extra* carries the baseline-relative facts (which baseline, what changed,
    what was carried). They belong here rather than in the reviewer's output for
    the same reason: the harness computed them, and a reviewer asserting them
    would be inventing data.
    """
    meta = {
        "target_sha": sha, "mode": scope, "round": round_no,
        "stacks": stacks, "repo": str(repo),
    }
    meta.update(extra or {})
    (run_dir / "meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8", newline="\n")


def default_goals(round_no: int) -> Dict[str, Any]:
    """The built-in goal set, one per dimension — the fail-open fallback."""
    return {"round": round_no,
            "goals": [{"dimension": d, **DEFAULT_GOALS[d]} for d in DIMENSIONS]}


def read_goals(path: Path, round_no: int) -> Optional[Dict[str, Any]]:
    """Parse a goals file, or None when it is missing, malformed or incomplete.

    A set missing ANY dimension is treated as absent rather than partially
    applied: a half-applied goal set is harder to reason about than the default,
    and the difference would be invisible in the run report.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    goals = data.get("goals")
    if not isinstance(goals, list):
        return None
    by_dim = {g.get("dimension"): g for g in goals if isinstance(g, dict)}
    if any(d not in by_dim for d in DIMENSIONS):
        return None
    return {"round": round_no, "goals": [by_dim[d] for d in DIMENSIONS]}


def goal_for(goals: Dict[str, Any], dimension: str) -> Dict[str, Any]:
    """One dimension's goal, with the built-in default filling any missing field.

    A goal that names an objective but no acceptance criterion is still usable —
    the rubric supplies the standard the reviewer is held to either way.
    """
    merged: Dict[str, Any] = {"dimension": dimension, **DEFAULT_GOALS[dimension]}
    for goal in goals.get("goals") or []:
        if isinstance(goal, dict) and goal.get("dimension") == dimension:
            merged.update({k: v for k, v in goal.items() if v})
            break
    return merged


def probe_summary(probes: List[Dict[str, Any]]) -> str:
    """A compact, tool-per-line view of the probe run, for the goals prompt.

    The per-dimension SLICE goes to the reviewer; the orchestrator needs the whole
    picture to decide where this round's work is.
    """
    lines = []
    for p in probes:
        signal = p.get("signal")
        findings = len(p.get("findings") or [])
        state = "ran" if p.get("ran") else "NOT RUN"
        sig = "n/a" if signal is None else signal
        note = p.get("note") or ""
        lines.append(f"  {p.get('tool')}: {state}, signal {sig}, "
                     f"{findings} finding(s). {note}".rstrip())
    return "\n".join(lines) if lines else "  (no probes ran)"


def set_goals(binary: str, repo: Path, round_dir: Path, scope: str, round_no: int,
              timeout: int, log: Path, probes: List[Dict[str, Any]],
              stacks: List[str], sha: str) -> Dict[str, Any]:
    """Ask the orchestrator to set this round's goals, one per dimension.

    Fail-open by design: a goal-setting failure is not a review failure. An
    unreadable, malformed or partial goal file degrades to the built-in default
    set rather than aborting the round.
    """
    out_path = round_dir / "goals.json"
    rc, _ = run_hermes(
        binary, repo,
        GOALS_PROMPT.format(
            repo=repo, scope=scope, round=round_no, sha=sha,
            stacks=", ".join(stacks) or "none detected",
            dimensions=", ".join(DIMENSIONS),
            probe_summary=probe_summary(probes),
            out_path=out_path,
        ),
        timeout, log,
    )
    goals = read_goals(out_path, round_no)
    if rc != 0 or goals is None:
        print("  goals: the orchestrator set none — using the built-in default set")
        return default_goals(round_no)
    return goals


def review_goals(binary: str, repo: Path, round_dir: Path, round_no: int,
                 goals: Dict[str, Any], timeout: int, log: Path,
                 reviewers_ok: str, reviewers_failed: str,
                 gate_output: str) -> int:
    """The orchestrator's end-of-round review: the goals versus what happened.

    The gate has ALREADY decided acceptance; this explains it. The orchestrator is
    told not to recompute the score, so the verdict lives in exactly one place.
    """
    rc, _ = run_hermes(
        binary, repo,
        GOAL_REVIEW_PROMPT.format(
            repo=repo, round=round_no, run_dir=round_dir,
            goals_json=json.dumps(goals, indent=2),
            reviewers_ok=reviewers_ok or "(none)",
            reviewers_failed=reviewers_failed or "(none)",
            gate_output=gate_output[-3000:],
        ),
        timeout, log,
    )
    return rc


# ── the handover, as an OpenSpec change ──────────────────────────────────────
# The runtime image has no Node, so `openspec validate` cannot run inside a review. The shape is
# therefore checked here, encoding the rules `openspec instructions` states: a proposal with its
# Why and What Changes, at least one requirement per capability with at least one scenario, and
# scenarios that carry WHEN and THEN. The check is deliberately structural — `validate --strict`
# checks shape, not truth, and so does this.
def validate_handover(changes_root: Path) -> Dict[str, Any]:
    """Validate the OpenSpec change the orchestrator wrote. Never raises."""
    result: Dict[str, Any] = {
        "found": False, "path": None, "changes": [], "valid": False, "problems": [],
    }
    if not changes_root.is_dir():
        return result
    # `archive/` is OpenSpec's own bookkeeping, not a change: scaffolding a handover
    # creates it, and treating it as a malformed change fails a correct run.
    changes = sorted(p for p in changes_root.iterdir()
                     if p.is_dir() and p.name != "archive")
    if not changes:
        return result

    result["found"] = True
    result["path"] = str(changes_root)

    for change in changes:
        problems: List[str] = []
        proposal = change / "proposal.md"
        specs = sorted((change / "specs").rglob("spec.md")) if (change / "specs").is_dir() else []
        tasks = change / "tasks.md"

        if not proposal.is_file():
            problems.append("proposal.md missing")
        else:
            text = proposal.read_text(encoding="utf-8", errors="replace")
            for heading in ("## Why", "## What Changes"):
                if heading not in text:
                    problems.append(f"proposal.md: no `{heading}` section")

        if not specs:
            problems.append("no specs/<capability>/spec.md")
        for spec in specs:
            rel = spec.relative_to(change).as_posix()
            text = spec.read_text(encoding="utf-8", errors="replace")
            if not re.search(r"^### Requirement: \S", text, re.M):
                problems.append(f"{rel}: no `### Requirement:` block")
            for block in re.split(r"^### Requirement: ", text, flags=re.M)[1:]:
                name = block.splitlines()[0].strip() or "(unnamed)"
                scenarios = re.split(r"^#### Scenario: ", block, flags=re.M)[1:]
                if not scenarios:
                    problems.append(f"{rel}: requirement '{name}' has no scenario")
                for scenario in scenarios:
                    title = scenario.splitlines()[0].strip() or "(unnamed)"
                    if "**WHEN**" not in scenario or "**THEN**" not in scenario:
                        problems.append(
                            f"{rel}: scenario '{title}' needs both **WHEN** and **THEN**")

        if not tasks.is_file():
            problems.append("tasks.md missing")
        elif not re.search(r"^\s*- \[[ xX]\] \S", tasks.read_text(encoding="utf-8",
                                                          errors="replace"), re.M):
            # Checked or not: a handover that has landed has every task ticked, so
            # requiring an open box would reject archived work as malformed.
            problems.append("tasks.md: no checkbox task")

        result["changes"].append({"name": change.name, "problems": problems})
        result["problems"].extend(f"{change.name}: {p}" for p in problems)

    result["valid"] = all(not c["problems"] for c in result["changes"])
    return result


def read_handover_plan(changes_root: Path) -> Dict[str, Any]:
    """The change as a reader needs it: its name, its requirements, its tasks.

    Shape only — `validate_handover` owns whether the change is well formed, and this only
    renders it. Tasks come back verbatim, because the checkbox list is the plan.
    """
    plan: Dict[str, Any] = {"change": None, "requirements": [], "tasks": []}
    if not changes_root.is_dir():
        return plan
    changes = sorted(p for p in changes_root.iterdir()
                     if p.is_dir() and p.name != "archive")
    if not changes:
        return plan
    change = changes[0]
    plan["change"] = change.name

    specs = sorted((change / "specs").rglob("spec.md")) if (change / "specs").is_dir() else []
    for spec in specs:
        text = spec.read_text(encoding="utf-8", errors="replace")
        for name in re.findall(r"^### Requirement: (.+)$", text, re.M):
            plan["requirements"].append({"capability": spec.parent.name, "name": name.strip()})

    tasks = change / "tasks.md"
    if tasks.is_file():
        plan["tasks"] = [
            line.rstrip() for line in tasks.read_text(encoding="utf-8", errors="replace").splitlines()
            if re.match(r"^\s*- \[[ xX]\] ", line)
        ]
    return plan


def _finding_key(finding: Dict[str, Any]) -> str:
    """Identity for dedupe across samples: location plus normalised claim."""
    loc = finding.get("location") or {}
    path = str(loc.get("path") or "").strip().lstrip("./")
    lines = str(loc.get("line_range") or "").strip()
    claim = " ".join(str(finding.get("claim") or "").lower().split())[:120]
    return f"{path}|{lines}|{claim}"


def read_json_tolerant(path: Path) -> Dict[str, Any]:
    """Read a model-written JSON file, tolerating a code fence or surrounding prose."""
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    try:
        doc = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return {}
        try:
            doc = json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            return {}
    return doc if isinstance(doc, dict) else {}


def _record_merge(run_dir: Path, dropped: int, samples: int) -> None:
    """Persist the merge's own accounting into meta.json.

    `write_meta` runs BEFORE the reviewers, so it cannot know what the merge
    dropped. This is the read-modify-write that adds it afterwards.

    It matters because a baseline has to be complete: `baseline.py` refuses a run
    with a non-zero -- or unrecorded -- dropped count, since a baseline missing
    findings it never reported would carry that hole into every incremental
    review built on it.

    A round directory with no meta.json is left alone. The golden fixtures and
    the merge unit tests use bare temp dirs, and inventing a meta.json for them
    would make the fixtures depend on a file they do not have.
    """
    path = run_dir / "meta.json"
    if not path.exists():
        return
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    meta["dropped"] = dropped
    meta["samples_readable"] = samples
    path.write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8", newline="\n",
    )


def merge_generalist_samples(sample_paths: List[Path], round_dir: Path,
                             probe_results: Optional[List[Dict[str, Any]]] = None
                             ) -> Dict[str, Any]:
    """Bucket a generalist's findings by dimension into the per-dimension files.

    The scorer reads one file per dimension, so the collapsed mode has to regroup
    what one agent produced. Findings are deduped across samples.

    A finding whose `dimension` is missing or unrecognised is DROPPED and counted.
    Guessing a dimension would invent data, and silently attributing a finding to
    the wrong dimension would corrupt the per-dimension score it feeds.

    `tools_run` is UNIONed across samples: a tool counts as run if ANY sample ran
    it. The samples are independent attempts at the same round, so a tool one of
    them exercised was exercised. Dropping the union would force beta to 0 and
    silently reduce the hybrid score to the LLM's own judgement -- the
    deterministic half would be inert, and nothing downstream would say so.

    *probe_results* are the harness's own probes for this round, and they are
    seeded into `tools_run` too. STACK_TOOLS states that builtin names "are
    satisfied by the framework's own probes.py", so a probe that ran IS the tool
    running. Counting only what the reviewer reports would leave beta at 0 for
    every dimension whose expected tools are builtin -- the probe ran, the
    reviewer was handed its result in the prompt, and the gate would score the
    dimension as though nothing had been exercised.
    """
    buckets: Dict[str, Dict[str, Any]] = {
        d: {"findings": {}, "scores": []} for d in DIMENSIONS
    }
    tools: Dict[str, Dict[str, Any]] = {}
    dropped = 0
    samples = 0

    for probe in probe_results or []:
        tool = str(probe.get("tool") or "").strip()
        if not tool:
            continue
        entry = tools.setdefault(tool, {"cmd": tool, "ran": False, "parsed": False})
        entry["ran"] = entry["ran"] or bool(probe.get("ran"))
        entry["parsed"] = entry["parsed"] or bool(probe.get("parsed", True))
    for path in sample_paths:
        doc = read_json_tolerant(path)
        if not doc:
            continue
        samples += 1
        for finding in doc.get("findings") or []:
            if not isinstance(finding, dict):
                continue
            dim = str(finding.get("dimension") or "").strip().lower()
            if dim not in buckets:
                dropped += 1
                continue
            buckets[dim]["findings"].setdefault(_finding_key(finding), finding)
        for dim, value in (doc.get("scores") or {}).items():
            key = str(dim).strip().lower()
            if key in buckets and isinstance(value, (int, float)):
                buckets[key]["scores"].append(float(value))
        for tool in doc.get("tools_run") or []:
            if not isinstance(tool, dict):
                continue
            cmd = str(tool.get("cmd") or tool.get("name") or "").strip()
            if not cmd:
                continue
            entry = tools.setdefault(cmd, {"cmd": cmd, "ran": False, "parsed": False})
            entry["ran"] = entry["ran"] or bool(tool.get("ran"))
            # `parsed` defaults to true in the scorer, so treat a missing flag as
            # parsed rather than silently zeroing the tool's contribution.
            entry["parsed"] = entry["parsed"] or bool(tool.get("parsed", True))

    if samples == 0:
        # Nothing was readable. Five empty dimension files would score as a clean 100 and
        # PASS, so leave them MISSING: the gate treats a missing file as an error (exit 2).
        _record_merge(round_dir, dropped, 0)
        return {"samples": 0, "dropped": dropped, **{d: 0 for d in DIMENSIONS}}

    counts: Dict[str, int] = {}
    for dim, bucket in buckets.items():
        findings = list(bucket["findings"].values())
        scores = bucket["scores"]
        llm = round(sum(scores) / len(scores), 2) if scores else 100.0
        (round_dir / f"{dim}.json").write_text(
            json.dumps({
                "reviewer": GENERALIST_PROFILE,
                "dimension": dim,
                "score": llm,
                "rationale": (f"collapsed mode: {samples} generalist sample(s), "
                              f"{len(findings)} distinct finding(s) in this dimension"),
                "beta_note": (
                    f"union of {samples} sample(s): "
                    f"{sum(1 for t in tools.values() if t['ran'])} tool(s) run, "
                    f"{sum(1 for t in tools.values() if t['ran'] and t['parsed'])} parsed"
                    if tools else ""),
                "tools_run": list(tools.values()),
                "findings": findings,
                "schema_valid": True,
            }, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8", newline="\n")
        counts[dim] = len(findings)
    _record_merge(round_dir, dropped, samples)
    return {"samples": samples, "dropped": dropped, **counts}


def resolve_carry(repo: Path, spec: str, log: Path) -> Optional[Dict[str, Any]]:
    """Turn `--baseline` into the carry context, or None when there is none.

    Returning None is not an error: a repository with no baseline yet has to be
    reviewed whole, and that is the correct behaviour rather than a failure.
    """
    bm = baseline_mod()

    if spec in ("off", "none", ""):
        return None

    if spec == "auto":
        run_root, notes = bm.find_baseline(repo)
        if run_root is None:
            print("  no baseline available; this run is a whole-repo review")
            for note in notes[:3]:
                print(f"    {note}")
            return None
    else:
        run_root = Path(spec).resolve()
        ok, reasons = bm.is_baseline(run_root)
        if not ok:
            print(f"  --baseline {run_root} is not a usable baseline:")
            for reason in reasons:
                print(f"    {reason}")
            return None

    last = bm.round_dirs(run_root)[-1]
    meta = bm.read_meta(last)
    baseline_sha = meta.get("target_sha")

    try:
        changed = bm.changed_files(repo, baseline_sha)
    except RuntimeError as exc:
        print(f"  cannot diff against the baseline: {exc}")
        return None

    findings = bm.load_findings(last)
    carried, dropped = bm.carry(findings, changed)
    scores = bm.dimension_scores(last)

    print(f"  baseline {run_root.name} @ {str(baseline_sha)[:12]}: "
          f"{len(changed)} file(s) changed, {len(carried)} finding(s) carried, "
          f"{len(dropped)} invalidated")
    for finding in dropped:
        loc = (finding.get("location") or {}).get("path")
        print(f"    drop [{finding['_drop']}] {loc} -- {finding['_why']}")

    return {
        "run_root": str(run_root), "baseline_sha": baseline_sha,
        "changed": changed, "carried": carried, "dropped": dropped,
        "scores": scores,
    }


def apply_carry(round_dir: Path, ctx: Dict[str, Any]) -> Dict[str, int]:
    """Merge the carried findings in, then carry the LLM self-scores.

    Two halves, and the order matters only in that both must happen before the
    gate reads the files:

    - the findings, so the gate scores `carried + new` against the whole-repo
      kloc -- which is what keeps the aggregate comparable to the baseline;
    - the per-dimension LLM score, because a reviewer that saw six files cannot
      honestly score a fifty-file repository. Its self-assigned number is
      discarded and the baseline's is carried. The new signal is not lost: it
      lands in `det`, computed from the merged findings and the fresh probes.
    """
    bm = baseline_mod()

    added = bm.merge_into_round(round_dir, ctx["carried"])

    for dim, score in (ctx.get("scores") or {}).items():
        path = round_dir / f"{dim}.json"
        if not path.exists():
            continue
        try:
            review = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        review["score"] = score
        review["llm_carried_from_baseline"] = True
        path.write_text(
            json.dumps(review, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8", newline="\n",
        )
    return added


def carry_block(ctx: Optional[Dict[str, Any]]) -> str:
    """The prompt section describing a baseline and what it carried.

    Two jobs: give the reviewer the explicit changed-file list (which nothing
    passed before -- `--scope` only ever interpolated the literal word), and
    hand it the carried findings so it neither re-reports them nor wastes effort
    re-deriving them.
    """
    if not ctx:
        return ""
    changed = ctx.get("changed") or []
    carried = ctx.get("carried") or []
    lines = [
        "",
        "THIS IS AN INCREMENTAL REVIEW against a baseline whole-repo review at "
        f"{str(ctx.get('baseline_sha'))[:12]}.",
        f"Changed since that baseline ({len(changed)} file(s)) -- review THESE:",
    ]
    lines += [f"  - {p}" for p in changed[:60]]
    if len(changed) > 60:
        lines.append(f"  ... and {len(changed) - 60} more")
    lines += [
        "",
        f"{len(carried)} finding(s) from the baseline are CARRIED FORWARD for files",
        "that did not change. They are already counted in the score. Do NOT report",
        "them again. Report only what is wrong in the changed files, or what the",
        "change has made false elsewhere:",
    ]
    for f in carried[:40]:
        loc = (f.get("location") or {})
        lines.append(
            f"  - [{f.get('_dimension', '?')}] {loc.get('path')}:"
            f"{loc.get('line_range')} -- {str(f.get('claim'))[:110]}"
        )
    if len(carried) > 40:
        lines.append(f"  ... and {len(carried) - 40} more")
    return "\n".join(lines) + "\n"


# ── the reviewer's view of the probes ────────────────────────────────────────
# The prompt gets a BOUNDED digest; `probes.json` keeps every finding. The two consumers have
# different budgets: the gate and the next incremental run read the file, and only the prompt
# has to fit a model's context window. Measured on a Python repository, the full probe JSON was
# 515,487 of a 518,550-byte prompt — 1,013 ruff findings over 60 files, 975 of them `low`, 603
# of one rule — and the configured endpoint answered that request with a 504 at both a 240 s and
# a 900 s timeout, while the same profile answered a small prompt in 20 s.
PROMPT_PROBE_BUDGET_BYTES = 24_000
PROMPT_FINDINGS_PER_PROBE = 25
PROMPT_FINDINGS_PER_RULE = 3
PROMPT_CLAIM_CHARS = 180
PROMPT_CHECK_CHARS = 120

_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
_SEVERITY_UNKNOWN = 9


def _rule_code(finding: Dict[str, Any]) -> str:
    """The rule a finding came from: `ruff UP006: ...` -> `UP006`, else the claim's head."""
    claim = str(finding.get("claim") or "")
    m = re.match(r"^\S+\s+([A-Za-z]+[0-9]+)\b", claim)
    if m:
        return m.group(1).upper()
    return claim[:24] or "(unlabelled)"


def _trim_finding(finding: Dict[str, Any], repo: Path) -> Dict[str, Any]:
    """One finding with the fat removed: a repo-relative path and short strings.

    Measured on the 1,013-finding probe, `location` was 41.5% of the bytes because every path
    was absolute and `falsifiable_check` another 34.9% because it repeated that path inside a
    command. Neither gets more useful by being shown in full.
    """
    out = dict(finding)
    loc = dict(out.get("location") or {})
    path = str(loc.get("path") or "")
    if path:
        try:
            # as_posix(), not str(): on Windows `str(relative_to(...))` yields `scripts\\x.py`,
            # and the reviewer is told to cite `path:line`. The digest must read the same
            # whichever host ran the council — CI caught this on windows-latest.
            loc["path"] = Path(path).relative_to(repo).as_posix()
        except ValueError:
            pass  # outside the repo: leave it alone rather than mangle it
    out["location"] = loc
    for key, limit in (("claim", PROMPT_CLAIM_CHARS),
                       ("falsifiable_check", PROMPT_CHECK_CHARS)):
        value = out.get(key)
        if isinstance(value, str) and len(value) > limit:
            out[key] = value[:limit].rstrip() + "\u2026"
    return out


def probe_digest(probes: List[Dict[str, Any]], repo: Path,
                 budget_bytes: int = PROMPT_PROBE_BUDGET_BYTES) -> str:
    """Render the probe results for the reviewer prompt, bounded, without mutating *probes*.

    Findings are ranked by severity, then capped per rule code and per probe, because the volume
    is repetition rather than observation: 603 `UP006` and 138 `UP045` are two facts, not 741.
    Each entry reports `findings_total`, `findings_omitted` and `omitted_by_rule`, so the reviewer
    can say "600 more of this kind" instead of inferring silence.

    The list passed in is the record — this function reads it and returns a string. It is never
    the place a finding is dropped from disk: `probes.json` is written from the original list, and
    the incremental diff compares against that.
    """
    digest: List[Dict[str, Any]] = []
    for probe in probes:
        findings = list(probe.get("findings") or [])
        ranked = sorted(
            findings,
            key=lambda f: _SEVERITY_ORDER.get(
                str(f.get("severity") or "").lower(), _SEVERITY_UNKNOWN),
        )
        kept: List[Dict[str, Any]] = []
        per_rule: Dict[str, int] = {}
        omitted: Dict[str, int] = {}
        for finding in ranked:
            rule = _rule_code(finding)
            too_many = per_rule.get(rule, 0) >= PROMPT_FINDINGS_PER_RULE
            if len(kept) >= PROMPT_FINDINGS_PER_PROBE or too_many:
                omitted[rule] = omitted.get(rule, 0) + 1
                continue
            per_rule[rule] = per_rule.get(rule, 0) + 1
            kept.append(_trim_finding(finding, repo))

        entry: Dict[str, Any] = {k: v for k, v in probe.items() if k != "findings"}
        entry["findings"] = kept
        entry["findings_total"] = len(findings)
        entry["findings_omitted"] = len(findings) - len(kept)
        if omitted:
            entry["omitted_by_rule"] = dict(
                sorted(omitted.items(), key=lambda kv: (-kv[1], kv[0])))
        digest.append(entry)

    rendered = json.dumps(digest, indent=2, ensure_ascii=False)
    if len(rendered) <= budget_bytes:
        return rendered

    # Still over: keep the counts, drop the bodies. A prompt past the model's window produces no
    # review at all, which is strictly worse than a thin one that still names what it omitted.
    # The counts have to agree with what is actually shown: a body-less entry claiming three
    # findings were kept is a lie of the same kind the budget exists to avoid.
    bare = []
    for entry in digest:
        slim = {k: v for k, v in entry.items() if k != "findings"}
        slim["findings"] = []
        slim["findings_omitted"] = slim.get("findings_total", 0)
        slim["findings_dropped_for_budget"] = True
        bare.append(slim)
    return json.dumps(bare, indent=2, ensure_ascii=False)


def generalist_prompt(repo: Path, scope: str, round_no: int, sha: str,
                      stacks: List[str], probes: List[Dict[str, Any]],
                      goals: Dict[str, Any], out_path: Path,
                      carry_ctx: Optional[Dict[str, Any]] = None) -> str:
    """The ONE reviewer prompt (M8.5's collapsed generalist).

    Module-level, not a closure, because there are now TWO callers: the loop, which
    samples it N times in-process, and the durable swarm (M7), where each sample is
    a separate kanban card in a separate process. A second copy of this prompt would
    be a second definition of what a review is, and the two would drift — which is
    the failure mode this repository has already paid for twice (calibrate.py's
    private scorer, and the beta bug).

    `probe_json` is handed in rather than re-run: the probes are deterministic, so
    running them once per round is enough, and re-running them per sample would
    multiply a minutes-long cost by the sample count.
    """
    goal = goal_for(goals, DIMENSIONS[0])  # one goal; the generalist covers all five
    return GENERALIST_PROMPT.format(
        rubrics=", ".join(DIMENSION_SPEC[d]["rubric"] for d in DIMENSIONS),
        repo=repo, scope=scope, round=round_no, sha=sha,
        stacks=", ".join(stacks) or "none detected",
        goal_objective=(goal.get("objective")
                        or DEFAULT_GOALS[DIMENSIONS[0]]["objective"]),
        goal_acceptance=(goal.get("acceptance")
                         or DEFAULT_GOALS[DIMENSIONS[0]]["acceptance"]),
        goal_focus=", ".join(goal.get("focus") or []) or "(wherever the rubrics point)",
        probe_json=probe_digest(probes, Path(repo)),
        carry_block=carry_block(carry_ctx),
        out_path=out_path, profile=GENERALIST_PROFILE, prefix="GEN",
    )


def run_one_generalist_sample(binary: str, repo: Path, out_path: Path, prompt: str,
                              timeout: int, log: Path) -> int:
    """Run the reviewer ONCE, writing *out_path*. Returns the exit code.

    Shared by the loop's thread pool and the swarm's per-card invocation, so the
    retry rule is defined once: a sample that exits 0 without writing its file would
    silently shrink the review, so it gets exactly one retry and then the shortfall
    is reported by the caller.
    """
    rc, _ = run_hermes(binary, repo, prompt, timeout, log, profile=GENERALIST_PROFILE)
    if rc == 0 and not out_path.exists():
        rc, _ = run_hermes(binary, repo, prompt, timeout, log,
                           profile=GENERALIST_PROFILE)
    return rc


def run_generalist_reviewers(binary: str, repo: Path, run_dir: Path, scope: str,
                             round_no: int, timeout: int, log: Path,
                             probes: List[Dict[str, Any]], stacks: List[str],
                             sha: str, goals: Dict[str, Any],
                             samples: int,
                             carry_ctx: Optional[Dict[str, Any]] = None
                             ) -> Dict[str, int]:
    """Run ONE generalist profile `samples` times, then bucket what it found.

    Same profile every time, so the samples differ only by sampling — which is the
    variable the ablation found to matter. Returns a per-dimension rc map so the
    caller's reporting is unchanged: a dimension whose file was written reads ok.
    """
    from concurrent.futures import ThreadPoolExecutor

    def one(i: int) -> Tuple[int, int]:
        out_path = run_dir / f"generalist-{i}.json"
        prompt = generalist_prompt(repo, scope, round_no, sha, stacks, probes,
                                   goals, out_path, carry_ctx)
        return i, run_one_generalist_sample(binary, repo, out_path, prompt,
                                            timeout, log)

    with ThreadPoolExecutor(max_workers=samples) as pool:
        codes = dict(pool.map(one, range(1, samples + 1)))

    sample_paths = [run_dir / f"generalist-{i}.json" for i in range(1, samples + 1)]
    merged = merge_generalist_samples(sample_paths, run_dir, probes)
    print(f"    {merged['samples']}/{samples} sample(s) readable; "
          f"findings per dimension: "
          + ", ".join(f"{d}={merged.get(d, 0)}" for d in DIMENSIONS))
    if merged["dropped"]:
        print(f"    {merged['dropped']} finding(s) dropped: no usable `dimension` field")

    rc_by_dim: Dict[str, int] = {}
    for dim in DIMENSIONS:
        written = (run_dir / f"{dim}.json").exists()
        # Report the worst sample rc when a dimension produced nothing, so a total
        # failure still surfaces instead of reading as a clean empty review.
        rc_by_dim[dim] = 0 if written and merged["samples"] else (
            max(codes.values()) if codes else 2)
    return rc_by_dim


def confirm(prompt: str) -> bool:
    """semi mode: ask before an edit. Non-interactive stdin => refuse."""
    if not sys.stdin.isatty():
        print("  [semi] stdin is not a TTY — refusing to edit without approval.")
        return False
    try:
        return input(prompt).strip().lower() in {"y", "yes"}
    except (EOFError, KeyboardInterrupt):
        return False


# --- The loop ---------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="council_loop.py",
        description="Drive the review-council to termination (FRAMEWORK §7/§8).",
    )
    parser.add_argument("repo", nargs="?", default=None,
                        help="Repository to review. Omit to infer from the current directory "
                             "(nearest git root, or the nearest AGENTS.md/.hermes.md/CLAUDE.md "
                             "or build manifest).")
    parser.add_argument("--mode", choices=("full", "semi", "advisory"), default="full",
                        help="Autonomy mode (default: full)")
    parser.add_argument("--samples", type=int, default=5,
                        help="Samples of the generalist reviewer (default 5). Five "
                             "matched the five-specialist cost in the ablation, and "
                             "M8.5 found sampling — not profile count — is what buys "
                             "recall. Lower it to trade recall for wall-clock.")
    parser.add_argument("--baseline", default="off",
                        help="Review only what changed since a baseline whole-repo "
                             "run, carrying that run's findings for the files that "
                             "did not change. 'auto' finds the newest qualifying "
                             "run, or pass a run-root path. Default: off.")
    parser.add_argument("--scope", choices=("diff", "working-tree", "whole-repo"),
                        default="working-tree", help="Review scope (DECISIONS #7: diff by default)")
    parser.add_argument("--threshold", type=float, default=None,
                        help="MINIMUM aggregate score required to pass (default: the "
                             "calibrated value from scripts/calibration.json). "
                             "Everything above this is desirable but not required.")
    parser.add_argument("--min-rounds", type=int, default=1,
                        help="Always attempt at least this many rounds (default 1), so one "
                             "unlucky round cannot end the run.")
    parser.add_argument("--max-rounds", type=int, default=8,
                        help="Hard safety cap on rounds (default 8). The loop normally stops "
                             "earlier, once gains stall or the budget is spent.")
    parser.add_argument("--budget-seconds", type=float, default=0.0,
                        help="Wall-clock budget for the whole run (0 = unlimited). The loop "
                             "stops and hands over a plan when this is spent.")
    parser.add_argument("--k", type=int, default=2, help="Novelty window (default 2)")
    parser.add_argument("--epsilon", type=float, default=0.5,
                        help="Marginal-improvement floor (default 0.5)")
    parser.add_argument("--timeout", type=int, default=1800, help="Per-turn timeout, seconds")
    parser.add_argument("--run-root", default=None, help="Where to write run dirs")
    parser.add_argument("--dry-run", action="store_true", help="Print the plan and exit")
    return parser


def _ask_for_project(searched: Path) -> Optional[Path]:
    """Ask which project to review, when there is a person to ask.

    TTY only, deliberately. A scheduled job, a spawned worker or an agent turn
    has nobody at the terminal, and blocking on a prompt there hangs instead of
    failing -- so those keep the refusal in resolve_target. This is for someone
    running the loop by hand from a directory that is not inside a project.
    """
    if not sys.stdin.isatty():
        return None
    print(
        f"council_loop: no project found from {searched}.\n"
        "  the session is not anchored to one, and there is no git root or\n"
        "  project marker above it",
        file=sys.stderr,
    )
    try:
        answer = input("  path to review (blank to cancel): ").strip()
    except (EOFError, KeyboardInterrupt):
        print("", file=sys.stderr)
        return None
    if not answer:
        return None
    return Path(answer).expanduser().resolve()


def hermes_home() -> Optional[Path]:
    """Where Hermes keeps its profiles, resolved the way Hermes itself does.

    HERMES_HOME wins when it is set and real. Otherwise ask Hermes -- `profile
    show default` prints the default profile's Path, which IS the home, since
    profiles live at <home>/profiles. That is authoritative, profile-aware and
    cross-platform, which the fallbacks are not: a native Windows install keeps it
    under %LOCALAPPDATA%, and ~/.hermes is the POSIX default.
    """
    explicit = os.environ.get("HERMES_HOME")
    if explicit:
        candidate = Path(explicit).expanduser()
        if candidate.is_dir():
            return candidate

    # Cheap answers first: `hermes profile show default` costs ~550 ms (measured), most
    # of a `--dry-run`'s 612 ms. install_bots.py asks Hermes first because it WRITES there.
    candidates = [Path.home() / ".hermes"]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(Path(local) / "hermes")
    for candidate in candidates:
        if candidate.is_dir():
            return candidate

    # Last resort: a home that is neither the default nor in the environment. Only here is
    # the subprocess worth its cost.
    binary = hermes_bin()
    if binary:
        try:
            proc = subprocess.run(
                [binary, "profile", "show", "default"],
                capture_output=True, text=True, timeout=60,
                encoding="utf-8", errors="replace",
            )
            for line in (proc.stdout or "").splitlines():
                if line.startswith("Path:"):
                    candidate = Path(line.split(":", 1)[1].strip())
                    if candidate.is_dir():
                        return candidate
        except (OSError, subprocess.TimeoutExpired):
            pass
    return None


def missing_profiles() -> List[str]:
    """The profiles this run needs and that are not installed.

    Two, and both are load-bearing: the orchestrator sets each round's goals and
    aggregates, the generalist is the reviewer sampled N times. A run with either
    missing produces no reviewer output at all.
    """
    home = hermes_home()
    needed = (ORCHESTRATOR_PROFILE, GENERALIST_PROFILE)
    if home is None:
        return list(needed)
    return [name for name in needed if not (home / "profiles" / name).is_dir()]


def profile_preflight() -> Optional[str]:
    """The refusal message when the profiles are missing, else None."""
    missing = missing_profiles()
    if not missing:
        return None

    lines = [
        "council_loop: the council profiles are not installed, so nothing can review.",
        "",
        "Two Hermes profiles are required:",
        f"  {ORCHESTRATOR_PROFILE:<22} sets each round's goals, then judges the round",
        f"  {GENERALIST_PROFILE:<22} the reviewer, sampled N times",
        "",
        f"Missing: {', '.join(missing)}",
        "",
        "Install them, once per machine:",
        "  nix run .#council -- setup bots        (from a checkout)",
        "  nix run <flake-url> -- setup bots      (from a flake URL)",
        "  council setup bots                     (if council is on your PATH)",
    ]
    home = hermes_home()
    lines.append("")
    lines.append(f"Hermes home: {home if home else 'not found'}")
    lines.append("")
    lines.append("Then set credentials for each profile -- Hermes does not share them:")
    lines.append(f"  hermes -p {ORCHESTRATOR_PROFILE} setup")
    lines.append(f"  hermes -p {GENERALIST_PROFILE} setup")
    return "\n".join(lines)


def resolve_target(explicit: Optional[str]) -> Tuple[Optional[Path], int]:
    """Resolve and sanity-check the project to review.

    Order: an explicit path, then the session's anchored project (inferred from
    the session cwd), then -- on a terminal -- the user. Returns (repo, 0), or
    (None, exit_code) when the loop must not proceed.
    """
    repo, why, confident = resolve_project(explicit)
    if not confident and explicit is None:
        # Ask rather than refuse when a person is at the terminal: the first run is exactly
        # when the answer is needed.
        asked = _ask_for_project(repo)
        if asked is not None:
            repo, why, confident = asked, "answered at the prompt", True
    if not repo.is_dir():
        print(f"council_loop: not a directory: {repo}", file=sys.stderr)
        return None, 2
    if not confident:
        # Refuse an arbitrary directory (an unanchored session's cwd is the user's home):
        # failing loudly beats reviewing the wrong tree — and writing .review-council/ there.
        print(
            "council_loop: could not identify a project from the session.\n"
            f"  looked in: {repo}\n"
            "  no git root and no project marker (.hermes.md / AGENTS.md /\n"
            "  CLAUDE.md / pyproject.toml / package.json / Cargo.toml / go.mod)\n\n"
            "Fix one of:\n"
            "  * pass the path explicitly:  council_loop.py <path/to/project>\n"
            "  * anchor the session to a project (desktop: the Projects picker;\n"
            "    CLI/TUI: launch from inside the project (`cd /path/to/project`);\n"
            "             `--in` is Hermes main only and is absent from the wheel)\n",
            file=sys.stderr,
        )
        return None, 2
    if explicit is None:
        print(f"inferred project: {repo}\n  ({why})")
    return repo, 0


def update_novelty(round_dir: Path, seen_ids: set, no_new_rounds: int,
                   k: int) -> Tuple[int, set, int]:
    """Count this round's new verified findings and update the no-new streak.

    §8 terminates on "no new VERIFIED finding for k iterations" — so the streak
    counts rounds that surfaced no finding id we had not already seen.
    """
    new_count, seen_ids = count_new_verified(round_dir, seen_ids)
    no_new_rounds = 0 if new_count else no_new_rounds + 1
    print(f"  new findings this round: {new_count} "
          f"(no-new streak {no_new_rounds}/{k})")
    return new_count, seen_ids, no_new_rounds


def out_of_budget(started: float, budget_seconds: float,
                  now: Optional[float] = None) -> bool:
    """True when the wall-clock budget is spent. 0 or less means unlimited."""
    if budget_seconds <= 0:
        return False
    return ((now if now is not None else time.monotonic()) - started) >= budget_seconds


def decide_stop(*, round_no: int, max_rounds: int, min_rounds: int,
                met_minimum: bool, scores: List[float], epsilon: float,
                no_new_rounds: int, k: int, budget_spent: bool, mode: str,
                confirm_fn: Callable[[str], bool]) -> Optional[Tuple[str, str]]:
    """The adaptive continue/stop decision. None means "keep going".

    The threshold is the MINIMUM requirement. Everything above it is desirable
    but not required, so the loop keeps climbing while it is still gaining ground
    and stops — handing over a plan — once the gains stop, the budget runs out,
    or the minimum is met and further rounds would be grinding rather than
    improving. Chasing the theoretical maximum is explicitly not the goal.

    Returns (outcome, reason) where outcome is "satisfied" or "escalate".
    """
    # --- hard limits: these end the run whatever the score ---
    hard: Optional[Tuple[str, str]] = None
    if round_no >= max_rounds:
        # The reason must match the outcome: "without clearing the minimum" on a run that
        # DID clear it is the same error as calling a blocked-but-passing run "below".
        hard = ("satisfied" if met_minimum else "escalate",
                f"round cap reached ({max_rounds})"
                + (" with the minimum met" if met_minimum
                   else " without clearing the minimum"))
    elif budget_spent:
        hard = ("satisfied" if met_minimum else "escalate",
                "time budget exhausted"
                + (" with the minimum met" if met_minimum else ""))

    # The floor: always attempt min_rounds, so one unlucky round cannot end the run. A hard
    # limit still outranks it, or the floor could overrun the cap.
    if hard is None and round_no < min_rounds:
        return None

    # --- the specific terminators ---
    specific: Optional[Tuple[str, str]] = None
    if met_minimum:
        # Above the minimum is a matter of priority, not requirement. Continue
        # only while there is real headroom being gained.
        if len(scores) >= 2 and (scores[-1] - scores[-2]) < epsilon:
            gain = scores[-1] - scores[-2]
            specific = ("satisfied", (
                f"minimum met; further gain {gain:+.2f} < {epsilon} — stopping "
                "and planning the remainder"
            ))
    else:
        if len(scores) >= 3 and (scores[-1] < scores[-2] < scores[-3]):
            specific = ("escalate", "oscillation: score regressed across rounds")
        elif len(scores) >= 2 and abs(scores[-1] - scores[-2]) < epsilon:
            specific = ("escalate", (
                f"stalled: improvement < {epsilon} ({scores[-2]} -> {scores[-1]})"
            ))
        elif no_new_rounds >= k:
            specific = ("escalate", (
                f"novelty: no new findings for {k} consecutive rounds (k={k})"
            ))
        elif mode == "advisory":
            specific = ("escalate", "advisory mode: report only, no fixes applied")
        elif mode == "semi" and not confirm_fn(
            f"\nApply fixes for round {round_no}? [y/N] "
        ):
            specific = ("escalate", "semi mode: edits not approved")

    # Prefer the specific reason when both apply: "oscillation" or "stalled" tells the next
    # iteration what to change, where "round cap reached" does not.
    if specific is not None:
        return specific
    return hard


def render_next_steps(*, result: Dict[str, Any], history: List[Dict[str, Any]],
                      outcome: str, reason: str, threshold: float, repo: Path,
                      mode: str, rounds_used: int,
                      budget_seconds: float = 0.0,
                      handover: Optional[Dict[str, Any]] = None) -> str:
    """The handover plan: what to do next, required first, then by priority.

    Produced on EVERY termination, satisfied or not. When the loop stops early —
    budget spent, gains stalled, cap reached — this is the deliverable that lets
    the next iteration pick up where this one left off instead of starting over.
    """
    gate = _gate_module()
    opportunities = gate.improvement_opportunities(result, target=threshold)
    aggregate = result.get("aggregate")
    blocking = result.get("blocking") or []
    score_met = (isinstance(aggregate, (int, float))
                 and float(aggregate) >= threshold)

    lines: List[str] = []
    lines.append("# Review-council next steps")
    lines.append("")
    lines.append(f"- **Outcome:** {outcome.upper()} — {reason}")
    lines.append(f"- **Target repository:** `{repo}`")
    lines.append(f"- **Autonomy mode:** {mode}")
    lines.append(f"- **Rounds used:** {rounds_used}")
    if budget_seconds:
        lines.append(f"- **Time budget:** {budget_seconds:g}s")
    if aggregate is not None:
        # Report the SCORE requirement and the blocking gate separately: calling a
        # blocked-but-passing aggregate "below the minimum" is simply wrong.
        lines.append(f"- **Aggregate:** {aggregate:.2f} / minimum {threshold:g} "
                     f"({'meets the minimum' if score_met else 'BELOW the minimum'})")
    if blocking:
        ids = ", ".join(str(f.get("id") or "?") for f in blocking[:5])
        more = f" (+{len(blocking) - 5} more)" if len(blocking) > 5 else ""
        lines.append(f"- **Blocked by:** {len(blocking)} open high/critical "
                     f"finding(s): {ids}{more}")
    lines.append("")
    lines.append("The minimum score is the requirement. Everything above it is "
                 "desirable — the sections below are ordered by priority.")
    lines.append("")

    # --- trajectory ---
    if history:
        lines.append("## Score trajectory")
        lines.append("")
        lines.append("| Round | Aggregate | Gate |")
        lines.append("|---|---|---|")
        for h in history:
            agg = h.get("aggregate")
            agg_s = "n/a" if agg is None else f"{agg:.2f}"
            lines.append(f"| {h['round']} | {agg_s} | "
                         f"{'PASS' if h.get('gate_rc') == 0 else 'FAIL'} |")
        lines.append("")
        if len(history) >= 2:
            first = history[0].get("aggregate")
            last = history[-1].get("aggregate")
            if isinstance(first, (int, float)) and isinstance(last, (int, float)):
                lines.append(f"Net movement across the run: **{last - first:+.2f}** "
                             f"aggregate points.")
                lines.append("")

    # A validated change IS the plan. The A/B digest below is the fallback for a run that
    # produced none, because two plans that can disagree is the defect this replaces.
    if handover and handover.get("valid"):
        plan = read_handover_plan(Path(handover["path"]))
        lines.append("## The change")
        lines.append("")
        lines.append(f"`{plan['change']}` — an OpenSpec change the council wrote at "
                     f"`{handover['path']}`. Requirements first, then its tasks; work them in "
                     "order and archive it when they are done.")
        lines.append("")
        if plan["requirements"]:
            lines.append("### Requirements")
            lines.append("")
            for req in plan["requirements"][:12]:
                lines.append(f"- `{req['capability']}` — {req['name']}")
            if len(plan["requirements"]) > 12:
                lines.append(f"- _{len(plan['requirements']) - 12} more in the change_")
            lines.append("")
        if plan["tasks"]:
            lines.append("### Tasks")
            lines.append("")
            lines.extend(plan["tasks"])
            lines.append("")
        lines.append("### How to resume")
        lines.append("")
        resume = f'python scripts/council_loop.py "{repo}" --mode {mode}'
        if budget_seconds:
            resume += f" --budget-seconds {int(budget_seconds)}"
        lines.append("```bash")
        lines.append(resume)
        lines.append("```")
        lines.append("")
        return "\n".join(lines)

    lines.append("_No validated change was written this round; the plan below is derived from "
                 "the gate, not from a change._")
    lines.append("")

    required = [o for o in opportunities if o.get("required")]
    desirable = [o for o in opportunities if not o.get("required")]

    def render_item(index: int, o: Dict[str, Any], letter: str) -> List[str]:
        pts = o.get("points_potential")
        # The dimension actions already state their own headroom in prose, so
        # only append the figure when the action does not mention it.
        pts_s = (f" (+{pts:.2f} aggregate)"
                 if isinstance(pts, (int, float)) and "aggregate" not in o["action"]
                 else "")
        block = [f"**{letter}{index}. {o['action']}{pts_s}**"]
        if o.get("claim"):
            block.append(f"  - {o['claim']}")
        if o.get("location"):
            block.append(f"  - at `{o['location']}`")
        if o.get("verify"):
            block.append(f"  - verify: {o['verify']}")
        return block

    lines.append("## A. Required to meet the minimum")
    lines.append("")
    if not required:
        if blocking:
            lines.append("The aggregate meets the minimum; the blockers are listed "
                         "above and are the only required work.")
        else:
            lines.append("Nothing outstanding — the minimum is met. "
                         "Remaining work is optional polish (section B).")
        lines.append("")
    else:
        for i, o in enumerate(required, 1):
            lines.extend(render_item(i, o, "A"))
            lines.append("")

    lines.append("## B. Desirable — raise the score further, in priority order")
    lines.append("")
    if not desirable:
        lines.append("Nothing further identified.")
    else:
        for i, o in enumerate(desirable, 1):
            lines.extend(render_item(i, o, "B"))
            lines.append("")

    # --- how to resume ---
    lines.append("## C. How to resume")
    lines.append("")
    lines.append("Re-run the loop against the same target; it re-reviews from "
                 "scratch and picks up whatever is still open:")
    lines.append("")
    lines.append("```bash")
    resume = f'python scripts/council_loop.py "{repo}" --mode {mode}'
    if budget_seconds:
        resume += f" --budget-seconds {int(budget_seconds)}"
    lines.append(resume)
    lines.append("```")
    lines.append("")
    lines.append("To check what the deterministic tooling can already see, "
                 "before spending a full council run:")
    lines.append("")
    lines.append("```bash")
    lines.append(f'python scripts/doctor.py --repo "{repo}"')
    lines.append(f'python scripts/probes.py --all --repo "{repo}"')
    lines.append("```")
    lines.append("")
    return "\n".join(lines)


def write_outcome(run_root: Path, outcome: str, reason: str, scores: List[float],
                  args: argparse.Namespace, repo: Path, *,
                  plan_path: Optional[Path] = None,
                  met_minimum: bool = False,
                  handover: Optional[Dict[str, Any]] = None) -> None:
    (run_root / "outcome.json").write_text(
        json.dumps({"outcome": outcome, "reason": reason, "scores": scores,
                    "threshold": args.threshold, "mode": args.mode,
                    "repo": str(repo), "run_root": str(run_root),
                    "met_minimum": met_minimum,
                    "min_rounds": args.min_rounds,
                    "max_rounds": args.max_rounds,
                    "budget_seconds": args.budget_seconds,
                    "next_steps": str(plan_path) if plan_path else None,
                    "handover": handover if handover else None},
                   indent=2), encoding="utf-8")

    print("\n" + "=" * 60)
    print(f"OUTCOME: {outcome.upper()}")
    print(f"reason:  {reason}")
    print(f"scores:  {scores}")
    if plan_path:
        print(f"next:    {plan_path}")
    if handover and handover.get("found"):
        state = "valid" if handover.get("valid") else "INVALID"
        print(f"change:  {handover.get('path')} ({state})")
    print(f"run dir: {run_root}")
    print("=" * 60)


def fix_plan(handover: Optional[Dict[str, Any]], verdict: Dict[str, Any],
             threshold: float) -> str:
    """The plan the fixer works: the change's tasks when there is one, else the gate digest.

    One plan for the reader and another for the fixer is the same defect as two plans in the
    reader's own file — the turn that edits the tree must be working what the change says.
    """
    if handover and handover.get("valid") and handover.get("path"):
        plan = read_handover_plan(Path(handover["path"]))
        if plan.get("tasks"):
            head = (f"Work the OpenSpec change `{plan['change']}` at `{handover['path']}`. "
                    "Its tasks, in order:")
            return head + "\n" + "\n".join(plan["tasks"])
    return priority_digest(verdict, threshold)


def priority_digest(verdict: Dict[str, Any], threshold: float,
                    limit: int = 12) -> str:
    """A compact, ordered work list for the fix turn, from the gate verdict."""
    try:
        opportunities = _gate_module().improvement_opportunities(
            verdict, target=threshold)
    except Exception:  # noqa: BLE001 — never break the loop over a digest
        return "(could not derive a priority list; work from the gate output above)"
    if not opportunities:
        return "(nothing outstanding)"

    lines: List[str] = []
    for i, o in enumerate(opportunities[:limit], 1):
        tag = "REQUIRED" if o.get("required") else "desirable"
        pts = o.get("points_potential")
        pts_s = f" (+{pts:.2f})" if isinstance(pts, (int, float)) else ""
        lines.append(f"{i}. [{tag}] {o['action']}{pts_s}")
        if o.get("location"):
            lines.append(f"     at {o['location']}")
        if o.get("verify"):
            lines.append(f"     verify: {o['verify']}")
    if len(opportunities) > limit:
        lines.append(f"... and {len(opportunities) - limit} further item(s); "
                     "see the run's next-steps.md")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    # From the calibration manifest unless named, so the loop and the calibration cannot
    # drift (it was hardcoded in three places).
    if args.threshold is None:
        args.threshold = float(_gate_module().calibrated_threshold())

    repo, code = resolve_target(args.repo)
    if repo is None:
        return code

    binary = hermes_bin()
    if not binary:
        print("council_loop: `hermes` not found on PATH", file=sys.stderr)
        return 2

    # Before the run dir exists, so a refusal writes nothing; before `--dry-run` returns, so
    # a dry run answers "will this work?", not only "what is the plan".
    refusal = profile_preflight()
    if refusal:
        print(refusal, file=sys.stderr)
        return 2

    stamp = time.strftime("%Y%m%d-%H%M%S")
    run_root = Path(args.run_root) if args.run_root else (repo / ".review-council" / stamp)
    # A raw PermissionError here is the first thing a container user meets, and a traceback
    # does not name the cause: the image runs as uid 1000, so a repo mounted from another
    # account is read-only to it.
    try:
        run_root.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        # os.getuid is POSIX-only and this module ships to Windows too.
        uid = getattr(os, "getuid", lambda: -1)()
        print(f"council: cannot create the run directory {run_root}", file=sys.stderr)
        print(f"  {run_root.parent} is not writable by uid {uid}.", file=sys.stderr)
        print("  In the container the image runs as uid 1000, so a repo mounted from", file=sys.stderr)
        print("  another account is read-only to it. Run it as yourself instead:", file=sys.stderr)
        print("", file=sys.stderr)
        print("    docker run --rm --user \"$(id -u):$(id -g)\" \\", file=sys.stderr)
        print("      -v \"$PWD:/repo\" ... review-council /repo", file=sys.stderr)
        return 2
    log = run_root / "council.log"

    plan = {
        "repo": str(repo), "mode": args.mode, "scope": args.scope,
        "minimum_score": args.threshold, "min_rounds": args.min_rounds,
        "max_rounds": args.max_rounds, "budget_seconds": args.budget_seconds,
        "k": args.k, "epsilon": args.epsilon, "run_root": str(run_root),
    }
    print(json.dumps(plan, indent=2))
    if args.dry_run:
        return 0

    started = time.monotonic()
    seen_ids: set = set()
    scores: List[float] = []
    history: List[Dict[str, Any]] = []
    no_new_rounds = 0
    outcome = "escalate"
    reason = "round cap reached"
    verdict: Dict[str, Any] = {}
    handover: Dict[str, Any] = {}
    rounds_used = 0

    # Facts the harness owns, resolved once: the revision under review, the
    # detected stacks, and the deterministic probe results.
    sha = git_sha(repo)
    stacks = _gate_module().relevant_stacks(repo)
    print(f"target revision: {sha}")
    print(f"detected stacks: {', '.join(stacks) or 'none'}")
    print("running deterministic probes (once, for the whole run)…", flush=True)
    probes = run_probes(repo)
    print(f"  {len(probes)} probe(s) ran")

    # Persisted so a later incremental run can diff its probes against these: a signal that
    # moved is the one invalidation signal needing no file reading. Written once, because
    # the probes run once per run.
    (run_root / "probes.json").write_text(
        json.dumps(probes, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8", newline="\n",
    )

    # Resolved once, before the loop: the baseline cannot change mid-run, and diffing once
    # keeps every round measuring the same change.
    carry_ctx = resolve_carry(repo, args.baseline, log)
    meta_mode = "incremental" if carry_ctx else args.scope
    prompt_scope = (
        f"incremental -- {len(carry_ctx['changed'])} file(s) changed since "
        f"{str(carry_ctx['baseline_sha'])[:12]}"
        if carry_ctx else args.scope
    )
    meta_extra: Dict[str, Any] = {}
    if carry_ctx:
        meta_extra = {
            "baseline": carry_ctx["run_root"],
            "baseline_sha": carry_ctx["baseline_sha"],
            "changed": carry_ctx["changed"],
            "carried": len(carry_ctx["carried"]),
            "invalidated": len(carry_ctx["dropped"]),
        }

    for round_no in range(1, args.max_rounds + 1):
        rounds_used = round_no
        round_dir = run_root / f"round-{round_no}"
        round_dir.mkdir(parents=True, exist_ok=True)
        print(f"\n=== round {round_no}/{args.max_rounds} — review ===", flush=True)

        # 1. Goals: one per dimension, set by the orchestrator. Fail-open — a goal-setting
        #    failure is not a review failure, so it degrades to the built-in set.
        write_meta(round_dir, repo, meta_mode, round_no, stacks, sha,
                   extra=meta_extra)
        print("  setting this round's goals…", flush=True)
        goals = set_goals(binary, repo, round_dir, args.scope, round_no,
                          args.timeout, log, probes, stacks, sha)

        # 2. Convene. One generalist profile sampled N times, then bucketed by dimension,
        #    so everything downstream reads the same per-dimension files as before.
        print(f"  convening 1 generalist x {args.samples} samples…", flush=True)
        rc_by_dim = run_generalist_reviewers(
            binary, repo, round_dir, prompt_scope, round_no, args.timeout, log,
            probes, stacks, sha, goals, args.samples, carry_ctx)
        timed_out = [d for d, rc in rc_by_dim.items() if rc == 124]
        failed = [d for d, rc in rc_by_dim.items() if rc not in (0, 124)]
        missing = [d for d in DIMENSIONS if not (round_dir / f"{d}.json").exists()]
        for d in DIMENSIONS:
            mark = "ok" if (round_dir / f"{d}.json").exists() else "NO FILE"
            print(f"    {d:<14} rc={rc_by_dim.get(d, '?')}  {mark}")
        if timed_out:
            print(f"  timed out: {', '.join(timed_out)}")
        if failed:
            print(f"  non-zero exit: {', '.join(failed)}")

        # Carry, before the orchestrator and the gate read these files, so both
        # see `carried + new` exactly as a whole-repo round would.
        if carry_ctx:
            added = apply_carry(round_dir, carry_ctx)
            total_added = sum(added.values())
            print(f"  carried {total_added} finding(s) into "
                  f"{len(added)} dimension(s); LLM scores carried from the baseline")

        # 3. Aggregate: the orchestrator validates and builds the evidence matrix.
        #    It does NOT decide the verdict — the gate does, from the same files.
        ok = [d for d in DIMENSIONS if d not in missing]
        rc, _ = run_hermes(
            binary, repo,
            AGGREGATE_PROMPT.format(
                repo=repo, round=round_no, run_dir=round_dir,
                reviewers_ok=", ".join(ok) or "(none)",
                reviewers_failed=", ".join(missing) or "(none)",
            ),
            args.timeout, log,
        )
        if rc == 124:
            print("  orchestrator timed out during aggregation "
                  "(the gate still reads the reviewer files)")

        # 4. Gate: the deterministic verdict, from the reviewer files.
        gate_rc, gate_out, verdict = run_gate(round_dir, args.threshold, repo=repo)
        if gate_rc == 2:
            reason = "gate could not evaluate the run (missing/unparseable reviewer output)"
            print(f"  {reason}: {gate_out[:400]}")
            break

        aggregate = verdict.get("aggregate")
        scores.append(float(aggregate) if isinstance(aggregate, (int, float)) else 0.0)
        met_minimum = gate_rc == 0
        history.append({"round": round_no, "aggregate": aggregate, "gate_rc": gate_rc})
        print(f"  aggregate {aggregate} / minimum {args.threshold:g}  ->  "
              f"{'PASS' if met_minimum else 'FAIL'}")

        _new_count, seen_ids, no_new_rounds = update_novelty(
            round_dir, seen_ids, no_new_rounds, args.k)

        # 5. Goal review: the orchestrator explains the round against its goals. The gate
        #    has ALREADY decided acceptance; this never overrides it.
        rc = review_goals(binary, repo, round_dir, round_no, goals,
                          args.timeout, log,
                          reviewers_ok=", ".join(ok),
                          reviewers_failed=", ".join(missing),
                          gate_output=gate_out)
        if rc == 124:
            print("  orchestrator timed out during the goal review "
                  "(the gate verdict stands)")

        # The handover the orchestrator was asked to write, checked rather than trusted.
        handover = validate_handover(run_root / "handover" / "openspec" / "changes")
        if handover["found"]:
            state = "valid" if handover["valid"] else "INVALID"
            print(f"  handover: openspec change, {state}")
            for problem in handover["problems"]:
                print(f"    - {problem}")
        else:
            print("  handover: no openspec change written this round")

        stop = decide_stop(
            round_no=round_no, max_rounds=args.max_rounds,
            min_rounds=args.min_rounds, met_minimum=met_minimum,
            scores=scores, epsilon=args.epsilon,
            no_new_rounds=no_new_rounds, k=args.k,
            budget_spent=out_of_budget(started, args.budget_seconds),
            mode=args.mode, confirm_fn=confirm,
        )
        if stop:
            outcome, reason = stop
            break

        # --- fix turn (§7) ---
        print(f"=== round {round_no} — fix (mode: {args.mode}) ===", flush=True)
        run_hermes(
            binary, repo,
            FIX_PROMPT.format(
                repo=repo, gate_output=gate_out, mode=args.mode,
                next_steps=fix_plan(handover, verdict, args.threshold),
            ),
            args.timeout, log,
        )

    # Produced on EVERY termination, satisfied or not: when the loop stops early (budget,
    # stall, cap) this is what lets the next iteration pick up instead of starting over.
    plan_path: Optional[Path] = None
    if verdict:
        plan_path = run_root / "next-steps.md"
        plan_path.write_text(
            render_next_steps(
                result=verdict, history=history, outcome=outcome, reason=reason,
                threshold=args.threshold, repo=repo, mode=args.mode,
                rounds_used=rounds_used, budget_seconds=args.budget_seconds,
                handover=handover or None,
            ),
            encoding="utf-8",
        )
        if handover.get("found"):
            with plan_path.open("a", encoding="utf-8") as fh:
                fh.write("\n## The change\n\n")
                fh.write(f"The handover is an OpenSpec change at `{handover['path']}`.\n\n")
                if handover["valid"]:
                    fh.write("It validates against the container's shape: a proposal with Why "
                             "and What Changes, requirements with WHEN/THEN scenarios, and "
                             "tasks as checkboxes.\n")
                else:
                    fh.write("**It does not validate.** Structural problems:\n\n")
                    for problem in handover["problems"]:
                        fh.write(f"- {problem}\n")

    write_outcome(run_root, outcome, reason, scores, args, repo,
                  plan_path=plan_path, met_minimum=(outcome == "satisfied"),
                  handover=handover or None)
    return 0 if outcome == "satisfied" else 1


if __name__ == "__main__":
    # Not a program: reached through `council <verb>`. See council.py.
    from council import require_dispatch

    require_dispatch("review")
    sys.exit(main())
