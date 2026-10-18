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

# `_shared` by path, like every sibling here -- see its own docstring for why a
# plain import would not be safe.
_SHARED_SPEC = _shared_util.spec_from_file_location(
    "_shared", Path(__file__).resolve().parent / "_shared.py")
assert _SHARED_SPEC is not None and _SHARED_SPEC.loader is not None, "_shared.py"
_shared = _shared_util.module_from_spec(_SHARED_SPEC)
_SHARED_SPEC.loader.exec_module(_shared)

HERE = Path(__file__).resolve().parent

# Source suffixes counted when measuring repo size for findings DENSITY.
# research/deterministic-quality-tooling.md §3 requires density, not raw counts.
SOURCE_SUFFIXES = frozenset({
    ".py", ".nix", ".sh", ".bash", ".js", ".ts", ".go", ".rs", ".c", ".h",
})

# --- The scoring table (FRAMEWORK §6) ---------------------------------------

# Aggregate weights. Working defaults; M8 calibrates. Sum should be 1.0.
WEIGHTS: Dict[str, float] = {
    "security": 0.30,
    "correctness": 0.25,
    "readability": 0.20,
    "architecture": 0.15,
    "performance": 0.10,
}

# Expected deterministic tools, per dimension PER LANGUAGE STACK — the
# denominator of beta. beta_c = tools_ran_and_parsed_c / tools_expected_c
# (MEASURED, not asserted).
#
# Keyed by stack because a flat table makes beta unreachable on any repo that is
# not that stack: with a Nix-only table, a Python repo scores beta=0 no matter
# how many analyzers it runs, so the deterministic half of the hybrid is
# decorative. DECISIONS #3 locks "language-agnostic framework, Python
# first-class" — this table encodes that. Nix stays first-class too.
#
# Names in BUILTIN_TOOLS are satisfied by the framework's own probes.py (zero
# installs). Everything else needs the external tool; `doctor.py` reports which
# are missing and how to get them.
STACK_TOOLS: Dict[str, Dict[str, List[str]]] = {
    "security": {
        # ONE dependency scanner for every ecosystem: osv-scanner reads PyPI,
        # npm, cargo, Go, Ruby and Composer lockfiles, so it replaces pip-audit,
        # npm-audit and cargo-audit -- and unlike them it has no runtime
        # dependency of its own to get wrong. gosec stays because it is a Go
        # security LINTER, a different job from auditing dependencies.
        #
        # TWO secret scanners, and they are not redundant: `gitleaks` is the
        # maintained binary with entropy detection and a few hundred rules, while
        # `secret-grep` is this framework's own regex probe with no external
        # dependency at all. They fail in different ways -- gitleaks cannot run
        # without the toolchain, secret-grep always can -- so both are expected.
        #
        # `zizmor` is a security probe that is DELIBERATELY NOT in this table. It
        # reads `.github/workflows`, and a repository without CI has no workflows to
        # read: listing it here would make beta fall on every repo that has no
        # workflows, punishing it for a check that cannot apply. It contributes to
        # `det` through `tools_run` whenever it does run, which is the correct
        # behaviour for a conditional analyzer -- see `probe_zizmor`.
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
        # without a pinned baseline, so performance had no measured input at all and was
        # scored entirely from the reviewer's findings. These three are absolute and
        # cheap — IFD breaks eval caching, a missing store cache rebuilds every run, and
        # a missing concurrency key wastes superseded runs.
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

# Tools the framework implements itself (scripts/probes.py). These always
# "ran" — they need no installation, which is what keeps the framework runnable
# on a bare machine.
BUILTIN_TOOLS: frozenset = frozenset({
    "secret-grep", "py-compile", "bash-n", "complexity", "dep-graph", "declared-rules",
    # Pure text over the repository; they need no toolchain, so they run everywhere.
    "ci-cache", "ci-concurrency",
})

# Tools implemented as probes.py wrappers around the PINNED nix toolchain. They
# need no binary of their own — `nix` plus the toolchain is enough — so they count
# as available whenever the toolchain resolves.
#
# This is the whole set the gate can expect a HARNESS-RUN tool to come from. A name
# the gate expects but that is absent here can only be satisfied by the reviewer's
# own report, which is exactly the asymmetry that let beta measure diligence: the
# Nix tools were deterministic and the Python ones were not. Every expected tool
# now has a probe, so the deterministic half is a property of the harness.
NIX_PROBE_TOOLS: frozenset = frozenset({
    "statix", "deadnix", "nixfmt", "flake-check", "nix-eval", "nix-eval-time",
    "ruff", "mypy", "bandit", "osv-scanner", "pytest",
    # Needs `nix` (it asks Nix to evaluate with IFD disabled), unlike the two CI text
    # probes, which are BUILTIN.
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

#: Expected-tool names that are EXTERNAL BINARIES: the toolchain must ship them, or
#: beta is capped by the packaging rather than by the repository under review.
#: Every OTHER name in STACK_TOOLS/GENERIC_TOOLS is a probe implemented inside
#: scripts/probes.py -- no binary, no dependency. The two sets are disjoint and
#: together cover every name, which `tests/test_probes.py` asserts, so a name added to
#: STACK_TOOLS without a probe or a shipped tool cannot go unnoticed.
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
    "rust": ("Cargo.toml",),
    "go": ("go.mod",),
    "shell": ("Makefile",),
}

STACK_EXTENSIONS: Dict[str, Tuple[str, ...]] = {
    "nix": (".nix",),
    "python": (".py",),
    "javascript": (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"),
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
            # Relative to *root*, not the absolute path: a checkout under a directory
            # named `build` or `target` would otherwise have every file skipped.
            if any(part in _SKIP_DIRS for part in path.relative_to(root).parts):
                continue
            seen += 1
            suffix = path.suffix.lower()
            for stack, exts in STACK_EXTENSIONS.items():
                if suffix in exts:
                    counts[stack] = counts.get(stack, 0) + 1
                    break

    # Marker-detected stacks first (authoritative), then stacks that only show
    # up as a meaningful share of the tree.
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
        # Order by weight: the dominant stack first, so `expected_tools` reads naturally.
        return sorted(kept, key=lambda s: -shares.get(s, 0.0))
    # Nothing cleared the bar: keep the largest stack, and any marker-detected one that
    # at least owns some lines, rather than falling back to `generic` and losing beta.
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

# Hill curve defaults for findings density (FRAMEWORK §6 normalization).
HILL_K = 5.0
HILL_N = 1.2

# FALLBACK pass threshold — used only when scripts/calibration.json is missing or
# unreadable. The authoritative value is the calibrated one; see
# calibrated_threshold(). A fallback rather than a hard failure is deliberate: an
# uncalibrated checkout still runs.
DEFAULT_THRESHOLD = 80.0

# Severities that block satisfaction outright (FRAMEWORK §6, §5), per dimension.
#
# Security and correctness are the HARD requirements: the observed cost of getting one
# wrong is a supply-chain compromise or a build that does not work, and eight
# well-regarded repositories produced 93 of 94 blocking findings in exactly these two
# dimensions. Everything else blocks only at `critical`, so a readability or performance
# defect moves the score without vetoing a merge — while a `critical` anywhere still
# blocks, which keeps an absolute floor in every dimension.
BLOCKING_SEVERITIES: Dict[str, frozenset] = {
    "security": frozenset({"high", "critical"}),
    "correctness": frozenset({"high", "critical"}),
    "readability": frozenset({"critical"}),
    "architecture": frozenset({"critical"}),
    "performance": frozenset({"critical"}),
}
# An unrecognised dimension gets the strict floor, not the lenient one: a dimension
# nobody classified should not be able to pass on a `high`.
DEFAULT_BLOCKING: frozenset = frozenset({"critical"})

# Severity weights for the density term (§3: "severity-weighted findings per
# KLOC"). The density numerator is a WEIGHTED count, not a raw one.
#
# `info` weighs 0 because it is a note, not a defect: the rubrics use it for
# "verified, no action", "recorded so it is not re-litigated" and "assessment,
# no cost found". Counting those as defects made a thorough reviewer score WORSE
# than a silent one — the incentive pointed away from the diligence the council
# exists to reward.
#
# `low` is 1.0 deliberately. It is the scale anchor the calibration was fitted
# on, so a repo whose findings are all `low` scores exactly as it did before and
# every d_star in calibration.json stays meaningful. Reweighting the anchor
# would invalidate the whole manifest without a recalibration to match.
SEVERITY_WEIGHT: Dict[str, float] = {
    "critical": 4.0,
    "high": 3.0,
    "medium": 2.0,
    "low": 1.0,
    "info": 0.0,
}
# An unrecognised severity is treated as a real finding rather than dropped:
# silence about a defect is the worse failure, and the rubrics' enum is closed.
DEFAULT_SEVERITY_WEIGHT = 1.0


# --- Scoring math -----------------------------------------------------------

def hill_curve(x: float, k: float = HILL_K, n: float = HILL_N) -> float:
    """Findings density -> 0-100. `100 / (1 + (x/K)^n)` (FRAMEWORK §6)."""
    if x <= 0:
        return 100.0
    return 100.0 / (1.0 + (x / k) ** n)


# --- calibration (M8) -------------------------------------------------------
#
# research/deterministic-quality-tooling.md §3: "Density, not raw counts.
# Absolute counts punish large repos; use severity-weighted findings per KLOC."
# §7: calibrate d* from a known-good baseline scan and "record the calibration
# inputs and outputs in the manifest so a score is always reproducible *and* its
# parameters are auditable."
#
# Without a manifest the framework falls back to the original count-based curve,
# so an uncalibrated checkout still runs — it just says so.

CALIBRATION_PATH = HERE / "calibration.json"
_CALIBRATION: Optional[Dict[str, Any]] = None
_CALIBRATION_LOADED = False


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

# Invocations whose canonical tool name cannot be derived from the command's own
# words. The reviewer reports what it TYPED; STACK_TOOLS names the TOOL. Where
# those differ the mapping is real knowledge and has to live somewhere -- without
# it the reviewer runs the tool, beta cannot see it, and the dimension is scored
# as though nothing ran. Observed on a real run: `nix flake check --no-build
# --keep-going` yielded candidates {nix, nix-flake} and never reached
# `flake-check`, silently halving the correctness dimension's beta.
#
# `nix flake check` is the reason a generic rule cannot do this: the canonical
# name is the SUBCOMMAND PAIR, not the first two tokens, so the usual
# runner+subcommand join lands on `nix-flake` instead.
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
    # Skip leading `NAME=value` assignments: `PATH=/x/bin:$PATH ruff check` runs
    # ruff, and the assignment is not the executable.
    while tokens and re.match(r"^[a-z_][a-z0-9_]*=", tokens[0]):
        tokens.pop(0)
    if not tokens:
        return set()

    # Only the EXECUTABLE is path-stripped. Stripping the whole string before its
    # last `/` took the tail of the last ARGUMENT instead: a reviewer reporting
    # `python3 -m pytest tests/ -q` resolved to `-q`, so pytest never matched and
    # the dimension was scored as though the tool had not run.
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
    # Runner + subcommand (`cargo test` -> cargo-test).
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
            # Three producers write this field: the reviewer's JSON (`cmd`), a
            # probe result (`tool`), and older reports (`name`). Accepting all
            # three is honest -- they are the same fact under different keys --
            # and reading only one silently drops a producer's whole contribution.
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

    # §6: det[c] = geometric_mean(normalize(tool_signals_c)) -- the signals of THIS
    # category's tools. Averaging every tool into every category made the
    # readability number depend on bandit and the security number depend on mypy,
    # which is neither what the spec says nor what the `_c` subscript means. It went
    # unnoticed while beta < 1 let the reviewer's score dominate; at beta = 1 det IS
    # the score, so the leak would decide the verdict rather than just colour it.
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
        # A tool that ran contributes a normalized signal. Tools that report an
        # explicit 0-100 `signal` are trusted for the deterministic term; a
        # clean run with no signal defaults to 100 (no findings => no defect
        # signal), and findings density below is what moves it down.
        raw = tool.get("signal")
        signals.append((float(raw) if isinstance(raw, (int, float)) else 100.0, 1.0))

    det = weighted_geometric_mean(signals) if signals else 0.0

    # Findings density for the dimension, as a second deterministic term.
    # §3: severity-weighted findings per KLOC, NOT a raw count. A raw count makes
    # a 100-line file with 5 findings score identically to a 10,000-line repo
    # with 5, and makes an `info` note cost as much as a defect.
    open_findings = weighted_open_findings(review.get("findings"))
    if size_kloc > 0:
        density_score = hill_density(open_findings / size_kloc)
    else:
        density_score = hill_curve(float(open_findings))
    det = weighted_geometric_mean([(det, 0.7), (density_score, 0.3)]) if signals else density_score

    return det, beta, missing


def score_dimension(review: Dict[str, Any], dimension: str,
                    stacks: Optional[List[str]] = None,
                    size_kloc: float = 0.0) -> Dict[str, Any]:
    """score[c] = beta*det + (1-beta)*llm (FRAMEWORK §6)."""
    llm = float(review.get("score") or 0.0)
    det, beta, missing = deterministic_score(review, dimension, stacks, size_kloc)
    score = beta * det + (1.0 - beta) * llm
    return {
        "dimension": dimension,
        "llm": round(llm, 2),
        "det": round(det, 2),
        "beta": round(beta, 4),
        "score": round(score, 2),
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

    Measured against eight well-regarded repositories: 93 of 94 blocking findings were
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
        # relevant_stacks, not detect_stacks: beta should ask "did the tools for the
        # languages this repo is MADE OF run", not "did every tool for every language
        # that appears twice run". An incidental Python file used to make pytest, ruff,
        # mypy and bandit expected, which depressed beta on repos that had nothing to
        # test in Python.
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


def evaluate(run_dir: Path, threshold: float, allow_partial: bool = False,
             stacks: Optional[List[str]] = None,
             repo: Optional[Path] = None) -> Dict[str, Any]:
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

    # Resolve the repo from meta.json when not given, so the score depends on the
    # RUN and not on how the gate was invoked (see resolve_repo).
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

    per_dimension = [score_dimension(reviews[d], d, stacks, size_kloc)
                     for d in WEIGHTS if d in reviews]

    # Renormalize weights over the dimensions actually present, so a partial run
    # is scored on what it reviewed rather than silently diluted to zero.
    present = {d: WEIGHTS[d] for d in reviews}
    aggregate = renormalized_aggregate(present, per_dimension)

    blocking = open_blocking(reviews)
    satisfied, reason = verdict_summary(aggregate, threshold, blocking)

    return {
        "status": "satisfied" if satisfied else "not_satisfied",
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

    # Whether the SCORE requirement is already met decides what counts as
    # required. The minimum score is the requirement; the blocking-finding gate
    # is a separate, independent requirement. Conflating them would mark a
    # dimension below the threshold as "required" even on a run whose aggregate
    # already clears the minimum — and would mislabel such a run as "below the
    # minimum" when it is really just blocked.
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

    # 2. Per-dimension headroom, split into "needed for the minimum" and
    #    "desirable above it".
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

    # 3. beta gaps. Raising beta only helps when the deterministic half scores
    #    BETTER than the reviewer, since score = beta*det + (1-beta)*llm.
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
            # "not run", not "install": `tools_missing` means the tool was EXPECTED
            # and the run did not report it. Whether it is installed is a different
            # question that this module cannot see -- `council doctor` answers it.
            # Saying "install" sent a reader to install tools that were already
            # pinned in the toolchain and, for ruff and mypy, already run.
            #
            # The harness now runs every expected tool itself, so this branch is
            # reached only when a probe genuinely could not run -- no lockfile to
            # audit, no tests collected -- rather than when a reviewer chose not to.
            "action": (f"{d['dimension']}: {', '.join(missing)} not run "
                       f"(beta {beta:.2f} -> 1.00); the deterministic half scores "
                       f"{det:.1f} vs the reviewer's {llm:.1f}"),
        })

    # 4. Remaining non-blocking findings, worst first.
    for d in per_dim:
        for finding in d.get("findings") or []:
            sev = str(finding.get("severity") or "").lower()
            if sev in BLOCKING_SEVERITIES:
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
                        help="Pass threshold (default: the calibrated value from "
                             "scripts/calibration.json)")
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
    args = parser.parse_args(argv)
    threshold: float = args.threshold if args.threshold is not None else calibrated_threshold()

    if args.latest:
        # The /goal quality-gate form. It runs at EVERY turn boundary, so it must
        # be cheap and must never guess: no run yet is a FAILED gate (the goal is
        # not met), not an error, and it says which directory it looked in.
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
            print(f"satisfied: aggregate {result['aggregate']} >= {result['threshold']:g}, no open high/critical")
        return 0
    return 1


if __name__ == "__main__":
    # Not a program: reached through `council <verb>`. See council.py.
    from council import require_dispatch

    require_dispatch("gate")
    sys.exit(main())
