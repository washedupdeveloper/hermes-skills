"""The pinned toolchain: where it is, and how to run a command against it.

The toolchain is the flake's `toolchain` package, built from the nixpkgs revision
in flake.lock, so the same lock gives the same store path on every machine and
every reviewer runs identical tool versions. Nothing here installs anything.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


_RESOLVED: Dict[str, str] = {}


def resolve(flake: Optional[Path] = None) -> Optional[str]:
    """The toolchain store path, or None when it cannot be resolved.

    REVIEW_COUNCIL_TOOLCHAIN wins: the image bakes it in and the devshell exports
    it. Asking nix first would need a writable store, which a container has not.

    Cached per flake, successes only: one nix-eval probe resolves this once per
    probe, and every miss is a `nix build` spawn. A failure is not cached, so a
    transient error can still be retried.
    """
    key = str(Path(flake) if flake else ROOT)
    if key in _RESOLVED:
        return _RESOLVED[key]

    baked = os.environ.get("REVIEW_COUNCIL_TOOLCHAIN", "")
    if baked and (Path(baked) / "bin").is_dir():
        _RESOLVED[key] = baked
        return baked
    flake = Path(flake) if flake else ROOT
    try:
        proc = subprocess.run(
            ["nix", "build", f"{flake}#toolchain", "--print-out-paths", "--no-link"],
            capture_output=True, text=True, timeout=1800,
            encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    lines = (proc.stdout or "").strip().splitlines()
    found = lines[-1].strip() if proc.returncode == 0 and lines else None
    if found:
        _RESOLVED[key] = found
    return found


def env(flake: Optional[Path] = None) -> Dict[str, str]:
    """The environment with the toolchain's bin first on PATH."""
    result = dict(os.environ)
    toolchain = resolve(flake)
    if toolchain:
        result["REVIEW_COUNCIL_TOOLCHAIN"] = toolchain
        result["PATH"] = str(Path(toolchain) / "bin") + os.pathsep + result.get("PATH", "")
    return result


def inventory(flake: Optional[Path] = None) -> Dict[str, Any]:
    """The pinned tool versions, as written by the flake."""
    toolchain = resolve(flake)
    if not toolchain:
        return {}
    path = Path(toolchain) / "review-council-toolchain.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def which(tool: str, flake: Optional[Path] = None) -> Optional[str]:
    return shutil.which(tool, path=env(flake).get("PATH", ""))


def run(argv: Sequence[str], repo: Optional[Path] = None, flake: Optional[Path] = None,
        timeout: int = 1800, env_extra: Optional[Dict[str, str]] = None,
        merge_stderr: bool = True) -> Tuple[int, str]:
    """Run a command against the toolchain. Returns (rc, combined output).

    (127, reason) when the toolchain is unavailable, so a probe reports ran=False
    rather than inventing a result.

    *env_extra* is for probes that must run a tool WITHOUT writing into the repo
    they are reviewing: pytest and mypy both cache by default, and a review must
    not leave files behind in someone else's tree.

    *merge_stderr* is False for a tool whose stdout is machine-readable and whose
    stderr carries human progress. Merging the two corrupts the payload: zizmor
    emits a JSON array on stdout and its banner and progress on stderr, so the
    merged stream does not parse. Every other probe reads combined output, where
    the split does not matter, so the default stays as it was.
    """
    environment = env(flake)
    if env_extra:
        environment.update(env_extra)
    if "REVIEW_COUNCIL_TOOLCHAIN" not in environment:
        return 127, "could not resolve the pinned toolchain"
    try:
        proc = subprocess.run(
            list(argv), cwd=str(repo) if repo else None, env=environment,
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, f"{type(exc).__name__}: {exc}"
    return proc.returncode, (
        (proc.stdout or "") if not merge_stderr
        else (proc.stdout or "") + (proc.stderr or ""))


def main(argv: List[str]) -> int:
    repo: Optional[Path] = None
    flake: Optional[Path] = None
    mode = "run"
    tool = ""
    command: List[str] = []

    def value_for(flag: str, position: int) -> str:
        if position + 1 >= len(argv):
            print(f"toolchain: {flag} needs a value", file=sys.stderr)
            raise SystemExit(2)
        return argv[position + 1]

    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg == "--repo":
            repo = Path(value_for("--repo", index))
            index += 2
        elif arg == "--flake":
            flake = Path(value_for("--flake", index))
            index += 2
        elif arg == "--which":
            mode, tool = "which", value_for("--which", index)
            index += 2
        elif arg == "--inventory":
            mode = "inventory"
            index += 1
        elif arg == "--path":
            mode = "path"
            index += 1
        elif arg == "--":
            command = argv[index + 1:]
            break
        else:
            command = argv[index:]
            break

    if mode == "path":
        toolchain = resolve(flake)
        if not toolchain:
            print("toolchain: could not resolve the pinned toolchain", file=sys.stderr)
            return 2
        print(toolchain)
        return 0

    if mode == "inventory":
        print(json.dumps(inventory(flake)))
        return 0

    if mode == "which":
        found = which(tool, flake)
        if found:
            print(found)
            return 0
        print(f"not found in toolchain: {tool}", file=sys.stderr)
        return 1

    if not command:
        print("toolchain: nothing to run (usage: toolchain.py -- <command...>)", file=sys.stderr)
        return 2

    environment = env(flake)
    if "REVIEW_COUNCIL_TOOLCHAIN" not in environment:
        print("toolchain: could not resolve the pinned toolchain", file=sys.stderr)
        return 2
    if repo:
        os.chdir(repo)
    os.execvpe(command[0], command, environment)
    return 0


if __name__ == "__main__":
    # Not a program: reached through `council <verb>`. See council.py.
    from council import require_dispatch

    require_dispatch("setup toolchain")
    sys.exit(main(sys.argv[1:]))
