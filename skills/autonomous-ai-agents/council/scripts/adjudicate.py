"""Adjudicate: the orchestrator demands a proof for every claim, and records what it settled.

A finding is a claim. `protocol/proofs.json` says what a checkable claim looks like; this module is
where the orchestrator *asks* for that check, runs it, and writes down the result — including, and
this is the point, the claims it could not settle.

Four states per finding, and only one of them is a pass:

| state | meaning | blocks certification |
|---|---|---|
| `confirmed` | the proof reproduced, and its control failed as required | **yes** — a real defect |
| `refuted` | the proof failed to reproduce | no — there is no defect to answer |
| `unsettled` | no proof, an uncontrolled proof, or a control that also passed | **yes** — nobody knows |
| `unrunnable` | the proof could not run here (no browser, no server, bad params) | **yes** — nobody knows |

`refuted` is the only state that clears a blocking finding, which is the asymmetry that matters: a
claim is guilty until its proof fails. The run is then never "fine"; it is either certified, or it
names what stopped it.

What this does NOT do: it does not decide the verdict, and it does not touch the score. Wiring the
verdict to these states is the next step, deliberately separate so the change can be measured on its
own. Until then a run is adjudicated and still scored as before — and `enforced: false` says so in
the output, so a reader cannot mistake the report for the gate.

CLI:
    council adjudicate <run-dir | round-dir> [--repo DIR] [--json] [--fail-on-unproven]
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import proofs as proof_mod  # noqa: E402 - after sys.path, by design
import score_reviews  # noqa: E402 - the blocking rule lives there and is not duplicated here
import severity as severity_mod  # noqa: E402 - the evidence -> severity rule table

SCHEMA_VERSION = 1
IGNORED_FILES = frozenset({"meta.json", "probes.json", "proofs.json", "calibration.json",
                           "outcome.json", "plan.json", "verdict.json"})
CLOSED_STATUS = frozenset({"fixed", "wontfix", "accepted", "closed"})
ROUND_DIR = re.compile(r"^round-(\d+)$")


# --- locating the round -----------------------------------------------------------


def looks_like_reviewer_file(path: Path) -> bool:
    """A reviewer payload is a JSON object carrying `findings` — not our own bookkeeping."""
    if path.suffix != ".json" or path.name in IGNORED_FILES:
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(payload, dict) and isinstance(payload.get("findings"), list)


def reviewer_files(directory: Path) -> List[Path]:
    """The files the GATE scores, and only those.

    A round directory after a merge holds both the per-sample files (`generalist-1.json`) and the
    merged per-dimension files (`security.json`, …), and the gate reads the merged ones. Reading
    every file with a `findings` key adjudicated the same claim twice — 30 records for 25 findings
    — so the merged set wins whenever it exists and the samples are the fallback.
    """
    candidates = [p for p in sorted(directory.glob("*.json")) if looks_like_reviewer_file(p)]
    merged = [p for p in candidates if p.stem in score_reviews.WEIGHTS]
    return merged or candidates


def _rounds(target: Path) -> List[Tuple[int, Path]]:
    rounds: List[Tuple[int, Path]] = []
    for path in sorted(target.glob("round-*")):
        match = ROUND_DIR.match(path.name)
        if match and path.is_dir() and reviewer_files(path):
            rounds.append((int(match.group(1)), path))
    return rounds


def locate(target: Path) -> Tuple[Path, Path]:
    """Return (run_root, round_dir) from either. Rounds sort numerically, as everywhere else."""
    target = target.resolve()
    if reviewer_files(target):
        return target.parent, target
    rounds = _rounds(target)
    if not rounds:
        raise FileNotFoundError(f"{target}: no round with reviewer files under it")
    return target, max(rounds)[1]


# --- the rule that decides what blocks ---------------------------------------------


def blocking(dimension: str, severity: str, status: str) -> bool:
    """The gate's own rule, imported rather than restated.

    Security and correctness block at `high`; the other dimensions only at `critical`. A second copy
    of that table here would drift the first time either changed.
    """
    if status in CLOSED_STATUS:
        return False
    severities = score_reviews.BLOCKING_SEVERITIES.get(dimension, score_reviews.DEFAULT_BLOCKING)
    return severity in severities


def read_findings(round_dir: Path) -> List[Dict[str, Any]]:
    found: List[Dict[str, Any]] = []
    for path in reviewer_files(round_dir):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for index, finding in enumerate(payload.get("findings") or [], 1):
            if not isinstance(finding, dict):
                continue
            record = dict(finding)
            record.setdefault("id", f"{path.stem}-{index}")
            record.setdefault("dimension", path.stem)
            record["_source"] = path.name
            found.append(record)
    return found


def repo_for(run_root: Path, round_dir: Path, explicit: Optional[Path]) -> Optional[Path]:
    if explicit:
        return explicit.resolve()
    for candidate in (round_dir / "meta.json", run_root / "meta.json"):
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        repo = payload.get("repo")
        if repo and Path(repo).is_dir():
            return Path(repo)
    return None


# --- adjudicating one round --------------------------------------------------------


def _norm_path(value: Any) -> str:
    """A repo-relative path with only the `./` prefix removed.

    Not `lstrip('./')`: that strips characters, so `../a.py` would become `a.py` and a proof
    outside the tree would be accepted as being about a file inside it.
    """
    text = PurePosixPath(str(value)).as_posix()
    while text.startswith("./"):
        text = text[2:]
    return text


def _matches_pattern(pattern: str, path: str) -> bool:
    """Does a proof's include/exclude pattern cover this path?

    Globs are matched with `fnmatch`, which treats `*` as spanning separators; that is deliberately
    generous — a pattern that might cover the file counts as covering it, and the strict checks are
    the ones that reject.
    """
    pattern = str(pattern).strip()
    path = _norm_path(path)
    if not pattern or not path:
        return False
    if _norm_path(pattern) == path:
        return True
    candidates = {pattern, pattern[3:] if pattern.startswith("**/") else pattern}
    return any(fnmatch.fnmatchcase(path, candidate) for candidate in candidates)


def _proves_the_claimed_place(proof: Optional[Dict[str, Any]],
                              location: Dict[str, Any]) -> Tuple[bool, str]:
    """Does the proof examine the file the finding is about?

    Measured twice, in both directions:

    * a finding about a credential in `src/svc/__init__.py:4` was proven with a `present` proof over
      `src/svc/client.py:9`, and adjudication confirmed it because the check passed and its control
      failed. A passing check somewhere else is not evidence here.
    * three complexity claims were confirmed by `absent` proofs whose `exclude` named the very file
      claimed. An absence proof that excludes a file says nothing about that file — it establishes
      something about the others. Without this, a claim can be confirmed by evidence that cannot
      observe it, which is worse than no confirmation.

    `command` proofs run over the whole tree and are left to the control, which is what catches a
    check that cannot fail.
    """
    params = (proof or {}).get("params") or {}
    kind = str((proof or {}).get("kind") or "")
    claim_path = (location or {}).get("path")
    if not claim_path:
        return True, ""
    if kind in ("present", "absent"):
        for pattern in params.get("exclude") or []:
            if _matches_pattern(str(pattern), claim_path):
                return False, (f"the proof excludes `{claim_path}`, so it establishes nothing "
                               f"about it")
        includes = [str(p) for p in params.get("include") or [] if str(p).strip()]
        if includes and not any(_matches_pattern(p, claim_path) for p in includes):
            return False, (f"the proof's include patterns {includes} do not cover "
                           f"`{claim_path}`")
    proven_path = params.get("path")
    if not proven_path:
        return True, ""
    if _norm_path(proven_path) == _norm_path(claim_path):
        return True, ""
    return False, (f"the proof examined `{proven_path}`, and the claim is about `{claim_path}`")


def _state(admission: str) -> str:
    return {
        "proven": "confirmed",
        "refuted": "refuted",
        "uncontrolled": "unsettled",
        "control_did_not_fail": "unsettled",
        "unrunnable": "unrunnable",
    }.get(admission, "unsettled")


def _reason(finding: Dict[str, Any], verdict: Dict[str, Any]) -> str:
    """Why this claim stands where it stands — in words a reader can act on."""
    state = _state(verdict["admission"])
    if state == "confirmed":
        return f"proof reproduced, control failed as required — {verdict['detail']}"
    if state == "refuted":
        return f"the proof did not reproduce — {verdict['detail']}"
    if state == "unrunnable":
        return f"the check could not run here — {verdict['detail']}"
    if not finding.get("proof"):
        candidate = finding.get("falsifiable_check")
        if candidate:
            return ("no structured proof offered. The finding names a check "
                    f"(`{str(candidate)[:80]}…`) but prose is not a proof the orchestrator can run")
        return "no structured proof offered"
    control = verdict.get("control") or {}
    if control.get("status") == "supported":
        return ("the check supports the claim and its opposite alike — the control also passed, so "
                "it cannot tell this claim apart from its negation")
    return f"proof ran without a usable control — {verdict['detail']}"


def adjudicate_round(round_dir: Path, repo: Optional[Path],
                     base_tree: Optional[Path] = None) -> Dict[str, Any]:
    """Adjudicate every finding in a round and write `proofs.json` beside it.

    *base_tree* is a clean checkout of the revision the change is measured against. With it, a
    claim that arrives without a control gets one synthesised — the same check, run where the
    defect is not — so "the check can fail" is demonstrated by the orchestrator rather than
    asserted by the reviewer.
    """
    run_root, round_dir = locate(round_dir)
    repo = repo_for(run_root, round_dir, repo)
    findings = read_findings(round_dir)
    if repo is None:
        raise FileNotFoundError(
            f"{round_dir}: no repository to run proofs against (no --repo, no meta.json `repo`)")
    # A typo in --repo must not cost a good adjudication. Measured: a diagnostic run pointed at a
    # path that did not exist, every proof came back unrunnable, and the all-unrunnable report was
    # written over a round where four claims had been confirmed. The tree is a precondition, so
    # this refuses before anything is written.
    if not Path(repo).is_dir():
        raise FileNotFoundError(
            f"{round_dir}: repository root `{repo}` does not exist — refusing to replace the "
            f"existing adjudication with results no proof could produce")
    context = proof_mod.Context(root=repo, artefact_dir=round_dir / "proofs",
                                base_root=Path(base_tree).resolve() if base_tree else None)

    records: List[Dict[str, Any]] = []
    for finding in findings:
        dimension = str(finding.get("dimension") or "")
        severity = str(finding.get("severity") or "").strip().lower()
        status = str(finding.get("status") or "open").strip().lower()
        location = finding.get("location") or {}
        proof = finding.get("proof")
        if isinstance(proof, dict):
            verdict = proof_mod.adjudicate(proof, context)
        else:
            verdict = {"admission": "uncontrolled", "class": "unproven", "kind": "",
                       "detail": "no proof offered", "control": None, "artefact": None}
        state = _state(verdict["admission"])
        right_place, mismatch = _proves_the_claimed_place(proof, location)
        if not right_place and state == "confirmed":
            # A proven check about a different file does not settle this finding. Demoted to
            # unsettled, which reports without blocking — the claim may still be true, it is
            # simply not what was proven.
            state = "unsettled"
            verdict["detail"] = f"{verdict['detail']} — {mismatch}"
        # Severity comes from what the tool detected, not from how the reviewer described it. The
        # reviewer's label is advisory and applies only when no rule covers the tool; it is never
        # used to downgrade evidence. Without this, the same committed credential scored
        # critical, critical and medium across three passes of one tree.
        evidence_severity, rule_id, authority = severity_mod.from_evidence(
            proof if isinstance(proof, dict) else None, verdict.get("observed"))
        effective, severity_source = severity_mod.effective(severity, evidence_severity, authority)
        # A severity the evidence does not corroborate may still be REPORTED, but it may not impose
        # the hardest cap on its own word. Measured: a formatting finding asserted `critical` and
        # proven by a linter produced the lowest score in the corpus (52.49) and a 15.59-point
        # spread across six passes of one tree. Uncorroborated severity is held at `high` — serious
        # enough to matter, not enough to let an opinion set the ceiling.
        corroborated = (evidence_severity is not None
                        and severity_mod.RANK.get(evidence_severity, -1)
                        >= severity_mod.RANK.get(effective, 99))
        severity_scored = effective
        if not corroborated and severity_mod.RANK.get(effective, 0) > \
                severity_mod.RANK["high"]:
            severity_scored = "high"
        # Blocking keeps the ASSERTED severity: a block that should not have been raised is visible
        # in the report and can be argued; a block that was never raised is invisible. Corroboration
        # governs the CAP instead (below), where an opinion must not set a numeric ceiling.
        blocking_here = blocking(dimension, effective, status)
        records.append({
            "id": finding.get("id"),
            "source": finding.get("_source"),
            "dimension": dimension,
            "severity": effective,
            "severity_scored": severity_scored,
            "severity_corroborated": corroborated,
            "severity_reviewer": severity,
            "severity_evidence": evidence_severity,
            "severity_rule": rule_id or None,
            "severity_source": severity_source,
            "status": status,
            "location": finding.get("location"),
            "claim": finding.get("claim"),
            "candidate": finding.get("falsifiable_check"),
            "proof_kind": verdict.get("kind") or None,
            "admission": verdict["admission"],
            "state": state,
            "blocks_certification": bool(blocking_here and state != "refuted"),
            "control": verdict.get("control"),
            # Who wrote the control: the reviewer, or the orchestrator from the base revision.
            # A reader has to be able to tell a demonstrated control from an asserted one.
            "control_source": verdict.get("control_source"),
            "artefact": verdict.get("artefact"),
            "reason": _reason(finding, verdict),
        })

    records.sort(key=lambda record: (str(record["source"]), str(record["id"])))
    summary = {
        "findings": len(records),
        "confirmed": sum(1 for r in records if r["state"] == "confirmed"),
        "refuted": sum(1 for r in records if r["state"] == "refuted"),
        "unsettled": sum(1 for r in records if r["state"] == "unsettled"),
        "unrunnable": sum(1 for r in records if r["state"] == "unrunnable"),
        "blocking": sum(1 for r in records if r["blocks_certification"]),
        "blocking_confirmed": sum(1 for r in records if r["blocks_certification"]
                                  and r["state"] == "confirmed"),
        "blocking_unsettled": sum(1 for r in records if r["blocks_certification"]
                                  and r["state"] in {"unsettled", "unrunnable"}),
        "certification_blocked": any(r["blocks_certification"] for r in records),
    }
    payload = {
        "schema_version": SCHEMA_VERSION,
        "round": round_dir.name,
        "repo": str(repo),
        # Stated, not implied: this report does not change the verdict yet, and a reader must not
        # read `certification_blocked: false` as "the gate passed".
        "enforced": False,
        "summary": summary,
        "findings": records,
    }
    (round_dir / "proofs.json").write_text(
        json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8", newline="\n")
    return payload


# --- the report --------------------------------------------------------------------


def render(payload: Dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [f"adjudication — {payload['round']}  ({payload['repo']})",
             f"  findings   : {summary['findings']}  "
             f"(confirmed {summary['confirmed']}, refuted {summary['refuted']}, "
             f"unsettled {summary['unsettled']}, unrunnable {summary['unrunnable']})",
             f"  blocking   : {summary['blocking']}  "
             f"(confirmed {summary['blocking_confirmed']}, "
             f"unsettled {summary['blocking_unsettled']})",
             "  enforced   : no — this report does not change the verdict (see docs/ADJUDICATION.md)"]
    if summary["certification_blocked"]:
        lines.append(f"  verdict    : NOT certifiable as it stands — {summary['blocking']} claim(s) "
                     f"block it ({summary['blocking_confirmed']} confirmed, "
                     f"{summary['blocking_unsettled']} unsettled):")
        for record in payload["findings"]:
            if record["blocks_certification"]:
                location = record.get("location") or {}
                where = f"{location.get('path', '?')}:{location.get('line_range', '?')}"
                lines.append(f"    - [{record['state']}] {record['dimension']} "
                             f"{record['severity']} {where} — {record['reason']}")
    else:
        lines.append("  verdict    : nothing blocking is unsettled")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="adjudicate",
        description=(__doc__ or "").splitlines()[0] if (__doc__ or "").strip() else None)
    parser.add_argument("run", help="a run directory or one of its round directories")
    parser.add_argument("--repo", help="the tree the proofs run against (default: meta.json)")
    parser.add_argument("--base-tree", help="a clean checkout of the base revision; claims without "
                                            "a control get one synthesised from it")
    parser.add_argument("--json", action="store_true", help="machine output")
    parser.add_argument("--fail-on-unproven", action="store_true",
                        help="exit 1 when a blocking claim is not settled")
    args = parser.parse_args(argv)
    try:
        payload = adjudicate_round(Path(args.run), Path(args.repo) if args.repo else None,
                                   Path(args.base_tree) if args.base_tree else None)
    except FileNotFoundError as exc:
        print(f"adjudicate: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(render(payload))
    if args.fail_on_unproven and payload["summary"]["certification_blocked"]:
        return 1
    return 0


if __name__ == "__main__":
    from council import require_dispatch

    require_dispatch("adjudicate")
    sys.exit(main())
