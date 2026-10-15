"""Where Hermes keeps its home.

Asked of Hermes rather than assumed: the answer differs per platform (%LOCALAPPDATA%
on Windows, ~/.hermes elsewhere) and a copy written to the wrong one is SHADOWED
rather than reported, so the mistake is silent.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def resolve() -> str:
    """HERMES_HOME, else what Hermes reports, else %LOCALAPPDATA%, else ~/.hermes."""
    explicit = os.environ.get("HERMES_HOME")
    if explicit:
        return explicit
    if shutil.which("hermes"):
        try:
            proc = subprocess.run(
                ["hermes", "profile", "show", "default"],
                capture_output=True, text=True, timeout=60,
                encoding="utf-8", errors="replace",
            )
        except (OSError, subprocess.TimeoutExpired):
            proc = None
        if proc is not None and proc.returncode == 0:
            # `hermes profile show default` prints the default profile's Path: the home.
            for line in (proc.stdout or "").replace("\r", "").splitlines():
                if line.startswith("Path:"):
                    found = line.split(":", 1)[1].strip()
                    if found and Path(found).is_dir():
                        return found
                    break
    local = os.environ.get("LOCALAPPDATA")
    if local and (Path(local) / "hermes").is_dir():
        return str(Path(local) / "hermes")
    return str(Path.home() / ".hermes")
