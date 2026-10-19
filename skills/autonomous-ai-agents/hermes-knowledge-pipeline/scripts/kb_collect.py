#!/usr/bin/env python3
"""kb_collect.py - cron --script pre-run collector for the nightly KB distill job.

Reads $HERMES_HOME/state.db (the canonical session store), finds sessions that
ended after the stored cursor, and prints a COMPACT digest for the agent to
work from. Advances nothing itself - the agent/job owns the cursor, so a failed
run does not lose sessions.

Two filters exist because the naive query feeds the pipeline its own output:

* `source != 'cron'` drops sessions created by cron jobs. Without it, each night
distils the previous night's distillation run - a self-referential loop that
  grows the queue forever. Subagent sessions inherit their parent's source
  ('desktop'), so real research is still captured.
* Sessions already cited by the vault are dropped, so an interrupted run that
  wrote proposals but never advanced the cursor cannot duplicate them.

Idle output is a STABLE sentinel (never empty): --monitor-script suppresses the
agent run only when stdout is byte-identical to the previous tick, and a
non-empty -> empty transition is itself a change.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

# A batch of 8 was empirically too large: the cron run was cut off by the 3-minute hard
# interrupt after writing proposals but before the bookkeeping. A batch that reliably
# finishes beats one that reliably gets truncated. Raise only with a measured run time.
MAX_SESSIONS = int(os.environ.get("KB_DISTILL_MAX_SESSIONS", "3"))
MIN_MESSAGES = int(os.environ.get("KB_DISTILL_MIN_MESSAGES", "6"))

# A proposal records its sessions in two places, `proposed_by:` and `sources: [session:<id>]`;
# both are read, because one proposal can cover several sessions and vice versa.
PROPOSED_BY_RE = re.compile(r"^proposed_by:\s*(\S+)\s*$", re.MULTILINE)
SESSION_REF_RE = re.compile(r"session:([0-9A-Za-z_][0-9A-Za-z_.-]*)")


def distilled_session_ids(root: Path) -> set[str]:
    """Session ids already represented in the vault.

    The vault is the authoritative record of what has been distilled; the cursor is only
    an optimisation. Relying on the cursor alone means a run interrupted between "write
    proposals" and "advance cursor" re-proposes everything on the next tick - which is
    exactly what happened the first time this pipeline ran against a real session store.
    Reading the vault makes replay harmless and keeps the pipeline idempotent by
    construction rather than by instruction-following.
    """
    ids: set[str] = set()
    for d in ("inbox", "entities", "concepts", "comparisons", "queries"):
        base = root / d
        if not base.is_dir():
            continue
        for p in base.rglob("*.md"):
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            ids.update(PROPOSED_BY_RE.findall(text))
            ids.update(SESSION_REF_RE.findall(text))
    return {i for i in ids if i}


def hermes_home() -> Path:
    return Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))


def cursor_path() -> Path:
    root = os.environ.get("HERMES_KB_ROOT") or os.environ.get("WIKI_PATH") or "."
    return Path(root) / "_meta" / "distill-cursor.json"


def load_cursor() -> float:
    try:
        return float(json.loads(cursor_path().read_text(encoding="utf-8"))["last_ended_at"])
    except Exception:
        return 0.0


def main() -> int:
    db = hermes_home() / "state.db"
    if not db.is_file():
        print(f"kb_collect: no session store at {db}", file=sys.stderr)
        return 1
    since = load_cursor()
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    rows = con.execute(
        """SELECT id, title, display_name, cwd, message_count, tool_call_count,
                  started_at, COALESCE(ended_at, last_activity_at), tool_names
             FROM sessions
            WHERE COALESCE(ended_at, last_activity_at) > ?
              AND COALESCE(message_count,0) >= ?
              AND COALESCE(hidden,0) = 0
              AND COALESCE(source,'') != 'cron'
            ORDER BY COALESCE(ended_at, last_activity_at) ASC
            LIMIT ?""",
        (since, MIN_MESSAGES, MAX_SESSIONS * 4),
    ).fetchall()

    # Drop sessions the vault already covers, then apply the batch cap.
    done = distilled_session_ids(cursor_path().parent.parent)
    rows = [r for r in rows if r[0] not in done][:MAX_SESSIONS]

    if not rows:
        # STABLE sentinel, not empty output: an empty string would differ from a
        # non-empty one and fire one wasted agent run.
        print(f"KB DISTILL: idle (cursor {int(since)})" if since else "KB DISTILL: idle (no cursor)")
        return 0

    out = [f"KB DISTILL QUEUE: {len(rows)} session(s) since "
           f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(since)) if since else 'the beginning'}",
           f"hermes_home: {hermes_home()}",
           f"kb_root: {cursor_path().parent.parent.as_posix()}"]
    newest = since
    for (sid, title, disp, cwd, nmsg, ntool, started, ended, tools) in rows:
        out.append(
            f"\n- session_id: {sid}\n"
            f"  title: {title or disp or '(untitled)'}\n"
            f"  ended: {time.strftime('%Y-%m-%d %H:%M', time.localtime(ended))}\n"
            f"  cwd: {cwd or '-'}\n"
            f"  messages: {nmsg}  tool_calls: {ntool}\n"
            f"  tools_used: {(tools or '-')[:300]}"
        )
        newest = max(newest, ended)
    out.append(
        "\nINSTRUCTIONS:\n"
        "1. For each session above, read it (messages table: SELECT role, content, tool_name "
        "FROM messages WHERE session_id=? ORDER BY id) or use session_search.\n"
        "2. Extract only durable, non-obvious knowledge - things a future session would "
        "otherwise re-derive or get wrong. Skip narration, one-off task state and anything "
        "already covered by an existing page (search the vault first).\n"
        "3. Write proposals to <kb_root>/inbox/<slug>.md with status: proposed, "
        "proposed_by: <session_id>, and tags from SCHEMA.md's taxonomy.\n"
        "4. Do NOT touch canonical directories (entities/ concepts/ comparisons/ queries/), "
        "index.md, raw/, or SCHEMA.md. The inbox gate exists so a human ratifies.\n"
        "5. Append one line per proposal to <kb_root>/log.md: "
        "'## [YYYY-MM-DD] propose | <title>'\n"
        "6. If nothing durable was found, write no files - an empty night is a valid result.\n"
        "7. Advance the cursor ONLY after the proposals are written: "
        f'{{"last_ended_at": {newest}}} -> {cursor_path().as_posix()}'
    )
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
