#!/usr/bin/env python3
"""The run's claim ladder: what this review's evidence supports, and what it does not.

A score is not a claim about the world. "Aggregate 87, satisfied" says the reviewers and the
deterministic gate agreed about the diff; it does not say the page was loaded, the CI pipeline ran,
or that the branch may be merged. Reports blur that line by default — a clean table reads as
"this is fine" — and the blend of observed and inferred is where a review tells its most expensive
lie.

So each run gets a ladder: rungs of evidence, in order, each either ALLOWED (its evidence is
present) or BLOCKED (with the reason it is not, and what would open it). The state is derived from
files, never asserted: meta.json, probes.json, the reviewer files, the calibration, the CI receipt,
the publish receipt. Nothing here is a new source of truth; it is the projection of what the run
already recorded.

The ladder, and why it stops where it does:

    run_recorded         the harness wrote what it reviewed (sha, stacks, mode)
    probes_observed      the deterministic probes ran AND parsed, for every tool this stack expects
    runtime_observed     the page was loaded (only when the run's stacks include `web`)
    council_complete     every dimension reported, nothing unparseable — a partial council is not a verdict
    gate_recomputed      the number came back out of the deterministic gate, not out of a self-report
    verdict_calibrated   the threshold is the calibrated one, not a CLI override
    ci_observed          a CI result for the head SHA was observed (a receipt, not a memory)
    merge_ready          verdict satisfied AND CI observed
    published            the verdict reached the pull request, and the write was read back

`merge_ready` without `ci_observed` is the exact sentence this module exists to make impossible to
print by accident: a review that never saw CI may say "satisfied", and may not say "merge ready".

    council claims --run DIR              # the ladder, for a human
    council claims --run DIR --json       # the same, for a caller
    council claims --run DIR --record-ci --sha <sha> --conclusion success --url <url>
    council claims --run DIR --record-published --url <url> --id <n> --sha <sha>
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SCHEMA_VERSION = "review_council_claims/v1"

#: Ordered. Each rung may only be claimed when every rung before it also holds.
LADDER: Tuple[str, ...] = (
    "run_recorded",
    "probes_observed",
    "runtime_observed",
    "council_complete",
    "gate_recomputed",
    "verdict_calibrated",
    "ci_observed",
    "merge_ready",
    "published",
)

LABELS: Dict[str, str] = {
    "run_recorded": "run recorded",
    "probes_observed": "probes observed",
    "runtime_observed": "runtime observed",
    "council_complete": "council complete",
    "gate_recomputed": "gate recomputed",
    "verdict_calibrated": "verdict calibrated",
    "ci_observed": "CI observed",
    "merge_ready": "merge ready",
    "published": "published",
}

BLOCK_REASONS: Dict[str, str] = {
    "run_recorded": "the run has no meta.json, or it records no target_sha — there is nothing to attach a claim to",
    "probes_observed": "probe output is absent, or an expected tool did not run and parse for this stack",
    "runtime_observed": "the page was not loaded: no browser driver, or the runtime lane did not run",
    "council_complete": "a dimension did not report, or a reviewer file did not parse — a partial council cannot certify anything",
    "gate_recomputed": "the gate could not produce a verdict from the reviewer files",
    "verdict_calibrated": "the threshold is a CLI override, not the calibrated one",
    "ci_observed": (
        "no CI result for this run's head SHA was observed. "
        "Record one with `council claims --record-ci` once the pipeline has actually finished"
    ),
    "merge_ready": "merge-readiness needs a satisfied verdict AND an observed CI result",
    "published": "the verdict was never posted to a pull request, or the write was not read back",
}

CLAIM_BOUNDARY = (
    "A satisfied verdict is a statement about the diff, derived by the deterministic gate from the "
    "reviewer files. It is not observed execution, a passing CI run, merge-readiness, or a merge."
)

RECEIPT_DIR = Path(".review-council")
CI_RECEIPT = RECEIPT_DIR / "ci-receipt.json"
PUBLISH_RECEIPT = RECEIPT_DIR / "published.json"

DIMENSIONS = ("security", "performance", "readability", "correctness", "architecture")


# --- the run's own files ------------------------------------------------------


def _read_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None


ROUND_PATTERN = re.compile(r"^round-(\d+)$")


def _round_number(path: Path) -> int:
    """The number in ``round-N``, or -1.

    Sorting round directories by NAME is wrong the moment a run reaches round 10: ``round-10`` sorts
    before ``round-2``, so "the latest round" silently became round 9. A run that is scored on the
    wrong round is a wrong number with no error anywhere, which is the failure this repository keeps
    paying for.
    """
    match = ROUND_PATTERN.match(path.name)
    return int(match.group(1)) if match else -1


def locate(pointed_at: Path) -> Tuple[Path, Path]:
    """``(run_root, score_dir)`` for whatever the caller named.

    A run has two shapes in this repository: the loop writes rounds under a run root
    (`meta.json`, `probes.json`, `outcome.json`, `round-N/`), and `gate`/`pr` are handed a round
    directory that carries the dimension files. Both are legitimate entry points, so the caller's
    path is resolved rather than constrained.

    Deterministic by construction: rounds sort numerically, and the newest round WITH reviewer files
    wins. A round that holds no reviewer output is not a candidate at all, so a half-written round
    cannot displace the one that was scored.
    """
    target = pointed_at.resolve()

    def newest_with_reviews(candidates: List[Path]) -> Optional[Path]:
        scored = [p for p in candidates if any((p / f"{d}.json").is_file() for d in DIMENSIONS)]
        return max(scored, key=_round_number) if scored else None

    rounds = sorted((p for p in target.glob("round-*") if p.is_dir()), key=_round_number)
    if (target / "meta.json").is_file():
        return target, newest_with_reviews(rounds) or target
    if rounds:
        return target, newest_with_reviews(rounds) or rounds[-1]
    if (target.parent / "meta.json").is_file():
        return target.parent, target
    return target, target


def _meta(run_root: Path, score_dir: Path) -> Tuple[Dict[str, Any], str]:
    """``(meta, conflict)``. Two meta.json that disagree are a conflict, never a silent pick.

    The rejected sha is returned as a non-empty *conflict* string so the first rung can name it.
    Reading the run root first and shrugging is how a claim ends up attached to the wrong commit.
    """
    root_payload = _read_json(run_root / "meta.json")
    round_payload = _read_json(score_dir / "meta.json") if score_dir != run_root else None
    if isinstance(root_payload, dict):
        if isinstance(round_payload, dict):
            a = str(root_payload.get("target_sha") or "").strip()
            b = str(round_payload.get("target_sha") or "").strip()
            if a and b and a != b:
                return root_payload, (f"two meta.json disagree: the run root says {a[:12]}, "
                                      f"{score_dir.name} says {b[:12]}")
        return root_payload, ""
    if isinstance(round_payload, dict):
        return round_payload, ""
    return {}, ""


def _probes(run_root: Path, score_dir: Path) -> Tuple[List[Dict[str, Any]], str]:
    """``(rows, state)`` where state is ``absent``, ``empty``, or ``ok``.

    Absent and empty are different facts: no file means the probes were never recorded, an empty
    array means something asked for them and got nothing back. Reporting both as "absent" hides a
    broken probe runner behind a missing file.
    """
    for candidate in (run_root / "probes.json", score_dir / "probes.json"):
        if not candidate.is_file():
            continue
        payload = _read_json(candidate)
        if payload is None:
            return [], "unreadable"
        if isinstance(payload, list):
            rows = [p for p in payload if isinstance(p, dict)]
            return rows, ("ok" if rows else "empty")
        return [], "malformed"
    return [], "absent"


# --- the rungs ----------------------------------------------------------------


def _rung_run_recorded(meta: Dict[str, Any], conflict: str = "") -> Tuple[bool, str, List[Dict[str, str]]]:
    if conflict:
        return False, conflict, []
    sha = str(meta.get("target_sha") or "").strip()
    if not sha:
        return False, BLOCK_REASONS["run_recorded"], []
    return True, "", [{"kind": "meta.json", "status": "observed", "source": f"target_sha {sha}"}]


def expected_tools(stacks: List[str], benchmark: Dict[str, Dict[str, List[str]]]) -> List[str]:
    """Every tool the gate expects for these stacks, across all dimensions, deduped in order."""
    seen: List[str] = []
    for dimension in benchmark.values():
        for stack in stacks:
            for tool in dimension.get(stack, []):
                if tool not in seen:
                    seen.append(tool)
    return seen


PROBE_STATE_REASONS = {
    "absent": "no probes.json in this run — the deterministic probes were never recorded",
    "unreadable": "probes.json did not parse, so no probe result can be relied on",
    "malformed": "probes.json is not a list of probe results",
    "empty": "probes.json is empty: the probe runner recorded nothing, which is not the same as clean",
}


def _rung_probes_observed(probes: List[Dict[str, Any]], state: str, stacks: List[str],
                          benchmark: Dict[str, Dict[str, List[str]]]) -> Tuple[bool, str, List[Dict[str, str]]]:
    """Fail closed on three separate vacuities: no file, no rows, and no stacks.

    An empty expected-tools set passes every membership test ever written. A run whose `meta.json`
    records no stacks therefore has nothing to measure and nothing to be proud of, so it blocks here
    rather than sailing through `all([]) is True`.
    """
    if state != "ok":
        return False, PROBE_STATE_REASONS.get(state, PROBE_STATE_REASONS["absent"]), []
    if not stacks:
        return False, ("the run recorded no stacks in meta.json, so no tool was expected and none can "
                       "be shown to have run — re-run the harness, which records them"), []
    ran = {str(p.get("tool") or "") for p in probes if p.get("ran") and p.get("parsed", True)}
    expected = expected_tools(stacks, benchmark)
    missing = [t for t in expected if t not in ran]
    evidence = [{"kind": "probes.json", "status": "observed",
                 "source": f"{len(ran)} probes ran; stacks {', '.join(stacks)}"}]
    if missing:
        return (
            False,
            f"these expected tools did not run and parse: {', '.join(sorted(missing))} — "
            "beta records how much of the score was deterministic, and these are the gaps",
            evidence,
        )
    if not expected:
        evidence[0]["status"] = "not applicable"
        evidence[0]["source"] = f"stacks {', '.join(stacks)} expect no tool"
    return True, "", evidence


def _rung_runtime_observed(probes: List[Dict[str, Any]], stacks: List[str]) -> Tuple[bool, str, List[Dict[str, str]]]:
    browser = next((p for p in probes if p.get("tool") == "browser"), None)
    if browser is None:
        return False, (
            "no `browser` probe result: the runtime lane did not run for this review. "
            "Run `council probes browser --repo .`, or set COUNCIL_WEB_URL for a served app"
        ), []
    if not browser.get("ran"):
        return False, str(browser.get("note") or BLOCK_REASONS["runtime_observed"]), [
            {"kind": "probes.json", "status": "not observed", "source": "browser probe did not run"}
        ]
    observed = [
        {"kind": "dom", "status": "observed", "source": _artifact(browser.get("note"), "dom=")},
        {"kind": "screenshot", "status": "observed", "source": _artifact(browser.get("note"), "screenshot=")},
    ]
    if browser.get("parsed") is False:
        return False, "the page was loaded but produced no DOM to inspect", observed
    signal = browser.get("signal")
    if isinstance(signal, (int, float)) and signal < 100:
        return (
            False,
            f"the page was loaded and reported {int(100 - signal)} point(s) of runtime findings — "
            "see the browser findings; an observed failure is not an observation that it works",
            observed,
        )
    return True, "", observed


def _artifact(note: Any, prefix: str) -> str:
    """The path a browser probe reported, e.g. ``dom=`` out of ``…; dom=/tmp/x/dom.html …``.

    One token only: the note carries the DOM and the screenshot on the same segment, so taking the
    rest of the segment would hand back both paths as if they were one.
    """
    for token in re.split(r"[\s;]+", str(note or "")):
        if token.startswith(prefix):
            value = token[len(prefix):].strip()
            return value
    return ""


def _rung_council_complete(result: Optional[Dict[str, Any]]) -> Tuple[bool, str, List[Dict[str, str]]]:
    if not result:
        return False, BLOCK_REASONS["council_complete"], []
    if result.get("status") == "error":
        return False, str(result.get("reason") or BLOCK_REASONS["council_complete"]), []
    missing = list(result.get("missing_files") or [])
    invalid = list(result.get("invalid") or [])
    present = list(result.get("reviews_present") or [])
    evidence = [{"kind": "reviewer files", "status": "observed",
                 "source": f"{len(present)}/5 dimensions: {', '.join(present) or 'none'}"}]
    if missing or invalid:
        return False, (f"missing: {', '.join(missing) or 'none'}; "
                       f"unparseable: {'; '.join(invalid) or 'none'}"), evidence
    return True, "", evidence


def _rung_gate_recomputed(result: Optional[Dict[str, Any]],
                          disagreement: str = "") -> Tuple[bool, str, List[Dict[str, str]]]:
    if disagreement:
        return False, disagreement, []
    if not result or result.get("aggregate") is None:
        return False, BLOCK_REASONS["gate_recomputed"], []
    return True, "", [{"kind": "gate", "status": "observed",
                       "source": f"aggregate {result['aggregate']:.2f} recomputed from the reviewer files"}]


def _rung_verdict_calibrated(result: Optional[Dict[str, Any]],
                             calibration: Optional[Dict[str, Any]]) -> Tuple[bool, str, List[Dict[str, str]]]:
    if not result or not result.get("calibrated"):
        return False, BLOCK_REASONS["verdict_calibrated"], []
    note = json.dumps(calibration or {})
    status = "provisional" if "PROVISIONAL" in note.upper() else "observed"
    return True, "", [{"kind": "calibration.json", "status": status,
                       "source": f"threshold {float(result.get('threshold') or 0):g} from scripts/calibration.json"}]


def _receipt_mismatch(receipt: Dict[str, Any], meta: Dict[str, Any], what: str) -> str:
    """The reason a receipt does not belong to this run, or "" when it does.

    A receipt with NO sha used to pass the equality test, because an empty string is falsy: that let
    a CI result for an unknown commit open this run's rung. Absent evidence is not matching
    evidence, so a receipt must NAME the commit when the run does.
    """
    sha = str(meta.get("target_sha") or "").strip()
    if not sha:
        return ""  # the first rung already blocked; nothing to compare against
    recorded = str(receipt.get("sha") or "").strip()
    if not recorded:
        return f"the {what} receipt names no commit, so it cannot be evidence for {sha[:12]}"
    if recorded != sha:
        return (f"the {what} receipt is for {recorded[:12]}, this run reviewed {sha[:12]} — "
                "a result for a different commit is not evidence for this one")
    return ""


def _rung_ci_observed(run_root: Path, meta: Dict[str, Any]) -> Tuple[bool, str, List[Dict[str, str]]]:
    receipt = _read_json(run_root / CI_RECEIPT)
    if not isinstance(receipt, dict):
        return False, BLOCK_REASONS["ci_observed"], []
    mismatch = _receipt_mismatch(receipt, meta, "CI")
    if mismatch:
        return False, mismatch, []
    conclusion = str(receipt.get("conclusion") or "").strip()
    if not conclusion:
        return False, "the CI receipt records no conclusion", []
    evidence = [{"kind": "ci receipt", "status": conclusion, "source": str(receipt.get("url") or "no url")}]
    if conclusion != "success":
        return False, f"CI concluded `{conclusion}`, which is not a pass", evidence
    return True, "", evidence


def _rung_published(run_root: Path, meta: Dict[str, Any]) -> Tuple[bool, str, List[Dict[str, str]]]:
    receipt = _read_json(run_root / PUBLISH_RECEIPT)
    if not isinstance(receipt, dict):
        return False, BLOCK_REASONS["published"], []
    url = str(receipt.get("url") or "").strip()
    if not url:
        return False, "the publish receipt records no URL — a write that was not read back is not observed", []
    mismatch = _receipt_mismatch(receipt, meta, "publish")
    if mismatch:
        return False, mismatch, []
    return True, "", [{"kind": "publish receipt", "status": "observed", "source": url}]


# --- the ladder ---------------------------------------------------------------


def _fingerprint(result: Optional[Dict[str, Any]]) -> Tuple[Any, ...]:
    """What two gate results must agree on to be the same verdict.

    Deliberately narrow: the status, the aggregate and the threshold. Everything else in the result
    is derived from these three, and comparing the whole dict would pin fields a future gate is
    entitled to add.
    """
    if not result:
        return ()
    aggregate = result.get("aggregate")
    return (result.get("status"), round(float(aggregate), 2) if isinstance(aggregate, (int, float)) else aggregate,
            result.get("threshold"))


def build(run_dir: Path, result: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Every rung's state for *run_dir*, derived from what the run recorded.

    The gate is ALWAYS re-run here, even when *result* is passed in. A ladder that trusts its
    caller's arithmetic is a ladder that can be opened by feeding it the right dict — and the whole
    point is that these claims are derived, not asserted. A passed result that disagrees with the
    recompute is reported as a blocked rung naming both numbers, never silently preferred.

    Pure with respect to the tree: reads files, writes nothing, and the payload carries no clock, so
    two calls on the same tree produce byte-identical output.
    """
    run_root, score_dir = locate(run_dir)
    meta, conflict = _meta(run_root, score_dir)
    probes, probe_state = _probes(run_root, score_dir)
    stacks = [str(s) for s in (meta.get("stacks") or [])]

    fresh = _gate(score_dir, stacks)
    disagreement = ""
    if result is not None and _fingerprint(result) != _fingerprint(fresh):
        disagreement = (f"the caller passed verdict {_fingerprint(result)} and this directory "
                        f"recomputes to {_fingerprint(fresh)} — the ladder reports the recompute")

    benchmark = _benchmark()
    calibration = _read_json(Path(__file__).resolve().parent / "calibration.json")

    checks: Dict[str, Tuple[bool, str, List[Dict[str, str]]]] = {
        "run_recorded": _rung_run_recorded(meta, conflict),
        "probes_observed": _rung_probes_observed(probes, probe_state, stacks, benchmark),
        "runtime_observed": _rung_runtime_observed(probes, stacks),
        "council_complete": _rung_council_complete(fresh),
        "gate_recomputed": _rung_gate_recomputed(fresh, disagreement),
        "verdict_calibrated": _rung_verdict_calibrated(fresh, calibration),
        "ci_observed": _rung_ci_observed(run_root, meta),
        "published": _rung_published(run_root, meta),
    }
    # `merge_ready` is not its own evidence: it is the conjunction.
    checks["merge_ready"] = (
        checks["ci_observed"][0] and bool(fresh) and fresh.get("status") == "satisfied",
        BLOCK_REASONS["merge_ready"],
        [],
    )

    applicable = _applicable(checks, stacks)

    allowed: List[str] = []
    blocked: List[Dict[str, str]] = []
    evidence: List[Dict[str, str]] = []
    blocked_seen = False
    for rung in LADDER:
        if rung not in applicable:
            continue
        ok, reason, items = checks.get(rung, (False, "unknown rung", []))
        if not blocked_seen and ok:
            allowed.append(rung)
            evidence.extend(items)
        else:
            blocked_seen = True
            blocked.append({"claim": rung, "reason": reason or BLOCK_REASONS.get(rung, "")})

    state = allowed[-1] if allowed else "nothing_observed"
    return {
        "schema_version": SCHEMA_VERSION,
        "run": run_root.resolve().name,
        "claim_state": state,
        "claim_label": LABELS.get(state, state),
        "allowed_claims": allowed,
        "blocked_claims": blocked,
        "not_applicable": [r for r in LADDER if r not in applicable],
        "evidence": evidence,
        # The RECOMPUTED verdict, never the caller's: reporting the passed-in dict here would let a
        # caller see its own number echoed back while the rungs were judged on the real one.
        "verdict": {
            "status": (fresh or {}).get("status"),
            "aggregate": (fresh or {}).get("aggregate"),
            "threshold": (fresh or {}).get("threshold"),
        },
        "claim_boundary": CLAIM_BOUNDARY,
        "next_action": blocked[0]["claim"] if blocked else "",
        "safe_summary": _summary(state, blocked),
    }


