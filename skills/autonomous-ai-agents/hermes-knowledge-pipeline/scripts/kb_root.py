#!/usr/bin/env python3
"""kb_root.py - resolve the canonical knowledge-base root for THIS machine.

One resolver, four platforms. Prints the resolved absolute path in the
*native-forward-slash* form that both MSYS bash and native Windows programs
accept (C:/Users/x/...), or the POSIX form elsewhere.

Exit 0 + path on stdout  -> usable
Exit 1 + reason on stderr -> needs setup
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import re

DEFAULT_DIRNAME = "AI-Knowledge"


def detect_platform() -> str:
    """Return one of: windows, wsl2, linux, macos."""
    if os.name == "nt":
        return "windows"
    # WSL2 reports 'microsoft' (or 'WSL2') in /proc/version; WSL1 too.
    try:
        with open("/proc/version", "r", encoding="utf-8", errors="replace") as fh:
            kv = fh.read().lower()
        if "microsoft" in kv or "wsl" in kv:
            return "wsl2"
    except OSError:
        pass
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def _windows_docs() -> Path:
    """Windows 'Documents' via the shell API so OneDrive redirection is honoured."""
    userprofile = os.environ.get("USERPROFILE") or str(Path.home())
    # Ask Windows where Documents really is (handles OneDrive Known-Folder-Move).
    try:
        import ctypes

        buf = ctypes.create_unicode_buffer(1024)
        # CSIDL_PERSONAL = 5
        if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0 and buf.value:
            return Path(buf.value)
    except Exception:
        pass
    return Path(userprofile) / "Documents"


def wsl_windows_user() -> str | None:
    """On WSL2, find the Windows username via interop, so /mnt/c/Users/<u> resolves."""
    try:
        out = os.popen('cmd.exe /c "echo %USERNAME%" 2>/dev/null').read().strip()
        if out and re.fullmatch(r"[A-Za-z0-9._-]+", out):
            return out
    except Exception:
        pass
    return None


def default_root(plat: str) -> Path:
    if plat == "windows":
        return _windows_docs() / DEFAULT_DIRNAME
    if plat == "wsl2":
        win_user = wsl_windows_user()
        # Prefer the Windows-side copy so Windows + WSL2 + Obsidian desktop
        # all read the SAME files. Fall back to ext4 if interop is unavailable.
        if win_user and Path(f"/mnt/c/Users/{win_user}").is_dir():
            return Path(f"/mnt/c/Users/{win_user}/Documents/{DEFAULT_DIRNAME}")
        return Path.home() / DEFAULT_DIRNAME
    if plat == "macos":
        return Path.home() / "Documents" / DEFAULT_DIRNAME
    # linux: keep it in a Documents-like place for Obsidian
    return Path.home() / "Documents" / DEFAULT_DIRNAME


def to_native_forward_slash(p: Path) -> str:
    """Path string that MSYS bash, cmd.exe, and native Windows tools all accept."""
    s = str(p)
    if os.name == "nt":
        return s.replace("\\", "/")
    return s


def resolve() -> tuple[str | None, str]:
    """(path, reason). Explicit env/config wins over the OS default."""
    plat = detect_platform()
    for var in ("HERMES_KB_ROOT", "WIKI_PATH", "OBSIDIAN_VAULT_PATH"):
        raw = os.environ.get(var, "").strip()
        if raw:
            p = Path(os.path.expanduser(raw))
            if not p.is_absolute():
                return None, f"{var}={raw!r} is not an absolute path"
            return to_native_forward_slash(p), f"from ${var}"
    return to_native_forward_slash(default_root(plat)), f"default for {plat}"


def main() -> int:
    path, reason = resolve()
    if path is None:
        print(reason, file=sys.stderr)
        return 1
    print(path)
    if "--explain" in sys.argv:
        print(f"# platform={detect_platform()} source={reason}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
