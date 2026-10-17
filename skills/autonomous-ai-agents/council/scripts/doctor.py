#!/usr/bin/env python3
"""Report which analyzers the pinned toolchain provides and the beta they yield.

A missing analyzer does not fail a run: beta drops and the score becomes
judgement-only. Usage: council doctor [--repo DIR] [--json] [--install].
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

try:
    import hermes  # type: ignore
    import toolchain  # type: ignore
    from score_reviews import (  # type: ignore
        BUILTIN_TOOLS,
        NIX_PROBE_TOOLS,
        WEIGHTS,
        detect_stacks,
        expected_tools,
    )
except ImportError as exc:  # pragma: no cover
    print(f"doctor: cannot import the framework modules from {HERE}: {exc}", file=sys.stderr)
    sys.exit(2)


# --- Tool catalog: how to detect and how to install, per platform ------------

# Each entry: detect (a command whose presence means "installed") and per-OS
# install hints. `pip` entries install into the interpreter running this script.
CATALOG: Dict[str, Dict[str, Any]] = {
    # Python
    "ruff":     {"detect": "ruff",      "pip": "ruff",     "why": "lint + format (readability)"},
    "mypy":     {"detect": "mypy",      "pip": "mypy",     "why": "static types (readability)"},
    "bandit":   {"detect": "bandit",    "pip": "bandit",   "why": "security lint (security)"},
    # One dependency scanner for every ecosystem, replacing pip-audit / npm-audit /
    # cargo-audit. pip-audit is gone deliberately: its nixpkgs wrapper cannot run
    # (it execs `python3 -m pip --version` under an interpreter that has no pip).
    "osv-scanner": {"detect": "osv-scanner", "nix": "osv-scanner",
                    "why": "dependency CVEs, all ecosystems (security)"},
    "pytest":   {"detect": "pytest",    "pip": "pytest",   "why": "test runner (correctness)"},
    # Nix (first-class, per DECISIONS #3 / the Nix-scoped rubrics)
    "nix":      {"detect": "nix",       "nix": "nix",      "why": "nix eval + flake check"},
    "nixfmt":   {"detect": "nixfmt",    "nix": "nixfmt",   "why": "nix formatting (readability)"},
    "statix":   {"detect": "statix",    "nix": "statix",   "why": "nix lints (security/readability)"},
    "deadnix":  {"detect": "deadnix",   "nix": "deadnix",  "why": "dead nix code (readability)"},
    # Cross-language / system
    "shellcheck": {"detect": "shellcheck", "apt": "shellcheck", "brew": "shellcheck",
                   "scoop": "shellcheck", "why": "shell lint (readability/security)"},
    "gitleaks": {"detect": "gitleaks", "brew": "gitleaks", "scoop": "gitleaks",
                 "why": "secret scanning (security)"},
    # semgrep is deliberately absent: it is not in research/nix-tooling.md §0, and
    # it does not build on the pinned nixpkgs (pyjwt runtime-dep check fails). The
    # security dimensions use statix + gitleaks (Nix) and bandit + osv-scanner (Python).
    # JS/TS
    "eslint":   {"detect": "eslint",    "npm": "eslint",   "why": "JS/TS lint (readability)"},
    "prettier": {"detect": "prettier",  "npm": "prettier", "why": "JS/TS format (readability)"},
    "tsc":      {"detect": "tsc",       "npm": "typescript", "why": "type check (correctness)"},
    "jest":     {"detect": "jest",      "npm": "jest",     "why": "JS tests (correctness)"},
    # Rust / Go
    "cargo":    {"detect": "cargo",     "why": "cargo test/clippy (rust)"},
    "clippy":   {"detect": "cargo-clippy", "why": "rust lints (readability)"},
    "rustfmt":  {"detect": "rustfmt",   "why": "rust format (readability)"},
    "go":       {"detect": "go",        "why": "go test/vet (go)"},
    "gofmt":    {"detect": "gofmt",     "why": "go format (readability)"},
}


def _platform_keys() -> Tuple[str, ...]:
    system = platform.system().lower()
    if system == "windows":
        return ("pip", "scoop", "winget", "nix")
    if system == "darwin":
        return ("pip", "brew", "nix")
    return ("pip", "apt", "nix")


# --- Nix: the declarative, pinned path --------------------------------------
#
# Nix is the PREFERRED provisioning mechanism: nix/builders.nix declares the tool set,
# flake.lock pins the exact nixpkgs revision, and `nix build .#toolchain` yields
# the same store path on every machine. Nothing is installed imperatively and
# nothing drifts. The pip/brew/scoop hints below exist only as a fallback for
# hosts without Nix.

_NIX_CACHE: Optional[Dict[str, Any]] = None


def nix_status() -> Dict[str, Any]:
    """Read the pinned toolchain, or report why it cannot be resolved.

    Returns {"available", "via", "toolchain", "tools", "absent", "nixpkgs", "error"}.
    Cached — this shells out.
    """
    global _NIX_CACHE
    if _NIX_CACHE is not None:
        return _NIX_CACHE

    result: Dict[str, Any] = {
        "available": False, "via": None, "toolchain": None,
        "tools": {}, "absent": [], "nixpkgs": None, "error": None,
    }

    if not (os.environ.get("REVIEW_COUNCIL_TOOLCHAIN") or shutil.which("nix")):
        result["error"] = ("nix not found. Install nix, or run the container image "
                           "(see docs/CONTAINER.md)")
        _NIX_CACHE = result
        return result

    resolved = toolchain.resolve()
    if not resolved:
        result["error"] = "could not build the pinned toolchain"
        _NIX_CACHE = result
        return result

    result["available"] = True
    result["via"] = "nix"
    result["toolchain"] = resolved

    data = toolchain.inventory()
    result["tools"] = data.get("tools") or {}
    result["absent"] = data.get("absent") or []
    result["nixpkgs"] = data.get("nixpkgs")

    _NIX_CACHE = result
    return result


def nix_provides(name: str) -> bool:
    """True when the pinned toolchain ships *name*."""
    status = nix_status()
    if not status["available"]:
        return False
    tools = status["tools"]
    if name in tools:
        return True
    # Nix attr names and binary names mostly coincide, but normalise anyway.
    return any(normalize_tool_name(k) == normalize_tool_name(name) for k in tools)


def normalize_tool_name(name: str) -> str:
    return str(name or "").strip().lower().replace("_", "-")


def tool_available(name: str) -> bool:
    """A builtin probe is always available; then the pinned Nix toolchain (which
    also satisfies the probe wrappers); then the host PATH."""
    if name in BUILTIN_TOOLS:
        return True
    # Probe wrappers need only `nix` + the toolchain, not a binary of their own.
    if name in NIX_PROBE_TOOLS and nix_status()["available"]:
        return True
    if nix_provides(name):
        return True
    entry = CATALOG.get(name)
    if entry and entry.get("detect"):
        return shutil.which(entry["detect"]) is not None
    return shutil.which(name) is not None


def install_command(name: str) -> Optional[str]:
    """How to get *name*.

    Nix first, always: the answer is to declare it in nix/builders.nix's `toolNames`
    and rebuild, so the tool set stays pinned and reproducible. The imperative
    installers are only offered when the tool is genuinely unavailable through the
    flake.
    """
    status = nix_status()
    if status["available"]:
        # None, not an instruction: `--install` RUNS what this returns, and
        # "add X to toolNames" is advice, not a command. The renderer prints it.
        return None

    entry = CATALOG.get(name)
    if not entry:
        return None
    available = package_managers()
    for key in _platform_keys():
        value = entry.get(key)
        if not value:
            continue
        if key in {"pip", "nix", "brew", "apt", "scoop", "npm"} and not available.get(key):
            continue
        if key == "pip":
            return f"{sys.executable} -m pip install {value}"
        if key == "nix":
            return f"nix profile install nixpkgs#{value}"
        if key == "brew":
            return f"brew install {value}"
        if key == "apt":
            return f"sudo apt-get install -y {value}"
        if key == "scoop":
            return f"scoop install {value}"
        if key == "winget":
            return f"winget install {value}"
        if key == "npm":
            return f"npm install -g {value}"
    return None


_PM_CACHE: Optional[Dict[str, bool]] = None


def package_managers() -> Dict[str, bool]:
    """Detected package managers, memoized — install_command() calls this per
    tool, and _has_pip() spawns a subprocess."""
    global _PM_CACHE
    if _PM_CACHE is None:
        _PM_CACHE = {
            "pip": shutil.which("pip") is not None or _has_pip(),
            "nix": shutil.which("nix") is not None,
            "brew": shutil.which("brew") is not None,
            "apt": shutil.which("apt-get") is not None,
            "scoop": shutil.which("scoop") is not None,
            "npm": shutil.which("npm") is not None,
            "cargo": shutil.which("cargo") is not None,
            "go": shutil.which("go") is not None,
        }
    return _PM_CACHE


def _has_pip() -> bool:
    try:
        return subprocess.run([sys.executable, "-m", "pip", "--version"],
                              capture_output=True, timeout=20).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def diagnose(repo: Path, dimension: Optional[str] = None) -> Dict[str, Any]:
    """Per-dimension tool availability and the beta you would get."""
    stacks = detect_stacks(repo)
    dims = [dimension] if dimension else list(WEIGHTS)
    nix = nix_status()

    dims_out: List[Dict[str, Any]] = []
    for dim in dims:
        expected = expected_tools(dim, stacks)
        if not expected:
            dims_out.append({"dimension": dim, "expected": [], "available": [],
                             "missing": [], "beta_now": 0.0, "beta_possible": 0.0,
                             "installable": []})
            continue
        available = [t for t in expected if tool_available(t)]
        missing = [t for t in expected if not tool_available(t)]
        installable = [{"tool": t, "command": install_command(t)} for t in missing
                       if install_command(t)]
        dims_out.append({
            "dimension": dim,
            "expected": expected,
            "available": available,
            "missing": missing,
            "beta_now": round(len(available) / len(expected), 4),
            "beta_possible": 1.0 if not missing else round(len(available) / len(expected), 4),
            "installable": installable,
        })

    # Aggregate beta, weighted the same way the score is.
    total_w = sum(WEIGHTS[d] for d in dims) or 1.0
    beta_now = sum(WEIGHTS[d["dimension"]] * d["beta_now"] for d in dims_out) / total_w

    return {
        "repo": str(repo),
        "platform": platform.system(),
        "stacks": stacks,
        "package_managers": package_managers(),
        "nix": {
            "available": nix["available"],
            "via": nix["via"],
            "toolchain": nix["toolchain"],
            "nixpkgs": nix["nixpkgs"],
            "tools": sorted(nix["tools"]),
            "absent": nix["absent"],
            "error": nix["error"],
        },
        # The deterministic half decides the SCORE; this decides whether a review
        # can run at all. Without it, doctor answered "beta 1.00" on a machine with
        # no Hermes and left the user to discover that from a failed run.
        "hermes": hermes.report(),
        "dimensions": dims_out,
        "beta_now": round(beta_now, 4),
        "builtin_tools": sorted(BUILTIN_TOOLS),
    }


def calibration_note(repo: Path) -> List[str]:
    """The caveat that decides whether a score means anything, where it is seen.

    `calibration.json` carries its own caveats and nobody reads them. `doctor` is
    where a user asks "is this machine ready?", and it answered only about
    tooling — so someone runs a review, gets FAIL, and concludes the tool is
    broken. That is the failure this prevents, and it is why the note is printed
    by default rather than behind a flag.

    It names the repository the threshold came from rather than trying to detect
    whether *this* is that repository: under `nix run` the framework lives in a
    store path, so a path comparison would never match and the note would be
    wrong in the one case it matters most.
    """
    cal = Path(__file__).resolve().parent / "calibration.json"
    if not cal.exists():
        return []
    try:
        data = json.loads(cal.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []

    out: List[str] = ["", "  the score:"]
    threshold = (data.get("threshold") or {}).get("recommended")
    if threshold is not None:
        out.append(f"    shipped threshold : {threshold}")
    out.append("    calibrated for    : the review-council repository itself")
    out.extend(
        textwrap.wrap(
            "The threshold came from that repository's own defect ladder, from ONE "
            "known-good sample, and calibration.json calls it PROVISIONAL. It is a "
            "policy value inside a measured equivalence band (80.63, 89.23): every "
            "threshold in that band gives the same verdict on all seven samples "
            "measured so far. If you are reviewing review-council the number is "
            "meaningful; for anything else it is not a pass mark. Read the score as a "
            "relative signal, or set your own bar with --threshold <n>. The FINDINGS "
            "are the portable output; the score is a local yardstick.",
            width=88,
            initial_indent="      ",
            subsequent_indent="      ",
        )
    )
    for caveat in (data.get("caveats") or [])[:2]:
        first = str(caveat).split(". ")[0].strip()
        out.extend(
            textwrap.wrap(
                "· " + first,
                width=88,
                initial_indent="    ",
                subsequent_indent="      ",
            )
        )
    return out


def render(report: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("review-council doctor")
    lines.append(f"  repo      : {report['repo']}")
    lines.append(f"  platform  : {report['platform']}")
    lines.append(f"  stacks    : {', '.join(report['stacks'])}")
    pms = [k for k, v in report["package_managers"].items() if v]
    lines.append(f"  pkg mgrs  : {', '.join(pms) if pms else '(none detected)'}")

    nix = report.get("nix") or {}
    if nix.get("available"):
        lines.append(f"  nix       : available ({nix['via']}) — pinned toolchain")
        if nix.get("nixpkgs"):
            lines.append(f"    nixpkgs : {nix['nixpkgs'][:12]}")
        if nix.get("toolchain"):
            lines.append(f"    store   : {nix['toolchain']}")
        lines.append(f"    tools   : {len(nix.get('tools') or [])} pinned"
                     + (f", {len(nix['absent'])} absent: {', '.join(nix['absent'])}"
                        if nix.get("absent") else ""))
    else:
        lines.append(f"  nix       : NOT available — {nix.get('error') or 'not detected'}")
        lines.append("    The pinned toolchain is the deterministic path. Without it, tools")
        lines.append("    fall back to whatever happens to be on PATH and drift between hosts.")

    lines.append(f"  beta now  : {report['beta_now']:.2f}  "
                 f"(0 = judgement-only, 1 = fully deterministic)")
    lines.extend(hermes.render(report.get("hermes") or {}))
    lines.append("")
    lines.append("  built-in probes (always available, no install):")
    lines.append(f"    {', '.join(report['builtin_tools'])}")
    lines.append("")
    lines.append("  per dimension:")
    for dim in report["dimensions"]:
        lines.append(f"    {dim['dimension']:<14} beta {dim['beta_now']:.2f}  "
                     f"({len(dim['available'])}/{len(dim['expected'])} tools)")
        if dim["missing"]:
            lines.append(f"        missing: {', '.join(dim['missing'])}")
    installable = [(d["dimension"], i) for d in report["dimensions"] for i in d["installable"]]
    if installable:
        lines.append("")
        lines.append("  to raise beta:")
        seen = set()
        for _dim, item in installable:
            if item["tool"] in seen:
                continue
            seen.add(item["tool"])
            lines.append(f"    {item['tool']:<12} {item['command']}")
    if report["beta_now"] < 1.0:
        lines.append("")
        lines.append("  Note: a missing analyzer does not fail the run — it lowers beta, so")
        lines.append("  the dimension is scored on reviewer judgement alone.")
        if nix.get("available"):
            lines.append("  Provision declaratively: declare the tool in")
            lines.append("  nix/builders.nix's toolNames, then rebuild with")
            lines.append("  `nix build .#toolchain`.")
    lines.extend(calibration_note(Path(report["repo"])))
    return "\n".join(lines)


def do_install(report: Dict[str, Any], assume_yes: bool) -> int:
    """Run the install commands for missing tools. Interactive unless --yes."""
    items = []
    seen = set()
    for dim in report["dimensions"]:
        for item in dim["installable"]:
            if item["tool"] not in seen and item["command"]:
                seen.add(item["tool"])
                items.append(item)
    if not items:
        print("Nothing to install — all expected tools are present.")
        return 0

    print(f"About to install {len(items)} tool(s):")
    for item in items:
        print(f"  {item['tool']:<12} {item['command']}")
    if not assume_yes:
        if not sys.stdin.isatty():
            print("\nRefusing to install without confirmation (stdin is not a TTY). "
                  "Re-run with --yes to proceed.", file=sys.stderr)
            return 2
        answer = input("\nProceed? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            print("Aborted.")
            return 1

    failures = 0
    for item in items:
        print(f"\n-> {item['tool']}: {item['command']}")
        try:
            # argv, not a shell string: nothing here needs a shell, and
            # sys.executable can contain a space ("C:\\Program Files\\...").
            proc = subprocess.run(shlex.split(item["command"]))
        except OSError as exc:
            print(f"   failed to launch: {exc}")
            failures += 1
            continue
        if proc.returncode != 0:
            print(f"   exited {proc.returncode}")
            failures += 1
        else:
            print("   ok")
    print(f"\nDone. {len(items) - failures}/{len(items)} succeeded.")
    print("Re-run doctor to confirm beta.")
    return 1 if failures else 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="doctor.py",
        description="Report the review-council's deterministic toolchain and the beta it yields.")
    parser.add_argument("--repo", default=".", help="Target repo (default: cwd)")
    parser.add_argument("--dimension", default=None, help="Restrict to one dimension")
    parser.add_argument("--json", action="store_true", help="Machine-readable output")
    parser.add_argument("--install", action="store_true", help="Install missing tools")
    parser.add_argument("--yes", action="store_true", help="Skip the install confirmation")
    parser.add_argument("--probe", action="store_true",
                        help="Also spend ONE real agent turn to prove Hermes works "
                             "(the only authoritative check; costs a turn)")
    args = parser.parse_args(argv)

    repo = Path(args.repo).expanduser().resolve()
    if not repo.is_dir():
        print(f"doctor: not a directory: {repo}", file=sys.stderr)
        return 2

    report = diagnose(repo, args.dimension)
    if args.probe:
        # L4. Opt-in because it is the only layer that costs anything, and the
        # only one that is authoritative: everything else is a proxy for it.
        report["hermes"]["capability"] = hermes.capability()

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(render(report))

    if args.install:
        return do_install(report, args.yes)
    return 0


if __name__ == "__main__":
    # Not a program: reached through `council <verb>`. See council.py.
    from council import require_dispatch

    require_dispatch("doctor")
    sys.exit(main())
