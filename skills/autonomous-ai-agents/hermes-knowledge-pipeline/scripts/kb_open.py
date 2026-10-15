#!/usr/bin/env python3
"""kb_open.py - open the vault (or a session) in Obsidian from the command line.

The two apps address each other through registered URI schemes, and neither needs
a plugin:

    obsidian://open?vault=<name>&file=<path>   -> Obsidian opens that note
    hermes://open/<session-id>                 -> the desktop app opens that chat

Why this script exists rather than a desktop plugin button: the Hermes desktop
bridge admits **web schemes only** (`SUPPORTED_WEB = ['http:', 'https:', 'mailto:']`
in `apps/desktop/electron/external-open.ts`), so a plugin calling
`ctx.os.openExternal('obsidian://...')` is rejected. The OS itself has no such
restriction, so the route that works is to hand the URI to the OS.

    kb_open.py                     # the vault's HOME.md (the overview)
    kb_open.py <note>              # a note, by name or vault-relative path
    kb_open.py --session <id>      # the session note for a session id
    kb_open.py --uri               # print the URI instead of opening it

Silent on success so it composes with a cron job or a chat instruction.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import kb_reindex as kb  # noqa: E402

SESSIONS_DIR = "sessions"


def vault_name(root: Path) -> str:
    """Obsidian's vault key is the folder name — that is what it registers."""
    return root.name


def note_uri(root: Path, rel: str) -> str:
    """`file=` takes a vault-relative path, and accepts either separator."""
    rel = rel.replace("\\", "/").lstrip("/")
    if not rel.lower().endswith(".md"):
        rel += ".md"
    from urllib.parse import quote
    return f"obsidian://open?vault={quote(vault_name(root))}&file={quote(rel)}"


def session_note(root: Path, session_id: str) -> Path | None:
    """The generated note for a session, if it has been exported yet."""
    p = root / SESSIONS_DIR / f"{kb.norm_key(session_id)}.md"
    return p if p.is_file() else None


def launch(uri: str) -> bool:
    """Hand a URI to the OS. Windows needs the empty-string title argument."""
    if sys.platform == "win32":
        subprocess.run(["cmd", "/c", "start", "", uri], check=False)
        return True
    if sys.platform == "darwin":
        subprocess.run(["open", uri], check=False)
        return True
    if os.environ.get("WSL_DISTRO_NAME"):
        # Inside WSL the handler lives on the Windows side.
        subprocess.run(["cmd.exe", "/c", "start", "", uri], check=False)
        return True
    subprocess.run(["xdg-open", uri], check=False)
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("note", nargs="?", default="HOME",
                    help="note name or vault-relative path (default: HOME)")
    ap.add_argument("--session", metavar="ID",
                    help="open the session note for this session id")
    ap.add_argument("--vault", default=None, help="vault root (default: resolved)")
    ap.add_argument("--uri", action="store_true", help="print the URI; open nothing")
    a = ap.parse_args()

    root = Path(a.vault).expanduser() if a.vault else kb.resolve_root()
    if not root.is_dir():
        print(f"kb_open: vault not found: {root}", file=sys.stderr)
        return 1

    if a.session:
        note = session_note(root, a.session)
        if note is None:
            print(f"kb_open: no note yet for session {a.session} "
                  f"(run kb_sessions.py; export is hourly)", file=sys.stderr)
            return 1
        rel = note.relative_to(root).as_posix()
    else:
        rel = a.note.strip()

    uri = note_uri(root, rel)
    if a.uri:
        print(uri)
        return 0
    launch(uri)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
