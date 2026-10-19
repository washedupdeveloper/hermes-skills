#!/usr/bin/env python3
"""Locate the Hermes the council drives, and report honestly what can be known.

The council does not talk to a Hermes *gateway*. It shells out to the `hermes`
launcher (`hermes -p <profile> chat --query-file <path>`) and reads the file that turn
writes. The prompt goes in a FILE, never in `-q`: a real repository's probe JSON runs
to ~400 KB and the kernel's per-argument cap is 64 KB, so `-q` failed every real repo
with `[Errno 7] Argument list too long`. `hermes serve` — the backend the desktop app and remote clients connect to
— is a DIFFERENT thing, and a reachable port on it is not evidence that the council
can run an agent. Conflating the two is how a machine reports "Hermes available"
and then fails every review, so this module keeps them apart.

The question is answered in LAYERS, cheapest and most certain first, and a weak
signal is never promoted into a strong claim:

    L0 launcher    deterministic, local    HERMES_BIN, then PATH, then known paths
    L1 version     deterministic, local    `hermes --version` — proves it EXECUTES
    L2 profiles    deterministic, local    the council profiles carry a provider
    L3 gateway     optimistic, network     something is listening — a HINT
    L4 capability  authoritative, costly   one real minimal turn (opt-in)

`report()` is L0..L3 and is what `doctor` prints. `capability()` is L4, opt-in,
because it spends an agent turn and whatever that costs.

Why not just check the port? Because it answers a question nobody asked. The
council's requirement is "a launcher that can complete a turn", and a listening
socket is neither necessary nor sufficient for that: the gateway can be up while
the launcher is absent (the desktop case), and the launcher can be present and
working with no gateway at all (the CLI case). The port is a useful DIAGNOSTIC
when a remote setup is misbehaving; it is not the availability test.
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

try:
    from hermes_home import resolve as resolve_hermes_home  # type: ignore
except ImportError:  # pragma: no cover - only when loaded without its sibling
    def resolve_hermes_home() -> str:
        return os.environ.get("HERMES_HOME") or str(Path.home() / ".hermes")


# The profiles the council installs and drives. One place knows their names.
PROFILES = ("council-generalist", "council-orchestrator")

# `hermes serve`'s default port. Only ever a hint — see the module docstring.
DEFAULT_GATEWAY_PORT = 9119

# Markers that a profile config can reach a model. Hermes keeps credentials PER
# PROFILE and does not share them, so this is asked per profile.
_CREDENTIAL_MARKERS = ("api_key", "provider", "base_url")


def launcher() -> Optional[str]:
    """L0 — the `hermes` executable, or None. Deterministic, local, cheap.

    `HERMES_BIN` wins so an environment that provides Hermes outside PATH — a
    container with an install mounted in, a second install beside the default —
    can name it instead of rewriting PATH.
    """
    explicit = os.environ.get("HERMES_BIN")
    if explicit:
        candidate = Path(explicit).expanduser()
        if candidate.exists():
            return str(candidate)
        found = shutil.which(explicit)
        if found:
            return found
    for name in ("hermes", "hermes.cmd", "hermes.exe"):
        found = shutil.which(name)
        if found:
            return found
    local = Path.home() / ".local" / "bin" / "hermes.cmd"
    if local.exists():
        return str(local)
    return None


def version(binary: Optional[str] = None, timeout: int = 60) -> Optional[str]:
    """L1 — the launcher's version, or None when it will not execute.

    Strictly more than `which`. A file on PATH that cannot run — wrong
    architecture, a dangling shebang, a wrapper whose interpreter is gone —
    resolves fine and then fails every single turn, and the failure reads as an
    agent problem rather than an install problem.
    """
    binary = binary or launcher()
    if not binary:
        return None
    try:
        proc = subprocess.run(
            [binary, "--version"], capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    text = (proc.stdout or proc.stderr or "").strip()
    return text.splitlines()[0].strip() if text else "unknown"


def profile_status() -> Dict[str, Any]:
    """L2 — whether the council's profiles exist and can reach a model.

    A machine with Hermes installed and the profiles absent cannot review; neither
    can one whose profiles carry no provider. Both are deterministic and local,
    and both are silent failures without this check: the run starts, spawns
    nothing, and the gate reports an error the user cannot act on.
    """
    root = Path(resolve_hermes_home()) / "profiles"
    out: Dict[str, Any] = {"root": str(root), "present": [], "missing": [],
                           "with_provider": [], "without_provider": []}
    for name in PROFILES:
        target = root / name
        if not target.is_dir():
            out["missing"].append(name)
            continue
        out["present"].append(name)
        try:
            text = (target / "config.yaml").read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        key = "with_provider" if any(m in text for m in _CREDENTIAL_MARKERS) \
            else "without_provider"
        out[key].append(name)
    return out


def gateway(host: Optional[str] = None, port: Optional[int] = None,
            timeout: float = 2.0) -> Dict[str, Any]:
    """L3 — is something listening where a Hermes backend would be? A HINT.

    Optimistic and deliberately weak. It answers "a Hermes backend is running
    here", which is what you want when a REMOTE setup is misbehaving — the desktop
    talking to a `hermes serve` over a tunnel, a container sharing the host's
    network namespace. It does not answer "the council can run an agent": that
    needs a launcher, and the launcher is a separate thing. A closed port proves
    only that nothing answered.
    """
    host = host or os.environ.get("HERMES_GATEWAY_HOST") or "127.0.0.1"
    try:
        port = int(port or os.environ.get("HERMES_GATEWAY_PORT") or DEFAULT_GATEWAY_PORT)
    except (TypeError, ValueError):
        port = DEFAULT_GATEWAY_PORT
    reachable = False
    try:
        with socket.create_connection((host, port), timeout=timeout):
            reachable = True
    except (OSError, ValueError):
        reachable = False
    return {
        "host": host, "port": port, "reachable": reachable,
        "meaning": ("a Hermes backend answered; it powers the desktop and remote "
                    "clients and is NOT what the council drives"),
    }


def capability(binary: Optional[str] = None, timeout: int = 300,
               profile: str = PROFILES[0]) -> Dict[str, Any]:
    """L4 — the only authoritative test: can this thing complete a turn?

    Opt-in, because it spends an agent turn and whatever that costs. Everything
    above is a proxy for this and none of them substitutes for it: a launcher that
    resolves, prints a version and sits beside profiles with a provider can still
    fail on an expired token, an exhausted key pool or an unreachable provider.
    """
    binary = binary or launcher()
    if not binary:
        return {"ran": False, "ok": False, "note": "no launcher"}
    try:
        proc = subprocess.run(
            [binary, "-p", profile, "chat", "-q", "Reply with the single word: ok"],
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
        )
    except subprocess.TimeoutExpired:
        return {"ran": True, "ok": False, "note": f"timed out after {timeout}s"}
    except OSError as exc:
        return {"ran": True, "ok": False, "note": f"{type(exc).__name__}: {exc}"}
    ok = proc.returncode == 0
    return {
        "ran": True, "ok": ok, "returncode": proc.returncode,
        "note": "completed a turn" if ok else (proc.stderr or proc.stdout or "").strip()[-200:],
    }


def report(gateway_host: Optional[str] = None,
           gateway_port: Optional[int] = None) -> Dict[str, Any]:
    """L0..L3 plus a single verdict a caller can act on.

    The verdict names the FIRST thing that would stop a review, in the order the
    layers are checked, because that is the one worth fixing. `gateway` is carried
    alongside but never changes the verdict: it is not on the path a review takes.
    """
    binary = launcher()
    ver = version(binary) if binary else None
    prof = profile_status()
    gw = gateway(gateway_host, gateway_port)

    if not binary:
        verdict, action = "no-launcher", "Install Hermes, or set HERMES_BIN to it."
    elif ver is None:
        verdict, action = "unusable-launcher", f"{binary} resolved but will not run."
    elif prof["missing"]:
        verdict, action = "no-profiles", "council setup bots"
    elif prof["without_provider"]:
        verdict, action = "no-credentials", (
            "hermes -p council-generalist setup   (and council-orchestrator)")
    else:
        verdict, action = "ready", None

    return {"launcher": binary, "version": ver, "profiles": prof,
            "gateway": gw, "verdict": verdict, "action": action}


_VERDICT_TEXT = {
    "ready": "ready — a review can run",
    "no-launcher": "NO LAUNCHER — nothing can review",
    "unusable-launcher": "LAUNCHER WILL NOT RUN — nothing can review",
    "no-profiles": "NO COUNCIL PROFILES — run `council setup bots`",
    "no-credentials": "NO PROVIDER CREDENTIALS in the council profiles",
}


def render(data: Dict[str, Any]) -> List[str]:
    """The lines `doctor` prints for Hermes. One renderer, so there is one wording."""
    out: List[str] = []
    launcher_path = data.get("launcher")
    if launcher_path:
        out.append(f"  hermes    : {data.get('version') or '?'}  ({launcher_path})")
    else:
        out.append("  hermes    : NOT FOUND — nothing can review")

    prof = data.get("profiles") or {}
    if prof.get("missing"):
        out.append(f"    profiles: missing {', '.join(prof['missing'])}"
                   f"  (expected under {prof.get('root')})")
    elif prof.get("present"):
        ready = ", ".join(prof.get("with_provider") or []) or "none"
        out.append(f"    profiles: {', '.join(prof['present'])}"
                   f"  (provider configured: {ready})")
        if prof.get("without_provider"):
            out.append(f"    NO provider in: {', '.join(prof['without_provider'])}")

    gw = data.get("gateway") or {}
    if gw:
        state = "reachable" if gw.get("reachable") else "not reachable"
        out.append(f"    gateway : {gw.get('host')}:{gw.get('port')} {state}"
                   f"  (a hint only; the council drives the launcher, not this)")

    verdict = data.get("verdict")
    if verdict and verdict != "ready":
        out.append(f"    verdict : {_VERDICT_TEXT.get(verdict, verdict)}")
        if data.get("action"):
            out.append(f"              {data['action']}")
    elif verdict:
        out.append(f"    verdict : {_VERDICT_TEXT[verdict]}")

    # L4, when asked for: its own line, so a proxy is never mistaken for the proof.
    cap = data.get("capability")
    if cap:
        out.append(f"    probe   : {'ok' if cap.get('ok') else 'FAILED'} — {cap.get('note')}")
    return out
