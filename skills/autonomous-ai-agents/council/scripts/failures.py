"""Classify why a sample produced no scoreable artefact — from the runner's own words.

The provider outage that cost three good-rung samples read:

    HTTP 404 — no marketplace sellers meet the minimum 89% discount

and left nothing behind but a missing file. `collect` said "not run", which is the same thing it
says for a rung nobody ever attempted. These helpers keep the difference: a runner records every
attempt and the reason it failed, so an outage is visible in the corpus instead of silent.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

#: Ordered: the first match wins, because a provider refusal can also produce a traceback.
PATTERNS: List[Tuple[str, str]] = [
    ("provider_refused", r"HTTP 404|no marketplace sellers|model_not_found|does not exist"),
    ("rate_limited", r"HTTP 429|rate limit|too many requests"),
    ("auth", r"HTTP 40[13]|unauthori[sz]ed|invalid api key|authentication"),
    ("timeout", r"timed out|timeout|TimeoutError"),
    ("connection", r"APIConnectionError|Connection refused|Temporary failure in name resolution"),
    ("unparseable", r"JSONDecodeError|unparseable|Expecting value"),
]


def classify_failure(text: str) -> str:
    """A short machine-readable reason. `unknown` is honest: it means nothing matched."""
    blob = text or ""
    for name, pattern in PATTERNS:
        if re.search(pattern, blob, re.IGNORECASE):
            return name
    return "unknown"


def attempt_record(rc: int, artefact_exists: bool, parsed: bool = False,
                   log_text: str = "", reason: Optional[str] = None) -> Dict[str, Any]:
    """One attempt, as the corpus records it.

    A run can exit nonzero and still have written a complete artefact — observed on a background
    run that exited 1 after writing valid JSON. The artefact is judged by parsing it, not by the
    exit code; the code is recorded so a pattern of nonzero exits stays visible.
    """
    if artefact_exists and parsed:
        return {"rc": rc, "artefact": "parsed", "reason": None}
    if artefact_exists and not parsed:
        return {"rc": rc, "artefact": "unparseable", "reason": "unparseable"}
    return {"rc": rc, "artefact": "missing", "reason": reason or classify_failure(log_text)}


def summarise(attempts: List[Dict[str, Any]]) -> str:
    """One line for a rung's note: how many attempts, and why the last one failed."""
    if not attempts:
        return "not run"
    last = attempts[-1]
    if last.get("artefact") == "parsed":
        return f"succeeded on attempt {len(attempts)}"
    return (f"no sample after {len(attempts)} attempt(s): {last.get('reason') or 'unknown'}"
            f" (rc={last.get('rc')})")
