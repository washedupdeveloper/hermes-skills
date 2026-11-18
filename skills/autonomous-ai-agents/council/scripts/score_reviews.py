#!/usr/bin/env python3
"""The deterministic gate: score a run directory and decide the verdict.

Reads one JSON file per reviewer (security.json, correctness.json, ...) plus an
optional meta.json, and recomputes the hybrid score itself. It never trusts a
number a reviewer asserted, which is the point of a deterministic gate.

Exit codes: 0 satisfied, 1 not satisfied (the stdout tail is the continuation
prompt), 2 error. Input contract: docs/FRAMEWORK.md.
"""
from __future__ import annotations

import argparse
import importlib.util as _shared_util
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# `_shared` by path, like every sibling here: see its docstring for why a plain
# import is not safe.
_SHARED_SPEC = _shared_util.spec_from_file_location(
    "_shared", Path(__file__).resolve().parent / "_shared.py")
assert _SHARED_SPEC is not None and _SHARED_SPEC.loader is not None, "_shared.py"
_shared = _shared_util.module_from_spec(_SHARED_SPEC)
_SHARED_SPEC.loader.exec_module(_shared)

HERE = Path(__file__).resolve().parent

# Source suffixes for findings DENSITY (research/deterministic-quality-tooling.md §3).
SOURCE_SUFFIXES = frozenset({
    ".py", ".nix", ".sh", ".bash", ".js", ".ts", ".go", ".rs", ".c", ".h",
})

# --- The scoring table (FRAMEWORK §6) ---------------------------------------

# Aggregate weights, summing to 1.0. Working defaults; M8 calibrates.
WEIGHTS: Dict[str, float] = {
    "security": 0.30,
    "correctness": 0.25,
    "readability": 0.20,
    "architecture": 0.15,
    "performance": 0.10,
}

# Expected tools per dimension PER STACK — the beta_c denominator
# (ran_and_parsed_c / tools_expected_c). A flat table scores beta=0 on every other
# stack (DECISIONS #3); BUILTIN_TOOLS need no install, `doctor.py` names the gaps.
STACK_TOOLS: Dict[str, Dict[str, List[str]]] = {
    "security": {
        # osv-scanner reads every ecosystem's lockfile, so no pip-audit/npm-audit/
        # cargo-audit; gosec stays as a Go LINTER. gitleaks (maintained, entropy) and
        # secret-grep (zero deps) fail differently, so both. zizmor: docs/TOOLCHAIN.md.
        "python": ["bandit", "osv-scanner", "gitleaks", "secret-grep"],
        "nix": ["statix", "gitleaks", "secret-grep"],
        "javascript": ["osv-scanner", "gitleaks", "secret-grep"],
        "rust": ["osv-scanner", "gitleaks", "secret-grep"],
        "go": ["gosec", "osv-scanner", "gitleaks", "secret-grep"],
        "shell": ["shellcheck", "gitleaks", "secret-grep"],
    },
    "correctness": {
        "python": ["pytest", "py-compile"],
        "nix": ["flake-check", "nix-eval"],
        "javascript": ["jest", "tsc"],
        # The runtime lane: what the page does when loaded, which no source check can answer.
        # `browser` is a probe, not an EXTERNAL_TOOL: the driver is host-provided, and its absence
        # is reported as `ran: false` so beta drops instead of the score passing on nothing.
        "web": ["browser"],
        "rust": ["cargo-test", "cargo-check"],
        "go": ["go-test", "go-vet"],
        "shell": ["bash-n"],
    },
    "readability": {
        "python": ["ruff", "mypy"],
        "nix": ["nixfmt", "statix", "deadnix"],
        "javascript": ["eslint", "prettier"],
        "rust": ["clippy", "rustfmt"],
        "go": ["gofmt", "golint"],
        "shell": ["shellcheck"],
    },
    "performance": {
        "python": ["complexity"],
        # Four signals, because one was not enough: `nix-eval-time` is informational
        # without a pinned baseline. The other three are absolute and cheap — IFD breaks
        # eval caching, a missing store cache rebuilds every run, a missing key wastes runs.
        "nix": ["ifd", "ci-cache", "ci-concurrency", "nix-eval-time"],
        "javascript": ["bundle-size"],
        "rust": ["cargo-bench"],
        "go": ["go-bench"],
        "shell": ["ci-cache", "ci-concurrency"],
    },
    "architecture": {
        "python": ["dep-graph", "declared-rules"],
        "nix": ["dep-graph", "declared-rules"],
        "javascript": ["dep-graph", "declared-rules"],
        "rust": ["dep-graph", "declared-rules"],
        "go": ["dep-graph", "declared-rules"],
        "shell": ["declared-rules"],
    },
}

# Tools the framework implements itself (scripts/probes.py), so they always "ran":
# no installation, which keeps the framework runnable on a bare machine.
BUILTIN_TOOLS: frozenset = frozenset({
    "secret-grep", "py-compile", "bash-n", "complexity", "dep-graph", "declared-rules",
    # Pure text; no toolchain needed, so they run everywhere.
    "ci-cache", "ci-concurrency",
})

# probes.py wrappers around the PINNED nix toolchain: no binary of their own, so they
# are available whenever the toolchain resolves. Every expected tool now has a probe,
# which makes the deterministic half a property of the harness.
NIX_PROBE_TOOLS: frozenset = frozenset({
    "statix", "deadnix", "nixfmt", "flake-check", "nix-eval", "nix-eval-time",
    "ruff", "mypy", "bandit", "osv-scanner", "pytest",
    # Needs `nix` (it evaluates with IFD disabled), unlike the two BUILTIN CI text
    # probes.
    "ifd",
})

# Tools expected regardless of stack — cheap, always-applicable checks.
GENERIC_TOOLS: Dict[str, List[str]] = {
    "security": [],
    "correctness": [],
    "readability": [],
    "performance": [],
    "architecture": [],
}

#: Expected-tool names that are EXTERNAL BINARIES: the toolchain must ship them or beta
#: is capped by the packaging. Every other name is a probe in scripts/probes.py; the
#: sets are disjoint and cover everything (tests/test_probes.py asserts it).
EXTERNAL_TOOLS = frozenset({
    # security
    "bandit", "gitleaks", "gosec", "osv-scanner", "shellcheck", "statix",
    # correctness
    "cargo-check", "cargo-test", "go-test", "go-vet", "jest", "pytest", "tsc",
    # readability
    "clippy", "deadnix", "eslint", "gofmt", "golint", "mypy", "nixfmt", "prettier",
    "ruff", "rustfmt",
    # performance
    "cargo-bench", "go-bench",
})