def _applicable(checks: Dict[str, Any], stacks: List[str]) -> List[str]:
    """`runtime_observed` exists only for a run whose stacks include a page."""
    return [r for r in LADDER if r != "runtime_observed" or "web" in stacks]


def _summary(state: str, blocked: List[Dict[str, str]]) -> str:
    label = LABELS.get(state, state)
    if blocked:
        nxt = blocked[0]
        return f"Evidence reaches `{label}`. Blocked at `{nxt['claim']}`: {nxt['reason'].splitlines()[0]}"
    return f"Evidence reaches `{label}`, the top of the ladder for this run."


def _benchmark() -> Dict[str, Dict[str, List[str]]]:
    """`STACK_TOOLS` from score_reviews, loaded by path: the gate's own table, not a copy."""
    score = _load("score_reviews")
    return dict(getattr(score, "STACK_TOOLS", {}) or {})


def _gate(score_dir: Path, stacks: List[str]) -> Optional[Dict[str, Any]]:
    """The gate's verdict for this directory, or an error result that names why it could not run.

    Returning ``None`` on a failure would make "the gate crashed" indistinguishable from "the gate
    ran and found nothing", and those are different claims. The error shape is the gate's own
    (`status: "error"`), so downstream rungs treat it as the non-verdict it is.
    """
    try:
        score = _load("score_reviews")
        return score.evaluate(score_dir, score.calibrated_threshold(), stacks=stacks or None)
    except Exception as exc:  # noqa: BLE001 - a ladder must render even when the gate cannot
        return {"status": "error", "reason": f"the deterministic gate could not run: "
                                             f"{type(exc).__name__}: {exc}", "aggregate": None}


