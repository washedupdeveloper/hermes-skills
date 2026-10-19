#!/usr/bin/env python3
"""kb_sessions.py - export Hermes sessions into the vault so a base can show what
 the agent has actually been doing.

The vault records *knowledge*; it does not record *activity*. That is the missing
half of the supervisor surface: the pages say what is known, nothing said what the
agent did to know it. This writes one note per session into `sessions/`, carrying
metadata `state.db` already tracks - model, wall-clock timing, message and tool
counts, tokens (including reasoning tokens), cost, and how the session ended - so a
Bases view can sort and filter the agent's own history like any other corpus.

    kb_sessions.py                # write sessions/*.md; silent when nothing changed
    kb_sessions.py --print        # show what would change; write nothing
    kb_sessions.py --limit 5      # newest N sessions only

Read-only on state.db, and no message content is copied: the transcript stays in the
database, and the note carries only the title Hermes already derived. Notes are
**generated and machine-local** - `sessions/` is gitignored and is deliberately NOT
in kb_reindex's PAGE_DIRS, so these notes never enter the knowledge corpus, the lint
report or the repo. They exist to be looked at.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import kb_reindex as kb  # noqa: E402

SESSIONS_DIR = "sessions"

# Only fields with real coverage in state.db: cwd/git_branch/git_repo_root are NULL on every
# session on this host, and tool_names carries an opaque hash, so including them would put
# permanently-empty columns on the board.
FIELDS = """id source profile_name model title title_source started_at ended_at
            last_activity_at last_activity_description end_reason message_count
            tool_call_count api_call_count input_tokens output_tokens
            reasoning_tokens cache_read_tokens estimated_cost_usd cost_status
            archived pinned hidden""".split()


def default_db() -> Path:
    home = os.environ.get("HERMES_HOME")
    base = Path(home) if home else Path.home() / ".hermes"
    return base / "state.db"


def pages_citing_sessions(root: Path) -> dict[str, list[str]]:
    """session id -> the vault pages that cite it.

    This is the other half of the session/knowledge link. A page names its session in
    `sources: [session:<id>]`, so the vault already records which session produced it -
    but only in one direction, and only inside frontmatter. Inverting it here lets each
    session note say what came out of it, which is what makes a session findable from
    the knowledge and vice versa.

    Reuses kb_reindex's parser rather than re-reading frontmatter, so there is exactly
    one implementation of "what does this page say".
    """
    out: dict[str, list[str]] = {}
    try:
        pages, _archived = kb.build(root)
    except Exception:
        return out
    for slug, meta in pages.items():
        if meta.get("dir") == SESSIONS_DIR:
            continue
        for src in meta.get("sources") or []:
            s = str(src).strip()
            if s.startswith("session:"):
                out.setdefault(s[len("session:"):].strip(), []).append(slug)
    return out


def iso(ts) -> str:
    if not ts:
        return ""
    try:
        return dt.datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%dT%H:%M:%S")
    except (ValueError, OSError, TypeError):
        return ""


def read_sessions(db: Path) -> list[dict]:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            f"SELECT {', '.join(FIELDS)} FROM sessions ORDER BY started_at DESC"
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def build_note(row: dict, produced: list[str] | None = None) -> tuple[str, str]:
    sid = str(row["id"])
    started, ended = row.get("started_at"), row.get("ended_at")
    last = row.get("last_activity_at")
    # An open session has no ended_at; that is state, not a missing value.
    state = "closed" if ended else "open"
    end_ref = ended or last
    duration_min = int((end_ref - started) / 60) if (started and end_ref) else 0

    title = str(row.get("title") or "").strip() or f"session {sid}"
    src = str(row.get("source") or "")
    # Who did the work: top-level session, delegated subagent, or scheduled job - the axis
    # a supervisor wants (did the agent do it, delegate it, or was it unattended).
    if src == "cron":
        kind = "cron"
    elif title.lower().startswith("subagent"):
        kind = "subagent"
    else:
        kind = "main"
    last_desc = str(row.get("last_activity_description") or "").strip()
    cost = row.get("estimated_cost_usd") or 0.0

    fm: dict = {
        "title": title,
        "created": iso(started)[:10] or dt.date.today().isoformat(),
        "updated": iso(last)[:10] or dt.date.today().isoformat(),
        "type": "session",
        "tags": ["session", "agent", "workflow"],
        "sources": [f"session:{sid}"],
        "confidence": "high",
        "generated": True,
        "session_id": sid,
        "state": state,
        "kind": kind,
        # How many vault pages cite this session. A number so a base can sort on it.
        "pages": len(produced or []),
        "last_activity_desc": last_desc,
        "source": str(row.get("source") or ""),
        "profile": str(row.get("profile_name") or ""),
        "model": str(row.get("model") or ""),
        "title_source": str(row.get("title_source") or ""),
        "ended_reason": str(row.get("end_reason") or ""),
        "started": iso(started),
        "ended": iso(ended),
        "last_activity": iso(last),
        "duration_min": duration_min,
        "messages": int(row.get("message_count") or 0),
        "tool_calls": int(row.get("tool_call_count") or 0),
        "api_calls": int(row.get("api_call_count") or 0),
        "tokens_in": int(row.get("input_tokens") or 0),
        "tokens_out": int(row.get("output_tokens") or 0),
        "tokens_reasoning": int(row.get("reasoning_tokens") or 0),
        "cache_read": int(row.get("cache_read_tokens") or 0),
        "cost_usd": round(float(cost), 4),
        "cost_status": str(row.get("cost_status") or ""),
    }

    body = [f"One agent session, exported from `state.db` by `kb_sessions.py`.\n",
            "\n> Generated, and machine-local: `sessions/` is gitignored and outside the\n"
            "> vault's lint. Do not hand-edit — re-run the exporter.\n",
            # One click back into the session: `hermes://open/<id>` is the desktop app's own
            # deep link (verified: the app logs `[deeplink] delivered open/<id>`).
            f"\n[Open this session in Hermes](hermes://open/{sid})\n",
            f"\n| | |\n|---|---|\n"
            f"| state | `{state}` |\n"
            f"| source | `{fm['source']}` |\n"
            f"| model | `{fm['model']}` |\n"
            f"| started | {fm['started'] or '-'} |\n"
            f"| ended | {fm['ended'] or '(open)'} |\n"
            f"| duration | {duration_min} min |\n"
            f"| messages | {fm['messages']} |\n"
            f"| tool calls | {fm['tool_calls']} |\n"
            f"| tokens | {fm['tokens_in']:,} in / {fm['tokens_out']:,} out"
            f" / {fm['tokens_reasoning']:,} reasoning |\n"
            f"| cost | ${fm['cost_usd']} ({fm['cost_status'] or 'n/a'}) |\n"]
    last_desc = str(row.get("last_activity_description") or "").strip()
    last_desc = str(row.get("last_activity_description") or "").strip()
    if last_desc:
        body.append(f"\n**Last activity:** {last_desc}\n")

    # What this session put into the knowledge base; without it a session is a dead end -
    # you can read what the agent did but not what it produced.
    if produced:
        body.append(f"\n## Produced {len(produced)} page(s)\n\n")
        for slug in sorted(produced):
            body.append(f"- [[{slug}]]\n")
    else:
        body.append("\n## Produced\n\nNo vault page cites this session yet.\n")
    return sid, kb.render_frontmatter(fm) + "".join(body)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", default=None, help="vault root (default: resolved)")
    ap.add_argument("--db", default=None, help="state.db path (default: $HERMES_HOME)")
    ap.add_argument("--limit", type=int, default=0, help="newest N sessions only")
    ap.add_argument("--print", action="store_true", dest="dry_run",
                    help="report what would change; write nothing")
    a = ap.parse_args()

    db = Path(a.db).expanduser() if a.db else default_db()
    if not db.is_file():
        print(f"kb_sessions: no session database at {db}", file=sys.stderr)
        return 1
    vault = Path(a.vault).expanduser() if a.vault else kb.resolve_root()
    dest = vault / SESSIONS_DIR

    try:
        rows = read_sessions(db)
    except sqlite3.Error as e:
        print(f"kb_sessions: cannot read {db}: {e}", file=sys.stderr)
        return 1
    if a.limit:
        rows = rows[:a.limit]

    changed, written, failed = 0, 0, []
    produced_by = pages_citing_sessions(vault)
    for row in rows:
        sid, content = build_note(row, produced_by.get(str(row["id"])))
        path = dest / f"{kb.norm_key(sid)}.md"
        if a.dry_run:
            current = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
            if current != content:
                changed += 1
                print(f"kb_sessions: would write {path.name}")
            continue
        try:
            dest.mkdir(parents=True, exist_ok=True)
            if kb.write_if_changed(path, content):
                written += 1
        except OSError as e:
            # A vault folder that is transiently locked (cloud sync, backup agent, AV scan)
            # must not abort the whole export: one unwritable note is a reportable problem,
            # a crashed job is a silent one. Seen in practice - Documents briefly carried
            # the READONLY attribute and every create failed with FileNotFoundError.
            failed.append(f"{path.name}: {e.__class__.__name__}")

    if a.dry_run:
        print(f"kb_sessions: {changed} of {len(rows)} note(s) would change")
        return 0
    if written:
        print(f"kb_sessions: {written} note(s) written -> {dest}")
    if failed:
        print(f"kb_sessions: {len(failed)} note(s) COULD NOT BE WRITTEN "
              f"(vault folder not writable?): {', '.join(failed[:5])}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