# Stack detection: marker files and extensions, in precedence order.
STACK_MARKERS: Dict[str, Tuple[str, ...]] = {
    "nix": ("flake.nix", "default.nix", "shell.nix"),
    "python": ("pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "tox.ini"),
    "javascript": ("package.json", "tsconfig.json"),
    # A page that can be LOADED, which is a different question from "is there JavaScript in here".
    # The marker is the entry point, so a JS library with no page stays out of the runtime lane and
    # is never penalised for it.
    "web": (
        "index.html",
        "public/index.html",
        "src/index.html",
        "vite.config.ts",
        "vite.config.js",
        "next.config.js",
        "next.config.mjs",
        "svelte.config.js",
        "astro.config.mjs",
        "nuxt.config.ts",
        # App-Router and Pages-Router projects have no root HTML to load: they need a server, which
        # is what `$COUNCIL_WEB_URL` is for. Detected here so the stack is still `web` and the
        # reviewer is told the runtime was not observed rather than being scored as if there were
        # nothing to observe.
        "app/page.tsx",
        "app/page.jsx",
        "pages/index.tsx",
        "pages/index.jsx",
    ),
    "rust": ("Cargo.toml",),
    "go": ("go.mod",),
    "shell": ("Makefile",),
}

STACK_EXTENSIONS: Dict[str, Tuple[str, ...]] = {
    "nix": (".nix",),
    "python": (".py",),
    "javascript": (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"),
    "web": (),
    "rust": (".rs",),
    "go": (".go",),
    "shell": (".sh", ".bash"),
}

# Directory names never walked during stack detection.
_SKIP_DIRS = frozenset({
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
    "env", ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache", "target",
    "dist", "build", ".next", ".nuxt", "result", ".review-council",
})


def detect_stacks(root: Path, max_files: int = 4000) -> List[str]:
    """Detect the language stacks present in *root*.

    Returns stack names in a stable order (marker files first, then by source
    extension counts). Falls back to ``["generic"]`` when nothing is recognised,
    so beta is 0 rather than undefined.
    """
    found: List[str] = []
    if root.is_dir():
        for stack, markers in STACK_MARKERS.items():
            if any((root / m).exists() for m in markers):
                found.append(stack)

    counts: Dict[str, int] = {}
    seen = 0
    if root.is_dir():
        for path in root.rglob("*"):
            if seen >= max_files:
                break
            if not path.is_file():
                continue
            # Relative to *root*, not absolute: a checkout under a directory named
            # `build` or `target` would otherwise skip every file.
            if any(part in _SKIP_DIRS for part in path.relative_to(root).parts):
                continue
            seen += 1
            suffix = path.suffix.lower()
            for stack, exts in STACK_EXTENSIONS.items():
                if suffix in exts:
                    counts[stack] = counts.get(stack, 0) + 1
                    break

    # Marker-detected stacks first (authoritative), then any stack owning >= 2 files.
    for stack in sorted(counts, key=lambda s: -counts[s]):
        if stack not in found and counts[stack] >= 2:
            found.append(stack)

    return found or ["generic"]


def stack_shares(root: Path, max_files: int = 4000) -> Dict[str, float]:
    """Each detected stack's share of the repository's SOURCE LINES.

    `detect_stacks` answers "is this language present", which is the right question for
    display and the wrong one for beta. A repository with two incidental Python files
    made `pytest`, `ruff`, `mypy` and `bandit` *expected*, so beta fell to 0.667 and the
    deterministic half was reported as incomplete when it had covered everything that
    mattered. Measured on `nix-direnv`: a Nix+shell project, scored as if a third of its
    obligations were Python.

    Lines, not file count: one 900-line module is a bigger commitment than nine
    three-line scripts.
    """
    lines: Dict[str, int] = {}
    seen = 0
    if not root.is_dir():
        return {}
    for path in root.rglob("*"):
        if seen >= max_files:
            break
        if not path.is_file():
            continue
        if any(part in _SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        seen += 1
        suffix = path.suffix.lower()
        for stack, exts in STACK_EXTENSIONS.items():
            if suffix in exts:
                try:
                    n = sum(1 for _ in path.open("rb"))
                except OSError:
                    break
                lines[stack] = lines.get(stack, 0) + n
                break
    total = sum(lines.values())
    if total <= 0:
        return {}
    return {stack: n / total for stack, n in lines.items()}


def relevant_stacks(root: Path, min_share: float = 0.10) -> List[str]:
    """The stacks that carry enough of the code to justify expecting tools for them.

    A stack must own at least *min_share* of the source lines. When nothing clears the
    bar — a Makefile-only repository has a marker but almost no counted source — the
    marker-detected stacks are kept, so a real project is never scored as `generic`.
    """
    present = detect_stacks(root)
    shares = stack_shares(root)
    if not shares:
        return present
    kept = [s for s in present if shares.get(s, 0.0) >= min_share]
    if kept:
        # Dominant stack first, so `expected_tools` reads naturally.
        return sorted(kept, key=lambda s: -shares.get(s, 0.0))
    # Nothing cleared the bar: keep stacks that own any lines, not `generic` — else beta
    # is lost.
    fallback = [s for s in present if shares.get(s, 0.0) > 0]
    if fallback:
        return sorted(fallback, key=lambda s: -shares.get(s, 0.0))
    return present


def expected_tools(dimension: str, stacks: List[str]) -> List[str]:
    """The union of expected tools for *dimension* across every detected stack,
    plus the stack-independent generics. Order-preserving, deduped."""
    out: List[str] = []
    for stack in stacks or ["generic"]:
        for tool in STACK_TOOLS.get(dimension, {}).get(stack, []):
            if tool not in out:
                out.append(tool)
    for tool in GENERIC_TOOLS.get(dimension, []):
        if tool not in out:
            out.append(tool)
    return out

# Uncalibrated Hill defaults for findings density (FRAMEWORK §6 shape): the measured
# d* and threshold live in docs/CALIBRATION.md.
HILL_K = 5.0
HILL_N = 1.2

# FALLBACK pass threshold, used only when scripts/calibration.json is missing or
# unreadable; the calibrated value wins (calibrated_threshold). Falling back rather
# than failing is deliberate: an uncalibrated checkout still runs.
DEFAULT_THRESHOLD = 80.0

# Blocking severities (FRAMEWORK §5/§6). Security and correctness block at `high`: 93 of
# 94 blocking findings across nine well-regarded repos were those two. The rest block
# only at `critical`, so a style defect moves the score but keeps an absolute floor.
BLOCKING_SEVERITIES: Dict[str, frozenset] = {
    "security": frozenset({"high", "critical"}),
    "correctness": frozenset({"high", "critical"}),
    "readability": frozenset({"critical"}),
    "architecture": frozenset({"critical"}),
    "performance": frozenset({"critical"}),
}
# An unrecognised dimension gets the strict floor, not the lenient one: a dimension
# nobody classified must not pass on a `high`.
DEFAULT_BLOCKING: frozenset = frozenset({"high", "critical"})

# Severity weights for the density numerator (§3: severity-weighted per KLOC, not raw).
# `info` is 0 — counting notes made a thorough reviewer score WORSE than a silent one.
# `low` is 1.0: the calibration's scale anchor, so reweighting it invalidates every d_star.
SEVERITY_WEIGHT: Dict[str, float] = {
    "critical": 4.0,
    "high": 3.0,
    "medium": 2.0,
    "low": 1.0,
    "info": 0.0,
}
# An unrecognised severity counts as a real finding rather than being dropped: silence
# about a defect is the worse failure, and the rubrics' enum is closed.
DEFAULT_SEVERITY_WEIGHT = 1.0


# --- Scoring math -----------------------------------------------------------

def hill_curve(x: float, k: float = HILL_K, n: float = HILL_N) -> float:
    """Findings density -> 0-100. `100 / (1 + (x/K)^n)` (FRAMEWORK §6)."""
    if x <= 0:
        return 100.0
    return 100.0 / (1.0 + (x / k) ** n)


# --- calibration (M8) -------------------------------------------------------
# See docs/CALIBRATION.md for d*, the threshold and the manifest. Without a manifest
# the scorer falls back to the count curve and still runs — it just says so.

CALIBRATION_PATH = HERE / "calibration.json"
_CALIBRATION: Optional[Dict[str, Any]] = None
_CALIBRATION_LOADED = False


def calibration_path(scale: str) -> Path:
    """Where the threshold for one scoring scale lives.

    Two scales coexist: `deterministic` (what calibrate.py has always measured) and `claims`
    (aggregates capped by proven defects). One file would let a corpus run overwrite the threshold
    the other scale still depends on.
    """
    if scale == "deterministic":
        return CALIBRATION_PATH
    return HERE / f"calibration.{scale}.json"


def load_scale_calibration(scale: str) -> Optional[Dict[str, Any]]:
    """The manifest for one scale, or None when no threshold was derived for it."""
    if scale == "deterministic":
        return load_calibration()
    return load_calibration(calibration_path(scale))


def load_calibration(path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """Load the calibration manifest, or None when the repo is uncalibrated."""
    global _CALIBRATION, _CALIBRATION_LOADED
    if path is None and _CALIBRATION_LOADED:
        return _CALIBRATION
    target = path or CALIBRATION_PATH
    data: Optional[Dict[str, Any]] = None
    if target.exists():
        try:
            data = json.loads(target.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            data = None
    if path is None:
        _CALIBRATION, _CALIBRATION_LOADED = data, True
    return data


def calibrated_threshold() -> float:
    """The shipped pass threshold: the calibrated recommendation, else the fallback.

    ONE source of truth. The threshold is calibrated (docs/CALIBRATION.md) to the
    midpoint of the separating plateau on the graded defect ladder, which
    maximises the margin to BOTH classes — a floor-of-plateau value leaves a bad
    sample one rounding step from passing. Reading it from the manifest means a
    recalibration cannot drift away from the number the gate actually enforces;
    the old arrangement had the value hardcoded in three places.
    """
    cal = load_calibration() or {}
    block = cal.get("threshold") or {}
    raw = block.get("recommended")
    if raw is None:
        return DEFAULT_THRESHOLD
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_THRESHOLD
    return value if value > 0 else DEFAULT_THRESHOLD


def kloc(root: Optional[Path]) -> float:
    """Thousands of source lines — the denominator for findings density.

    Returns 0.0 when the repo is unknown, which switches the scorer back to raw
    counts (you cannot normalise by a size you have not measured).
    """
    if root is None or not root.is_dir():
        return 0.0
    return _shared.kloc(root)


def hill_density(density: float, dimension: Optional[str] = None,
                 calibration: Optional[Dict[str, Any]] = None) -> float:
    """Density-based Hill curve using the CALIBRATED d* (§7 steps 2-3).

    d* is the density at which the term scores 50.

    The pooled d* is the median of the tools that produced a REAL baseline
    reading. Tools whose known-good density was zero are floored (d* = 0.05,
    meaning "almost any finding is serious"), which is the right behaviour
    per-tool — a single leaked secret should be near-fatal — but a terrible
    shared reference: most tools find nothing on clean code, so the median over
    ALL tools collapses to the floor and drags every dimension to ~6/100.
    Excluding floor-bound tools leaves the one or two analyzers that have a
    meaningful known-good density, which is what a shared curve should be
    anchored to.
    """
    cal = calibration if calibration is not None else load_calibration()
    k = HILL_N
    d_star = HILL_K
    if cal:
        k = float(cal.get("halflife_k") or HILL_N)
        table = cal.get("d_star") or {}
        anchored = sorted(
            v["d_star"] for v in table.values()
            if isinstance(v, dict) and isinstance(v.get("d_star"), (int, float))
            and not v.get("floored")
        )
        all_values = sorted(
            v["d_star"] for v in table.values()
            if isinstance(v, dict) and isinstance(v.get("d_star"), (int, float))
        )
        pooled = anchored or all_values
        if pooled:
            d_star = pooled[len(pooled) // 2]
    if density <= 0:
        return 100.0
    return 100.0 / (1.0 + (density / max(d_star, 1e-9)) ** k)


def weighted_geometric_mean(pairs: List[Tuple[float, float]]) -> float:
    """Weighted geometric mean of (value, weight); one failing term is not
    diluted by passing ones (FRAMEWORK §6: "weighted geometric mean, so one
    failing tool is not diluted by passing ones").

    A zero value with nonzero weight collapses the mean to 0, which is the
    intended hard behavior. A value of exactly 0 is floored to 1e-6 so the
    log is defined and the result stays distinguishable from a real 0.
    """
    total_w = sum(w for _, w in pairs if w > 0)
    if total_w <= 0:
        return 100.0
    acc = 0.0
    for value, weight in pairs:
        if weight <= 0:
            continue
        v = max(min(value, 100.0), 1e-6)
        acc += weight * math.log(v)
    return math.exp(acc / total_w)


# Runner tokens that prefix a tool invocation without being the tool.
_RUNNERS = frozenset({"python", "python3", "py", "uv", "uvx", "npx", "node",
                      "poetry", "pipx", "sh", "bash", "env"})

# Invocations whose canonical name is not derivable from the command's words: the reviewer
# reports what it TYPED, STACK_TOOLS names the TOOL. Without these,
# `nix flake check --no-build --keep-going` yields {nix, nix-flake}, never `flake-check` — beta halved.
_INVOCATION_ALIASES: Tuple[Tuple[str, str], ...] = (
    ("nix flake check", "flake-check"),
    ("nix-instantiate", "nix-eval"),
    ("nix eval", "nix-eval"),
)


def tool_name_candidates(name: str) -> set:
    """Every plausible canonical form of a reported tool name.

    Matching against a SET rather than one string is what makes beta robust:
    a reviewer may report `py_compile`, `py-compile`, `python -m py_compile`,
    `python3 -m py_compile`, `/usr/bin/ruff`, `ruff.exe`, or `cargo test`, and
    all of them must resolve to the tool the table expects. A single-character
    or invocation-style mismatch silently zeroing a dimension's beta is exactly
    the class of bug this prevents.
    """
    raw = str(name or "").strip().lower().replace("_", "-")
    if not raw:
        return set()

    def clean(token: str) -> str:
        """A token with any path prefix and a Windows extension removed."""
        bits = [p for p in re.split(r"[\\/]", token) if p]
        base = bits[-1] if bits else token
        return base[:-4] if base.endswith(".exe") else base

    tokens = raw.split()
    # Skip leading `NAME=value`: `PATH=/x/bin:$PATH ruff check` runs ruff, not PATH.
    while tokens and re.match(r"^[a-z_][a-z0-9_]*=", tokens[0]):
        tokens.pop(0)
    if not tokens:
        return set()

    # Only the EXECUTABLE is path-stripped: stripping the whole string took the last
    # ARGUMENT's tail, so `python3 -m pytest tests/ -q` resolved to `-q` and never matched.
    exe = clean(tokens[0])
    out: set = {exe}
    # First two tokens joined (`cargo test` -> cargo-test).
    if len(tokens) > 1:
        out.add(f"{exe}-{clean(tokens[1])}")
    # Module invocation (`python -m py_compile` -> py-compile).
    if "-m" in tokens:
        idx = tokens.index("-m")
        if idx + 1 < len(tokens):
            out.add(clean(tokens[idx + 1]))
    # Runner + subcommand; `-m` is the module form above, not a subcommand.
    if exe in _RUNNERS and len(tokens) > 1 and tokens[1] != "-m":
        out.add(clean(tokens[1]))

    # Invocations the generic rules cannot resolve, mapped explicitly.
    for invocation, canonical in _INVOCATION_ALIASES:
        if invocation in raw:
            out.add(canonical)

    out.discard("")
    return out


def normalize_tool_name(name: str) -> str:
    """A single canonical form, for display. Prefer the shortest candidate that
    is not a bare runner."""
    candidates = tool_name_candidates(name)
    if not candidates:
        return ""
    ordered = sorted(candidates, key=lambda c: (c in _RUNNERS, len(c)))
    return ordered[0]


def measure_beta(tools_run: List[Dict[str, Any]], dimension: str,
                 stacks: Optional[List[str]] = None) -> Tuple[float, List[str], List[str]]:
    """beta = ran_and_parsed / expected, MEASURED from the run (FRAMEWORK §6).

    *stacks* are the language stacks detected in the target repo; the expected
    set is the union of that dimension's tools across those stacks. A dimension
    with no expected tools has beta 0.0 — judgement-only, and the run says so.

    Returns (beta, ran_names, missing_names).
    """
    expected = expected_tools(dimension, stacks or ["generic"])
    if not expected:
        return 0.0, [], []

    ran: set = set()
    for tool in tools_run:
        if tool.get("ran") and tool.get("parsed", True):
            # Three producers write this field: `cmd` (reviewer JSON), `tool` (a probe
            # result) and `name` (older reports). Reading only one drops that
            # producer's whole contribution.
            ran |= tool_name_candidates(
                tool.get("name") or tool.get("cmd") or tool.get("tool") or "")

    hit = [e for e in expected if tool_name_candidates(e) & ran]
    miss = [e for e in expected if not (tool_name_candidates(e) & ran)]
    return len(hit) / len(expected), hit, miss


def weighted_open_findings(findings: Optional[List[Dict[str, Any]]]) -> float:
    """Open findings as a SEVERITY-WEIGHTED count (§3).

    A raw count makes a thorough reviewer score worse than a silent one, because
    the rubrics record what they verified at `info` as well as what they found
    broken. Weighting by severity keeps the defect signal and drops the note.
    """
    total = 0.0
    for finding in findings or []:
        if str(finding.get("status", "open")) != "open":
            continue
        severity = str(finding.get("severity") or "").strip().lower()
        total += SEVERITY_WEIGHT.get(severity, DEFAULT_SEVERITY_WEIGHT)
    return total


def deterministic_score(review: Dict[str, Any], dimension: str,
                        stacks: Optional[List[str]] = None,
                        size_kloc: float = 0.0) -> Tuple[float, float, List[str]]:
    """det_c and beta_c for one dimension.

    det is derived only from signals that actually ran. With beta = 0 the det
    term is inert by construction (`score = 0*det + 1*llm`), so a vacuous det
    cannot inflate the score — the failure mode the run log flagged when a
    zero-Nix repo made Nix-pattern greps trivially "clean".

    *size_kloc* is the target's size in thousands of source lines. When it is
    known the findings term is a DENSITY (§3); when it is not, the scorer falls
    back to a raw count, because you cannot normalise by a size you have not
    measured.
    """
    tools_run = review.get("tools_run") or []
    expected = expected_tools(dimension, stacks or ["generic"])
    beta, _ran, missing = measure_beta(tools_run, dimension, stacks)

    # §6: det[c] = geometric_mean(normalize(tool_signals_c)) — THIS category's tools
    # only. Averaging every tool into every category made readability depend on bandit
    # and security on mypy; at beta = 1 det IS the score, so that leak decides the verdict.
    wanted: set = set()
    for name in expected:
        wanted |= tool_name_candidates(name)

    signals: List[Tuple[float, float]] = []
    for tool in tools_run:
        if not (tool.get("ran") and tool.get("parsed", True)):
            continue
        name = tool.get("name") or tool.get("cmd") or tool.get("tool") or ""
        if not (tool_name_candidates(name) & wanted):
            continue
        # An explicit 0-100 `signal` is trusted; a clean run defaults to 100 (no
        # findings), and findings density below is what moves it down.
        raw = tool.get("signal")
        signals.append((float(raw) if isinstance(raw, (int, float)) else 100.0, 1.0))

    det = weighted_geometric_mean(signals) if signals else 0.0

    # Findings density for the dimension, as a second deterministic term. §3:
    # severity-weighted findings per KLOC, NOT a raw count — a raw count scores a
    # 100-line file with 5 findings like a 10,000-line repo with 5.
    open_findings = weighted_open_findings(review.get("findings"))
    if size_kloc > 0:
        # The same floor the claims term uses, for the same reason: without it a 56-line tree
        # scores WORSE than a 16-defect tree for the same findings, because density divides by a
        # size so small that everything saturates. Measured on the in-place corpus: flooring here
        # moved the good/bad margin from +7.81 to +20.41.
        density_score = hill_density(open_findings / max(size_kloc, MIN_KLOC))
    else:
        density_score = hill_curve(float(open_findings))
    det = weighted_geometric_mean([(det, 0.7), (density_score, 0.3)]) if signals else density_score

    return det, beta, missing


#: Below this, a findings DENSITY is meaningless: one medium finding in a 56-line file is "denser"
#: than ten in a 10k-line repository, so every score collapses into the same band. Measured on the
#: first corpus: four rungs spanning 0 to 16 seeded defects all scored 39–44, and the 16-defect rung
#: outscored the clean one. The floor does not change a real repository's arithmetic — it only
#: stops a tiny tree from being scored as if every line were defective.
MIN_KLOC = 1.0

#: What a *proven* defect does to its dimension's number, by severity.
#:
#: The blend alone cannot carry this. On a fully-probed run every dimension has β = 1.00, so
#: `score = det` and the claims term is multiplied by zero — measured on a real round: security
#: det 71.75 with a confirmed committed credential, unchanged by either scoring mode. A cap is the
#: same mechanism the gate already uses for observed runtime failure, and it cannot be diluted by
#: a tool that happened to be quiet.
CLAIM_CAPS = {"critical": 30.0, "high": 60.0, "medium": 85.0}


def claim_cap(records: List[Dict[str, Any]]) -> Optional[float]:
    """The hardest cap implied by the *confirmed* claims in one dimension, or None.

    Uses `severity_scored`, not `severity`: a severity the evidence does not corroborate is held at
    `high` by adjudication, so an asserted `critical` cannot set the ceiling on its own word. Old
    records without the field fall back to `severity`.
    """

    def scored(record: Dict[str, Any]) -> str:
        return str(record.get("severity_scored") or record.get("severity"))

    caps = [CLAIM_CAPS[scored(record)] for record in records
            if record.get("state") == "confirmed" and scored(record) in CLAIM_CAPS]
    return min(caps) if caps else None


def claims_score(records: List[Dict[str, Any]], size_kloc: float) -> float:
    """A dimension's score from the claims that were PROVEN, and only those.

    This is the M-E change: the number no longer comes from the reviewer's opinion of its own
    dimension, but from the severity-weighted density of the defects it proved. A dimension with
    nothing proven scores 100 — not because it was called clean, but because nothing was shown
    wrong in it. `unsettled` claims deliberately do not lower the score: they are not known
    defects, and they block certification through their own route.

    Same severity weights and same Hill curve as the deterministic half, on purpose: two numbers
    on different scales inside one blend would be unreadable.
    """
    confirmed = [{"severity": record.get("severity"), "status": "open"}
                 for record in records if record.get("state") == "confirmed"]
    weighted = weighted_open_findings(confirmed)
    if size_kloc > 0:
        return hill_density(weighted / max(size_kloc, MIN_KLOC))
    return hill_curve(weighted)


def score_dimension(review: Dict[str, Any], dimension: str,
                    stacks: Optional[List[str]] = None,
                    size_kloc: float = 0.0,
                    adjudication: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """score[c] = beta*det + (1-beta)*llm (FRAMEWORK §6).

    *adjudication* replaces the reviewer's `score` with the claims-derived number when the round
    was adjudicated. The substitution is recorded per dimension, because a reader comparing two
    runs has to know which scale each number is on.
    """
    if adjudication is None:
        llm = float(review.get("score") or 0.0)
        source = "reviewer"
        mine: List[Dict[str, Any]] = []
    else:
        mine = [record for record in (adjudication.get("findings") or [])
                if record.get("dimension") == dimension]
        llm = claims_score(mine, size_kloc)
        source = "claims"
    det, beta, missing = deterministic_score(review, dimension, stacks, size_kloc)
    score = beta * det + (1.0 - beta) * llm
    cap = claim_cap(mine) if adjudication is not None else None
    if cap is not None and score > cap:
        score = cap
    return {
        "dimension": dimension,
        "llm": round(llm, 2),
        "det": round(det, 2),
        "beta": round(beta, 4),
        "score": round(score, 2),
        "source": source,
        "cap": cap,
        "tools_missing": missing,
    }


# --- Aggregation ------------------------------------------------------------

def open_blocking(reviews: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Open findings at a blocking severity for their dimension.

    Security and correctness are the hard requirements: a `high` there blocks, because
    the observed cost of getting one wrong is a supply-chain compromise or a broken
    build. The other dimensions block only at `critical` — a readability or performance
    defect should move the score, not veto a merge the way a security hole does. A
    `critical` anywhere still blocks, so no dimension loses its absolute floor.

    Measured against nine well-regarded repositories: 93 of 94 blocking findings were
    security or correctness, so this narrows an untested path rather than loosening the
    rule that actually fired.
    """
    out: List[Dict[str, Any]] = []
    for dimension, review in reviews.items():
        blocking_sev = BLOCKING_SEVERITIES.get(dimension, DEFAULT_BLOCKING)
        for finding in review.get("findings") or []:
            severity = str(finding.get("severity") or "").strip().lower()
            status = str(finding.get("status") or "open").strip().lower()
            if status in {"fixed", "wontfix", "accepted", "closed"}:
                continue
            if severity in blocking_sev:
                out.append({"dimension": dimension, **finding})
    return out


def resolve_repo(run_dir: Path, repo: Optional[Path] = None) -> Optional[Path]:
    """The target repo, from --repo or from the run's own meta.json.

    The harness records the repo in meta.json, so a run dir is self-describing.
    Without this fallback the same run dir scores DIFFERENTLY depending on how the
    gate is invoked: with `--repo` the findings term is a calibrated density, and
    without it the gate falls back to the uncalibrated count curve. A score that
    depends on the invocation rather than on the data is not reproducible.
    """
    if repo is not None:
        return repo
    meta = run_dir / "meta.json"
    if meta.exists():
        try:
            recorded = json.loads(meta.read_text(encoding="utf-8-sig")).get("repo")
        except (OSError, json.JSONDecodeError):
            recorded = None
        if recorded:
            candidate = Path(recorded)
            if candidate.is_dir():
                return candidate
    return None


def resolve_stacks(run_dir: Path, repo: Optional[Path] = None) -> List[str]:
    """Stacks for beta: the run's own meta.json wins, else detect from --repo,
    else the run dir's parent (the repo the loop ran against)."""
    meta = run_dir / "meta.json"
    if meta.exists():
        try:
            payload = json.loads(meta.read_text(encoding="utf-8-sig"))
            declared = payload.get("stacks") or payload.get("stack")
            if isinstance(declared, str) and declared.strip():
                return [declared.strip()]
            if isinstance(declared, list) and declared:
                return [str(s).strip() for s in declared if str(s).strip()]
        except (OSError, json.JSONDecodeError):
            pass
    target = repo
    if target is None:
        # <repo>/.review-council/<stamp>/round-N -> walk up to the repo root.
        for parent in run_dir.parents:
            if (parent / ".git").exists() or (parent / "flake.nix").exists():
                target = parent
                break
    if target is not None and target.is_dir():
        # relevant_stacks, not detect_stacks: beta asks whether the tools for the languages
        # this repo is MADE OF ran. An incidental Python file made pytest, ruff, mypy and
        # bandit expected, which depressed beta on repos with nothing to test in Python.
        return relevant_stacks(target)
    return ["generic"]


def _error_result(reason: str, **extra: Any) -> Dict[str, Any]:
    """The shape of a non-verdict. A council that could not be evaluated must be
    distinguishable from one that was evaluated and failed — both are not-passes,
    but only the second is evidence about the code."""
    return {"status": "error", "reason": reason, "per_dimension": [],
            "aggregate": None, **extra}


def load_reviews(run_dir: Path) -> Tuple[Dict[str, Dict[str, Any]], List[str], List[str]]:
    """Load each dimension's reviewer JSON.

    Returns (reviews, missing, invalid) rather than raising, so the caller can
    decide whether a partial council is fatal (it is, by default) or merely
    scored on what is present.
    """
    reviews: Dict[str, Dict[str, Any]] = {}
    missing: List[str] = []
    invalid: List[str] = []

    for dimension in WEIGHTS:
        path = run_dir / f"{dimension}.json"
        if not path.exists():
            missing.append(dimension)
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            invalid.append(f"{dimension}: {exc}")
            continue
        if payload.get("schema_valid") is False:
            invalid.append(f"{dimension}: child reported schema_valid=false")
            continue
        reviews[dimension] = payload

    return reviews, missing, invalid


def renormalized_aggregate(present: Dict[str, float],
                           per_dimension: List[Dict[str, Any]]) -> float:
    """Weighted mean over the dimensions actually present.

    Weights are renormalized so a partial run is scored on what it reviewed
    rather than silently diluted toward zero by the absent dimensions.
    """
    total_weight = sum(present.values()) or 1.0
    return sum(
        (present[d] / total_weight)
        * next(p["score"] for p in per_dimension if p["dimension"] == d)
        for d in present
    )


def verdict_summary(aggregate: float, threshold: float,
                    blocking: List[Dict[str, Any]]) -> Tuple[bool, str]:
    """The pass/fail decision and its human-readable reason.

    Extracted so the single most consequential predicate in the framework —
    "does this aggregate AND the absence of open high/critical findings certify a
    pass" — is independently testable rather than buried in a 100-line loader.
    """
    reasons: List[str] = []
    if aggregate < threshold:
        reasons.append(f"aggregate {aggregate:.2f} < threshold {threshold:g}")
    if blocking:
        reasons.append(f"{len(blocking)} open high/critical finding(s)")
    satisfied = aggregate >= threshold and not blocking
    return satisfied, ("; ".join(reasons) or
                       "aggregate >= threshold and no blocking findings")


ADJUDICATED = frozenset({"confirmed", "refuted", "unsettled", "unrunnable"})


def load_proofs(run_dir: Path) -> Optional[Dict[str, Any]]:
    """The round's adjudication, or None when nothing was adjudicated.

    None and an empty report mean different things: "nobody ran the checks" versus "the checks ran
    and there was nothing to check". Only the second can open a gate.
    """
    path = run_dir / "proofs.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _adjudication_index(payload: Dict[str, Any]) -> Dict[Any, Dict[str, Any]]:
    index: Dict[Any, Dict[str, Any]] = {}
    for record in payload.get("findings") or []:
        if not isinstance(record, dict):
            continue
        if record.get("id"):
            index[str(record["id"])] = record
        location = record.get("location") or {}
        index[(record.get("dimension"), str(location.get("path")), str(location.get("line_range")))] = record
    return index


def apply_proofs(blocking: List[Dict[str, Any]],
                 payload: Optional[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Split blocking findings into (still blocking) and (unsettled) using the adjudication.

    Only `refuted` clears a finding. `confirmed` still blocks — it is a real defect. Anything else,
    including a finding the adjudication never saw, is unresolved and blocks for the other reason:
    nobody settled it. Returning all of them as unresolved when there is no report is deliberate;
    an enforcement mode that silently passes because the report is missing would be a back door.
    """
    if payload is None:
        return [], [{**finding, "_adjudication": "missing"} for finding in blocking]
    index = _adjudication_index(payload)
    still_blocking: List[Dict[str, Any]] = []
    unresolved: List[Dict[str, Any]] = []
    for finding in blocking:
        location = finding.get("location") or {}
        record = (index.get(str(finding.get("id")))
                  or index.get((finding.get("dimension"), str(location.get("path")),
                                str(location.get("line_range")))))
        state = (record or {}).get("state")
        if state == "refuted":
            continue
        if state == "confirmed":
            still_blocking.append({**finding, "_adjudication": state,
                                   "_reason": (record or {}).get("reason")})
            continue
        unresolved.append({**finding, "_adjudication": state or "missing",
                           "_reason": (record or {}).get("reason")})
    return still_blocking, unresolved


def certification(satisfied: bool, blocking: List[Dict[str, Any]],
                  unresolved: List[Dict[str, Any]], *, calibrated: bool = True,
                  coverage_gap: bool = False) -> str:
    """The verdict's state, named.

    `unsatisfied` means a real defect or a score short of the bar — something to fix.
    `unprovable` means nothing was found that is *proven* wrong, and something blocking could not be
    settled — or nothing was settled at all where the toolchain saw something. `uncalibrated` means
    the number itself cannot be compared to the threshold. Those are four different answers and a
    caller must be able to tell them apart without parsing prose.
    """
    if blocking:
        return "unsatisfied"
    if unresolved or coverage_gap:
        return "unprovable"
    if not calibrated:
        return "uncalibrated"
    return "certified" if satisfied else "unsatisfied"


def probe_defect_count(run_dir: Path) -> int:
    """How many defects the probes observed — the ones that could have blocked.

    A finding counts when it is `medium`, `high` or `critical`, or when it names no severity at
    all: an unlabelled probe finding is not evidence that the reviewer was entitled to ignore it,
    so it stays conservative. `low` findings do not count, because they cannot block on their own,
    and counting them made a clean tree uncertifiable whenever the reviewer correctly stayed
    silent. Measured: three clean rungs of one corpus, one silent reviewer, and `deadnix: unused
    lambda` plus "no AGENTS.md" — both `low` — turned a correct run into `unprovable` and cost the
    corpus a rung. `medium` does count: a bandit medium or a complexity ratio ≥ 2 is a defect a
    silent reviewer missed, and excluding it would reopen the hole this rule exists to close.
    """
    path = Path(run_dir) / "probes.json"
    if not path.exists():
        return 0
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return 0
    if not isinstance(payload, list):
        return 0
    total = 0
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        for finding in entry.get("findings") or []:
            severity = str((finding or {}).get("severity") or "").strip().lower() \
                if isinstance(finding, dict) else ""
            if severity in ("", "medium", "high", "critical"):
                total += 1
    return total


def coverage_gap(run_dir: Path, adjudication: Optional[Dict[str, Any]]) -> Optional[str]:
    """The blind-reviewer hole, as a rule.

    Claims scoring moves only when the reviewer proves something. A reviewer that reports nothing
    therefore scores 100 on a defective repository, and nothing blocks, because there is no claim to
    block on. So: if the probes observed a defect and the adjudication settled *no* claim at all
    (neither confirmed nor refuted), return why. The run is `unprovable` — nobody looked, and the
    toolchain says there was something to look at.
    """
    observed = probe_defect_count(run_dir)
    if not observed:
        return None
    records = (adjudication or {}).get("findings") or []
    settled = [r for r in records if r.get("state") in ("confirmed", "refuted")]
    if settled:
        return None
    return (f"the probes observed {observed} defect(s) and the reviewer settled no claim about any "
            f"of them — a run that proves nothing cannot be certified against a run that found "
            f"something")


def threshold_from_scale(payload: Optional[Dict[str, Any]]) -> Optional[float]:
    """The threshold a scale's manifest recommends, in either shipped shape.

    `calibration.json` nests it as `threshold.recommended`; a corpus derivation writes
    `threshold` as a number and repeats it under `recommended_threshold`. Reading only one
    shape is how a derived threshold ends up loaded, reported as calibrated, and never
    enforced.
    """
    if not payload:
        return None
    block = payload.get("threshold")
    if isinstance(block, dict):
        for key in ("recommended", "threshold"):
            value = block.get(key)
            if value is not None:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    return None
        return None
    if isinstance(block, (int, float)):
        return float(block)
    recommended = payload.get("recommended_threshold")
    if isinstance(recommended, dict) and recommended.get("threshold") is not None:
        try:
            return float(recommended["threshold"])
        except (TypeError, ValueError):
            return None
    return None


def evaluate(run_dir: Path, threshold: Optional[float] = None,
             allow_partial: bool = False,
             stacks: Optional[List[str]] = None,
             repo: Optional[Path] = None, require_proof: bool = True) -> Dict[str, Any]:
    """Load every reviewer file and compute the full hybrid verdict.

    A council is only a council if every dimension reported. A partial run is an
    ERROR (exit 2), never a silent pass: renormalizing over whatever happened to
    load lets a run that omits the hard-gate `correctness` dimension report
    "satisfied" (COR-0001). Pass allow_partial=True to opt into scoring a
    genuinely partial run on the dimensions present.

    *stacks* drives the beta denominator (see STACK_TOOLS). When omitted it is
    resolved from the run's meta.json or the target repo.
    """
    if stacks is None:
        stacks = resolve_stacks(run_dir, repo)

    # See resolve_repo: the score must depend on the RUN, not on how the gate was invoked.
    repo = resolve_repo(run_dir, repo)

    reviews, missing_files, invalid = load_reviews(run_dir)

    if not reviews:
        return _error_result(
            f"no reviewer output found in {run_dir} "
            f"(missing: {', '.join(sorted(missing_files)) or 'all'})"
        )

    # An incomplete or corrupt council is not a verdict.
    if (missing_files or invalid) and not allow_partial:
        problems: List[str] = []
        if missing_files:
            problems.append(f"missing reviewer output: {', '.join(sorted(missing_files))}")
        if invalid:
            problems.append("unparseable/invalid: " + "; ".join(invalid))
        return _error_result(
            "; ".join(problems)
            + " — a partial council cannot certify a pass "
            "(pass --allow-partial to score it anyway)"
        )

    # §3: measure the target's size so the findings term can be a density.
    size_kloc = kloc(repo) if repo else 0.0

    # Adjudication drives BOTH the score and the certification when enforcement is on:
    # `claims` means the number comes from proven defects; the reviewer's own score is only used
    # when the caller opted out (reproducing an old score) or nothing was adjudicated.
    adjudication = load_proofs(run_dir)
    use_claims = bool(require_proof and adjudication is not None)
    per_dimension = [score_dimension(reviews[d], d, stacks, size_kloc,
                                     adjudication=adjudication if use_claims else None)
                     for d in WEIGHTS if d in reviews]
    score_source = "claims" if use_claims else "reviewer"
    # What the aggregate is on. `claims` runs can sit below det (the cap), so a threshold derived
    # from densities does not describe them; `deterministic` is what calibrate.py measures.
    required_scale = "claims" if use_claims else "deterministic"
    scale_payload = load_scale_calibration(required_scale)
    calibrated_for_scale = scale_payload is not None
    calibration_scale = (str((scale_payload or {}).get("scale") or required_scale)
                         if calibrated_for_scale else "missing")

    # The threshold must come from the scale the score is on. Resolving it in the CLI
    # always read the deterministic manifest, so a claims run was enforced against a
    # number derived from densities: the file existed, was reported as calibrated, and
    # was never applied.
    if threshold is None:
        resolved = threshold_from_scale(scale_payload)
        # `or` would treat a legitimate 0.0 as absent and fall back to the deterministic 80.0 —
        # the exact cross-scale leak this resolution exists to stop.
        threshold = resolved if resolved is not None else calibrated_threshold()

    # Renormalize over the dimensions present, so a partial run is not diluted toward
    # zero by the absent ones.
    present = {d: WEIGHTS[d] for d in reviews}
    aggregate = renormalized_aggregate(present, per_dimension)

    blocking = open_blocking(reviews)
    unresolved: List[Dict[str, Any]] = []
    if require_proof:
        blocking, unresolved = apply_proofs(blocking, adjudication)
    satisfied, reason = verdict_summary(aggregate, threshold, blocking)
    if unresolved:
        # An unsettled blocking claim is not a pass. It is not a failure either: `certification`
        # names the difference, and the reason has to survive being read on its own.
        note = f"{len(unresolved)} blocking claim(s) could not be settled (see proofs.json)"
        clean_before = not blocking and aggregate >= threshold
        satisfied = False
        reason = note if clean_before else f"{reason}; {note}"
    # The blind-reviewer hole: claims scoring rewards proving nothing, so a run that settles no
    # claim while the probes saw defects is unprovable, not clean.
    gap = coverage_gap(run_dir, adjudication) if use_claims else None
    if gap:
        satisfied = False
        reason = gap if (not blocking and not unresolved) else f"{reason}; {gap}"
    if use_claims:
        # Point 2, made permanent: on this scale the verdict is the blocking set. No threshold is
        # consulted and none is printed. The earlier code printed `aggregate X >= Y` while never
        # testing it, and a later edit tested it — both are the same mistake with different signs:
        # either way a number decides. The measured reason is upstream of this: six passes over one
        # identical tree moved the aggregate by 15 points, so any cutoff inside that band decides by
        # luck. "Is this better than before" is answered by `compare`, against a named baseline,
        # from evidence that is cited.
        satisfied = not blocking and not unresolved and not gap
        parts = []
        if blocking:
            parts.append(f"{len(blocking)} confirmed claim(s) of high or critical severity")
        if unresolved:
            parts.append(f"{len(unresolved)} blocking claim(s) could not be settled")
        if gap:
            parts.append("the probes saw a defect and nothing was settled")
        reason = ("; ".join(parts) if parts else
                  "no confirmed claim of high or critical severity, and nothing blocking is "
                  "unsettled")
    elif not calibrated_for_scale and not blocking and not unresolved and not gap:
        # The number is real but it is not comparable: claims-scored runs are on a different scale
        # from the threshold this repository derived. Refusing to certify is the honest answer;
        # the alternative is a verdict that looks calibrated and is not.
        satisfied = False
        reason = (f"the score is on the `{score_source}` scale and the threshold was calibrated on "
                  f"`{calibration_scale}` — compare nothing until `council calibrate` derives a "
                  f"threshold for the claims scale")

    return {
        "status": "satisfied" if satisfied else "not_satisfied",
        "certification": certification(satisfied, blocking, unresolved,
                                       # A claims verdict rests on the blocking set, which needs no
                                       # threshold. `uncalibrated` belongs to the deterministic
                                       # scale, where the number IS the verdict.
                                       calibrated=True if use_claims else calibrated_for_scale,
                                       coverage_gap=bool(gap)),
        "coverage_gap": gap,
        "score_source": score_source,
        "certification_basis": "claims" if use_claims else "threshold",
        "calibration_scale": calibration_scale,
        "calibrated_for_scale": calibrated_for_scale,
        "enforced": bool(require_proof),
        "unresolved": unresolved,
        "reason": reason,
        "aggregate": round(aggregate, 2),
        "threshold": threshold,
        "per_dimension": per_dimension,
        "blocking": blocking,
        "missing_files": sorted(missing_files),
        "invalid": invalid,
        "reviews_present": sorted(reviews),
        "stacks": list(stacks),
        "size_kloc": round(size_kloc, 4),
        "calibrated": load_calibration() is not None,
    }


# --- Improvement opportunities (drives the next-steps plan) -----------------

def improvement_opportunities(result: Dict[str, Any],
                              target: Optional[float] = None) -> List[Dict[str, Any]]:
    """Ranked, concrete ways to raise the aggregate.

    The threshold is the MINIMUM requirement; everything above it is desirable
    but not required. This separates the two so a plan can lead with what is
    actually required and then prioritise the rest by how much score it buys.

    Each entry carries `points_potential` — the WEIGHTED headroom, i.e. how much
    of the aggregate this item can actually move. Ranking by that (rather than by
    prose) is what makes the plan a priority list instead of a wish list.
    """
    per_dim = result.get("per_dimension") or []
    if not per_dim:
        return []

    weights = {d["dimension"]: WEIGHTS.get(d["dimension"], 0.0) for d in per_dim}
    total_weight = sum(weights.values()) or 1.0
    threshold = float(result.get("threshold") or target or calibrated_threshold())
    goal = float(target) if target is not None else threshold

    # The score requirement and the blocking gate are independent. Conflating them marks
    # a dimension "required" on a run whose aggregate already clears the minimum, and
    # mislabels a blocked-but-passing run as "below the minimum".
    aggregate = result.get("aggregate")
    score_met = (isinstance(aggregate, (int, float))
                 and float(aggregate) >= goal)

    out: List[Dict[str, Any]] = []

    # 1. Blocking findings. REQUIRED — no aggregate buys a pass past these.
    for finding in result.get("blocking") or []:
        loc = finding.get("location") or finding.get("path") or ""
        if isinstance(loc, dict):
            loc = f"{loc.get('path', '')}:{loc.get('line_range', loc.get('lines', ''))}"
        out.append({
            "kind": "blocking",
            "required": True,
            "priority": 0,
            "dimension": finding.get("dimension"),
            "id": finding.get("id"),
            "severity": finding.get("severity"),
            "location": loc,
            "claim": (finding.get("claim") or finding.get("consequence")
                      or finding.get("title") or ""),
            "verify": finding.get("falsifiable_check"),
            "points_potential": None,
            "action": (f"Fix [{finding.get('id')}] "
                       f"({finding.get('severity')}) — an open high/critical "
                       f"finding blocks a pass regardless of the aggregate."),
        })

    # 2. Per-dimension headroom: needed for the minimum vs desirable above it.
    for d in per_dim:
        name = d["dimension"]
        score = float(d["score"])
        w = weights[name] / total_weight
        to_goal = max(0.0, goal - score)
        to_max = max(0.0, 100.0 - score)
        if to_max <= 0.01:
            continue
        required = (not score_met) and to_goal > 0.01
        out.append({
            "kind": "dimension",
            "required": required,
            "priority": 1 if required else 3,
            "dimension": name,
            "score": round(score, 2),
            "goal": goal,
            "beta": d.get("beta"),
            "det": d.get("det"),
            "llm": d.get("llm"),
            "points_potential": round((to_goal if required else to_max) * w, 2),
            "points_to_max": round(to_max * w, 2),
            "action": (
                f"{name}: {score:.1f} -> {goal:g} to meet the minimum"
                if required else
                f"{name}: {score:.1f} — raise toward 100 for up to "
                f"+{to_max * w:.2f} aggregate (the minimum is already met)"
            ),
        })

    # 3. beta gaps. Raising beta only helps when det > llm, since
    #    score = beta*det + (1-beta)*llm.
    for d in per_dim:
        missing = d.get("tools_missing") or []
        if not missing:
            continue
        beta = float(d.get("beta") or 0.0)
        det = float(d.get("det") or 0.0)
        llm = float(d.get("llm") or 0.0)
        gain_per_beta = det - llm
        if gain_per_beta <= 0:
            continue      # adding determinism would LOWER this dimension
        w = weights[d["dimension"]] / total_weight
        out.append({
            "kind": "beta",
            "required": False,
            "priority": 2,
            "dimension": d["dimension"],
            "missing_tools": missing,
            "beta": round(beta, 4),
            "det": round(det, 2),
            "llm": round(llm, 2),
            "points_potential": round((1.0 - beta) * gain_per_beta * w, 2),
            # "not run", not "install": `tools_missing` means EXPECTED and unreported —
            # whether it is installed is `council doctor`'s question, not this module's.
            # The harness now runs every expected tool, so this means a probe could not.
            "action": (f"{d['dimension']}: {', '.join(missing)} not run "
                       f"(beta {beta:.2f} -> 1.00); the deterministic half scores "
                       f"{det:.1f} vs the reviewer's {llm:.1f}"),
        })

    # 4. Remaining non-blocking findings, worst first.
    for d in per_dim:
        blocking_sev = BLOCKING_SEVERITIES.get(d["dimension"], DEFAULT_BLOCKING)
        for finding in d.get("findings") or []:
            sev = str(finding.get("severity") or "").lower()
            # `sev in BLOCKING_SEVERITIES` tested a SEVERITY against a dict keyed by
            # DIMENSION: false for every finding, so a blocking finding appeared here AND
            # in section 1 — measured twice as SEC-0001.
            if sev in blocking_sev:
                continue      # already covered as blocking
            status = str(finding.get("status") or "open").lower()
            if status in {"fixed", "wontfix", "accepted", "closed"}:
                continue
            loc = finding.get("location") or ""
            if isinstance(loc, dict):
                loc = f"{loc.get('path', '')}:{loc.get('line_range', '')}"
            out.append({
                "kind": "finding",
                "required": False,
                "priority": 4 if sev == "medium" else 5,
                "dimension": d["dimension"],
                "id": finding.get("id"),
                "severity": sev,
                "location": loc,
                "claim": finding.get("claim") or "",
                "verify": finding.get("falsifiable_check"),
                "points_potential": None,
                "action": (f"Address [{finding.get('id')}] ({sev}) "
                           f"in {d['dimension']} — improves the reviewer's score "
                           f"and may reduce findings density"),
            })

    # Required first, then by how much aggregate each item can move.
    out.sort(key=lambda o: (o["priority"],
                            -(o.get("points_potential") or 0.0)))
    return out


# --- Continuation prompt ----------------------------------------------------

def render_continuation(result: Dict[str, Any], tail_chars: int) -> str:
    """The gate's stdout on failure IS the continuation prompt (FRAMEWORK §6)."""
    lines: List[str] = []
    lines.append("REVIEW-COUNCIL GATE FAILED — repair these, then finish.")
    lines.append(f"aggregate {result['aggregate']:.2f} / threshold {result['threshold']:g}")
    lines.append("")

    lines.append("per dimension (score = beta*det + (1-beta)*llm):")
    for dim in result["per_dimension"]:
        miss = f"  missing: {', '.join(dim['tools_missing'])}" if dim["tools_missing"] else ""
        lines.append(
            f"  {dim['dimension']:<14} llm {dim['llm']:>6}  det {dim['det']:>6}  "
            f"beta {dim['beta']:>5}  ->  {dim['score']:>6}{miss}"
        )
    lines.append("")

    if result["blocking"]:
        lines.append("OPEN BLOCKING FINDINGS (must be fixed before this can pass):")
        for finding in result["blocking"]:
            fid = finding.get("id") or "?"
            loc = finding.get("location") or finding.get("path") or ""
            if isinstance(loc, dict):
                loc = f"{loc.get('path', '')}:{loc.get('line_range', loc.get('lines', ''))}"
            claim = finding.get("claim") or finding.get("consequence") or finding.get("title") or ""
            lines.append(f"  [{fid}] {finding['dimension']} {finding.get('severity', '')} {loc}")
            if claim:
                lines.append(f"      {claim}")
            check = finding.get("falsifiable_check")
            if check:
                lines.append(f"      verify: {check}")
        lines.append("")

    if result["missing_files"]:
        lines.append(f"reviewers with no output: {', '.join(result['missing_files'])}")
    if result["invalid"]:
        lines.append("invalid reviewer output:")
        for item in result["invalid"]:
            lines.append(f"  - {item}")

    text = "\n".join(lines).rstrip() + "\n"
    if tail_chars and len(text) > tail_chars:
        text = text[:tail_chars].rstrip() + "\n[... truncated]\n"
    return text


# --- CLI --------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="score_reviews.py",
        description="Deterministic gate for the review-council (FRAMEWORK §6/§8).",
    )
    parser.add_argument("run_dir", nargs="?",
                        help="Directory holding <dimension>.json reviewer outputs")
    parser.add_argument("--latest", action="store_true",
                        help="Ignore run_dir and score the NEWEST run under "
                             "--repo (or the cwd): <repo>/.review-council/<stamp>/. "
                             "This is the form to use as a /goal quality gate, "
                             "because it needs no run directory you would have to "
                             "know.")
    parser.add_argument("--threshold", type=float, default=None,
                        help="Pass threshold (default: the value calibrated for the run's own "
                             "scale — scripts/calibration.claims.json for a claims-scored run, "
                             "else scripts/calibration.json)")
    parser.add_argument("--json", action="store_true", help="Emit the full result as JSON on stdout")
    parser.add_argument("--tail-chars", type=int, default=3000,
                        help="Cap the continuation prompt (default 3000, matches goals.py)")
    parser.add_argument("--allow-partial", action="store_true",
                        help="Score a partial run on the dimensions present instead of erroring (exit 2)")
    parser.add_argument("--repo", default=None,
                        help="Target repo for language-stack detection (drives the beta denominator). "
                             "Defaults to the run's meta.json, else the repo the run dir lives under.")
    parser.add_argument("--stacks", default=None,
                        help="Comma-separated stacks to force (e.g. 'nix,python'), overriding detection")
    parser.add_argument("--quiet", action="store_true", help="Suppress the continuation prompt")
    parser.add_argument("--allow-unproven", action="store_true",
                        help="DO NOT require a proof for a blocking finding — the pre-proof rule. "
                             "Default is enforcement: a blocking claim counts only once its proof "
                             "was refuted, and anything unsettled makes the run unprovable "
                             "(docs/ADJUDICATION.md). Use this to reproduce an old score, not to "
                             "certify a merge.")
    args = parser.parse_args(argv)
    threshold: Optional[float] = args.threshold

    if args.latest:
        # Runs at EVERY turn boundary, so it must stay cheap and never guess: no run yet
        # is a FAILED gate (the goal is not met), not an error, and it names the
        # directory it looked in.
        repo_root = Path(args.repo) if args.repo else Path.cwd()
        runs = sorted(
            (p for p in (repo_root / ".review-council").glob("*") if p.is_dir()),
            key=lambda p: p.name,
        ) if (repo_root / ".review-council").is_dir() else []
        if not runs:
            print(f"gate: no run under {repo_root / '.review-council'} yet, so the goal "
                  f"is not met.", file=sys.stderr)
            return 1
        run_dir = runs[-1]
        if not args.quiet:
            print(f"gate: scoring the newest run: {run_dir}")
    elif args.run_dir:
        run_dir = Path(args.run_dir)
    else:
        print("score_reviews: give a run directory, or --latest to score the newest "
              "one under --repo.", file=sys.stderr)
        return 2
    if not run_dir.is_dir():
        print(f"score_reviews: run directory not found: {run_dir}", file=sys.stderr)
        return 2

    forced = [s.strip() for s in args.stacks.split(",") if s.strip()] if args.stacks else None
    repo = Path(args.repo) if args.repo else None

    try:
        result = evaluate(run_dir, threshold, allow_partial=args.allow_partial,
                          require_proof=not args.allow_unproven,
                          stacks=forced, repo=repo)
    except Exception as exc:  # never crash the loop; a gate error is a failed gate
        print(f"score_reviews: evaluation error: {exc}", file=sys.stderr)
        return 2

    if result["status"] == "error":
        print(f"score_reviews: {result['reason']}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif not args.quiet and result["status"] != "satisfied":
        sys.stdout.write(render_continuation(result, args.tail_chars))

    if result["status"] == "satisfied":
        if not args.json and not args.quiet:
            if result.get("threshold") is None:
                print("satisfied: no open high/critical and nothing blocking unsettled "
                      "(no claims threshold is calibrated, so the number is not compared)")
            else:
                print(f"satisfied: aggregate {result['aggregate']} >= {result['threshold']:g}, "
                      f"no open high/critical")
        return 0
    return 1


if __name__ == "__main__":
    # Not a program: reached through `council <verb>`. See council.py.
    from council import require_dispatch

    require_dispatch("gate")
    sys.exit(main())
