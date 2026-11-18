"""Severity from evidence: what the tool found decides, not how the reviewer described it.

    from_evidence({"kind": "command", "params": {"argv": ["gitleaks", "detect", ...]}},
                  {"stdout_head": "..."})   ->  ("critical", "credential")

The reviewer's label is advisory and applies only when no rule matches. That is the whole point:
on the nine-run corpus one committed credential came back critical, critical, then medium across
three passes of the same tree, and the caps turn that disagreement into a score swing.

`protocol/severity.json` is the only place a rule is declared, and every rule says why.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
CONTRACT = HERE.parent / "protocol" / "severity.json"

RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}

_table: Optional[Dict[str, Any]] = None


def contract(path: Optional[Path] = None) -> Dict[str, Any]:
    global _table
    if path is None and _table is not None:
        return _table
    data = json.loads(Path(path or CONTRACT).read_text(encoding="utf-8-sig"))
    if path is None:
        _table = data
    return data


def rules() -> Dict[str, Dict[str, Any]]:
    return {rule["tool"]: rule for rule in contract().get("rules", []) if rule.get("tool")}


def content_rules() -> List[Dict[str, Any]]:
    """Rules that key on WHAT was matched rather than which tool matched it.

    A `present` proof cites the line it found; if that line holds a live-key literal, the credential
    is in the tree regardless of the tool used. Without this, a text-based proof of the same defect
    kept the reviewer's label and reintroduced the very flip the table exists to remove.
    """
    return [rule for rule in contract().get("rules", []) if rule.get("excerpt_matches")]


def _tool_of(proof: Optional[Dict[str, Any]]) -> str:
    """The tool a proof invokes, from the executable it names."""
    if not isinstance(proof, dict):
        return ""
    argv = (proof.get("params") or {}).get("argv") or []
    if not argv:
        return ""
    return Path(str(argv[0])).name


def from_evidence(proof: Optional[Dict[str, Any]],
                  observed: Optional[Dict[str, Any]] = None) -> Tuple[Optional[str], str, str]:
    """The severity the evidence implies, the rule that produced it, and its authority.

    Authority is `exact` when the rule names the defect class (a credential literal, a
    SyntaxError) and `floor` when it only knows which tool ran. Exact rules settle severity;
    floor rules can raise it and never lower it.

    Returns (None, "", "") when nothing covers this proof — the caller keeps the reviewer's label.
    """
    text = ""
    # Content rules only for proofs that CITE A LINE. Measured: a `ruff format --check` finding was
    # stamped critical because the formatter echo contained the secret it was reformatting — the
    # rule matched the tool's output, not the finding's subject. A citation has a subject; a
    # command's stdout is whatever the tool happened to print.
    params = (proof or {}).get("params") or {}
    cites_a_line = (proof or {}).get("kind") in ("present", "absent") or "line" in params
    if cites_a_line:
        for rule in content_rules():
            text = text or _observed_text(observed)
            if text and re.search(str(rule["excerpt_matches"]), text):
                return str(rule["severity"]), str(rule["id"]), "exact"

    tool = _tool_of(proof)
    if not tool:
        return None, "", ""
    tool_rule = rules().get(tool)
    if tool_rule is None:
        return None, "", ""
    narrow = tool_rule.get("rules") or []
    if narrow:
        text = text or _observed_text(observed)
        if not any(re.search(rf"\b{re.escape(code)}\b", text) for code in narrow):
            return None, "", ""
    return str(tool_rule["severity"]), str(tool_rule["id"]), str(tool_rule.get("authority") or "floor")


def _observed_text(observed: Optional[Dict[str, Any]]) -> str:
    """Everything a proof observed that could carry the matched content."""
    if not isinstance(observed, dict):
        return ""
    return " ".join(str(observed.get(key) or "")
                    for key in ("excerpt", "stdout_head", "stderr_head", "detail", "text"))


def effective(reviewer: Optional[str], evidence: Optional[str],
              authority: str = "floor") -> Tuple[str, str]:
    """The severity a record should carry, and where it came from.

    Two authorities, because the measurements disagreed about which one is safe:

    * **exact** — the rule named the defect class, so its severity settles the matter. One syntax
      error came back `critical`, `critical`, `high` across three passes of the same tree; naming
      the class removes that.
    * **floor** — the rule only knows which tool ran, so it may raise a reviewer's label and never
      lower it. Applying tool evidence as a plain override downgraded a critical claim to `low`
      because its proof happened to invoke a linter.
    """
    reviewer = (reviewer or "medium").strip().lower()
    if not evidence:
        return reviewer, "reviewer"
    evidence = evidence.strip().lower()
    if authority == "exact":
        return evidence, "evidence"
    if RANK.get(evidence, -1) > RANK.get(reviewer, -1):
        return evidence, "evidence"
    return reviewer, "reviewer"


def agrees(reviewer: Optional[str], evidence: Optional[str]) -> Optional[bool]:
    """None when there is nothing to compare; otherwise whether they are the same severity."""
    if not evidence:
        return None
    return (reviewer or "").strip().lower() == evidence


def main(argv: Optional[list] = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(
        prog="severity",
        description=(__doc__ or "").splitlines()[0] if (__doc__ or "").strip() else None)
    parser.add_argument("--list", action="store_true", help="print the rule table")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.list:
        if args.json:
            print(json.dumps(contract(), indent=2))
        else:
            for rule in contract().get("rules", []):
                subject = rule.get("tool") or f"content:{rule.get('excerpt_matches')}"
                print(f"  {subject:24s} -> {rule['severity']:8s} ({rule['id']})")
                print(f"      {rule['why']}")
        return 0
    parser.print_help()
    return 2


if __name__ == "__main__":
    # Not a program: reached through `council <verb>`. See council.py.
    from council import require_dispatch

    require_dispatch("severity")
    raise SystemExit(main())