_MODULES: Dict[str, Any] = {}


def _load(name: str):
    """Load a sibling module by path, once per process.

    The CLI, `pr.py` and the tests reach this file from different roots, so a plain ``import`` would
    depend on ``sys.path``. The cache matters too: re-executing `score_reviews` per rung would make
    the ladder's cost depend on how many rungs are blocked.
    """
    if name in _MODULES:
        return _MODULES[name]
    import importlib.util

    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_claims_{name}", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    _MODULES[name] = module
    return module


# --- receipts: the only writes this module makes --------------------------------


SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _refuse_sha(value: str, what: str) -> str:
    """Refuse anything that is not a full lowercase commit id, naming what was given.

    A receipt keyed to a SHORT sha can never match the run's 40-character target, so it would sit in
    the tree looking like evidence and opening nothing. Refusing at write time names the mistake
    where it is cheap; normalising here would hide it.
    """
    if SHA_RE.match(value):
        return ""
    return (f"{what}: {value!r} is not a full lowercase 40-character commit id. "
            "Paste the sha the pipeline ran against, exactly as git printed it.")


def record_ci(run_dir: Path, sha: str, conclusion: str, url: str = "") -> Path:
    """Record an OBSERVED CI result for this run's head SHA.

    The caller observed it: this is a receipt, not a probe. It is keyed to a sha so a result for
    another commit cannot open this run's rung.
    """
    invalid = _refuse_sha(sha.strip(), "record-ci")
    if invalid:
        raise ValueError(invalid)
    if not conclusion.strip():
        raise ValueError("record-ci: --conclusion is required (a receipt with no verdict is not evidence)")
    run_root, _ = locate(run_dir)
    path = run_root / CI_RECEIPT
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "sha": sha.strip(),
        "conclusion": conclusion.strip(),
        "url": url.strip(),
        "observed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")
    return path


def record_published(run_dir: Path, url: str, comment_id: Optional[int] = None, sha: str = "") -> Path:
    """Record that the verdict reached the pull request, with the URL that was read back."""
    invalid = _refuse_sha(sha.strip(), "record-published") if sha.strip() else ""
    if invalid:
        raise ValueError(invalid)
    if not url.strip():
        raise ValueError("record-published: --url is required (the address that was read back)")
    run_root, _ = locate(run_dir)
    path = run_root / PUBLISH_RECEIPT
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "url": url.strip(),
        "comment_id": comment_id,
        "sha": sha.strip(),
        "observed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")
    return path


# --- rendering ----------------------------------------------------------------


def render(payload: Dict[str, Any]) -> str:
    lines = [f"claims — {payload['run']}", f"  state     : {payload['claim_label']}"]
    lines.append(f"  verdict   : {(payload['verdict']['status'] or 'none')} "
                 f"({payload['verdict']['aggregate']}, threshold {payload['verdict']['threshold']})")
    lines.append("  allowed:")
    for rung in payload["allowed_claims"] or ["(nothing is observed)"]:
        lines.append(f"    + {LABELS.get(rung, rung)}")
    if payload["blocked_claims"]:
        lines.append("  blocked:")
        for item in payload["blocked_claims"]:
            lines.append(f"    - {LABELS.get(item['claim'], item['claim'])}: {item['reason']}")
    if payload["not_applicable"]:
        lines.append(f"  not applicable: {', '.join(payload['not_applicable'])}")
    lines.append(f"  boundary  : {payload['claim_boundary']}")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="claims.py", description="The run's claim ladder: what its evidence supports.")
    parser.add_argument("--run", required=True, help="run directory (or its round-<n> child)")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--record-ci", action="store_true",
                        help="record an OBSERVED CI result for this run (requires --sha, --conclusion)")
    parser.add_argument("--record-published", action="store_true",
                        help="record that the verdict was posted and read back (requires --url)")
    parser.add_argument("--sha", default="", help="the commit the result belongs to")
    parser.add_argument("--conclusion", default="", help="CI conclusion, e.g. success / failure")
    parser.add_argument("--url", default="", help="URL of the CI run, or of the posted comment")
    parser.add_argument("--id", type=int, default=None, help="posted comment id, when recording a publish")
    parser.add_argument(
        "--require", choices=LADDER, default=None,
        help="exit 1 unless this rung is ALLOWED. The default is stricter: any blocked rung exits 1, "
             "which is right for a human reading the ladder and wrong for a pipeline that only means "
             "to require, say, merge_ready.")
    args = parser.parse_args(argv)

    run_dir = Path(args.run).expanduser()
    if not run_dir.is_dir():
        print(f"claims: not a directory: {run_dir}", file=sys.stderr)
        return 2

    if args.record_ci:
        if not args.sha or not args.conclusion:
            parser.error("--record-ci needs --sha and --conclusion")
        try:
            path = record_ci(run_dir, args.sha, args.conclusion, args.url)
        except ValueError as exc:
            print(f"claims: {exc}", file=sys.stderr)
            return 2
        print(f"claims: recorded CI for {args.sha[:12]} as {args.conclusion} -> {path}")
        return 0
    if args.record_published:
        if not args.url:
            parser.error("--record-published needs --url")
        try:
            path = record_published(run_dir, args.url, args.id, args.sha)
        except ValueError as exc:
            print(f"claims: {exc}", file=sys.stderr)
            return 2
        print(f"claims: recorded the published verdict -> {path}")
        return 0

    payload = build(run_dir)
    print(json.dumps(payload, indent=2) if args.json else render(payload))
    return _exit_code(payload, args.require)


def _exit_code(payload: Dict[str, Any], required: Optional[str]) -> int:
    """0 when the asked-for level is reached, 1 otherwise.

    With no `--require`, any blocked rung is a 1: the default is the strict reading, because a
    caller who wanted a specific level can say so, and a caller who did not should not be told a
    partial ladder is a pass.
    """
    if required:
        return 0 if required in payload.get("allowed_claims", []) else 1
    return 0 if not payload.get("blocked_claims") else 1


if __name__ == "__main__":
    # Not a program: reached through `council claims`. See council.py.
    from council import require_dispatch

    require_dispatch("claims")
    sys.exit(main())
