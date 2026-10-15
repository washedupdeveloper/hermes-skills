#!/usr/bin/env python3
"""The framework's own deterministic analyzers, so a review has real signal on a
machine where nothing else is installed.

Each probe prints one JSON object: {tool, ran, parsed, signal, findings, note}.
`signal` is the 0-100 score the gate feeds into the per-dimension geometric
mean. Stdlib only and cross-platform; third-party analyzers (ruff, statix, ...)
are layered on top when present, see doctor.py.

    council probes <name> [--repo DIR] [--json]
    council probes --list
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

try:
    import toolchain  # type: ignore
except ImportError as exc:  # pragma: no cover
    print(f"probes: cannot import toolchain.py from {HERE}: {exc}", file=sys.stderr)
    raise

SKIP_DIRS = frozenset({
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
    "env", ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache", "target",
    "dist", "build", ".next", ".nuxt", "result", ".review-council",
})

MAX_FILE_BYTES = 2_000_000


# --- helpers ----------------------------------------------------------------

def iter_files(root: Path, suffixes: tuple[str, ...], limit: int = 5000) -> List[Path]:
    """Every file under *root* with one of *suffixes*, skipping vendored dirs.

    The skip test matches the path RELATIVE to *root*. Testing absolute
    ``path.parts`` also matched ancestors of the root itself, so a repository
    checked out under any directory named ``build``, ``dist`` or ``target``
    scanned as EMPTY and reported a clean result. Nix's build sandbox makes
    that concrete: TMPDIR is ``/build``, so every probe saw zero files there.
    """
    out: List[Path] = []
    if not root.is_dir():
        return out
    for path in root.rglob("*"):
        if len(out) >= limit:
            break
        if not path.is_file():
            continue
        # A dotfile has NO suffix — `Path('.env').suffix` is `''` — so a suffix-only
        # test silently skipped the very file the list names, and secret-grep
        # reported "clean" on an unscanned `.env`. Match the bare name too.
        if path.suffix.lower() not in suffixes and path.name not in suffixes:
            continue
        rel_parts = path.relative_to(root).parts[:-1]
        if any(part in SKIP_DIRS for part in rel_parts):
            continue
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        out.append(path)
    return out


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def result(tool: str, ran: bool, signal: Optional[float] = None,
           findings: Optional[List[Dict[str, Any]]] = None, note: str = "",
           parsed: bool = True) -> Dict[str, Any]:
    return {
        "tool": tool, "ran": ran, "parsed": parsed,
        "signal": signal, "findings": findings or [], "note": note,
    }


_KLOC_CACHE: Dict[str, float] = {}
_SIZE_MODULE: List[Any] = []


def _kloc(root: Optional[Path]) -> float:
    """The target's size in KLOC, from the ONE definition in score_reviews.

    Loaded by PATH rather than by name: this module is also loaded standalone (the
    tests load it from scripts/probes.py, the CLI loads it as a verb), so a bare
    `import score_reviews` would depend on how the caller set sys.path. A silent
    fallback to 0.0 would revert every signal to a raw count -- the exact
    miscalibration this exists to remove -- so a failure here raises.
    """
    if root is None:
        return 0.0
    key = str(root)
    if key in _KLOC_CACHE:
        return _KLOC_CACHE[key]
    if not _SIZE_MODULE:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "score_reviews", Path(__file__).resolve().parent / "score_reviews.py")
        if spec is None or spec.loader is None:
            raise ImportError("probes.py needs score_reviews.py for the KLOC denominator")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _SIZE_MODULE.append(module)
    _KLOC_CACHE[key] = _SIZE_MODULE[0].kloc(root)
    return _KLOC_CACHE[key]


# The half-point (d*) this curve uses: the density at which a probe's signal scores
# 50. UNCALIBRATED, and named rather than a bare literal so the assumption is
# greppable. The calibration MEASURES a per-tool d* table and derives a pooled
# 1.8921 for the findings term (score_reviews.hill_density); this curve does not
# use it. Measured, the two disagree by up to 26 points over the density range, and
# 19 points on a probe reporting one finding per KLOC. See docs/CALIBRATION.md.
PROBE_HALF_POINT = 5.0


def score_from_density(count: float, root: Optional[Path] = None,
                       k: float = PROBE_HALF_POINT, n: float = 1.2) -> float:
    """Hill curve over findings DENSITY (§6). Same SHAPE as the scorer, different
    half-point — this is NOT the same curve as score_reviews.hill_density.

    The shape matches (`n=1.2`, the calibrated exponent). The half-point does not:
    this one is the uncalibrated `PROBE_HALF_POINT` above, while the findings term
    uses the pooled calibrated `d*`. It used to claim "matching
    score_reviews.hill_curve", which was false and hid the difference.

    `count` is a weighted finding count and `root` is the tree it was found in; the
    curve is applied to `count / KLOC`. It was applied to the raw count before,
    which scored a 14 KLOC repo's 16 findings as 16 per KLOC.

    With no measurable size it falls back to the raw count, the same way
    score_reviews does -- you cannot normalise by a size you have not measured.
    """
    if count <= 0:
        return 100.0
    size = _kloc(root) if root is not None else 0.0
    x = (count / size) if size > 0 else float(count)
    return 100.0 / (1.0 + (x / k) ** n)


# --- probes -----------------------------------------------------------------

# Secret patterns. Deliberately conservative: a probe that cries wolf trains the
# council to ignore it (FRAMEWORK §9, the SNR term exists for this reason).
_SECRET_PATTERNS: List[tuple[str, str]] = [
    (r"(?i)\b(?:api[_-]?key|apikey|secret|token|passwd|password)\s*[:=]\s*['\"][A-Za-z0-9_\-/+]{16,}['\"]",
     "hardcoded credential"),
    (r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----", "private key material"),
    (r"\bAKIA[0-9A-Z]{16}\b", "AWS access key id"),
    (r"\bghp_[A-Za-z0-9]{36}\b", "GitHub personal access token"),
    (r"\bsk-[A-Za-z0-9]{20,}\b", "OpenAI-style API key"),
    (r"\binf_[A-Za-z0-9]{20,}\b", "inference provider API key"),
    (r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b", "Slack token"),
]

# Paths that legitimately contain secret-shaped strings.
_SECRET_ALLOW = re.compile(
    r"(?i)(^|/)(tests?|fixtures?|examples?|docs?|samples?)/|\.(example|sample|template|md|rst|txt)$"
    r"|(^|/)\.env\.(example|sample|template)$"
)


def probe_secret_grep(root: Path) -> Dict[str, Any]:
    """Scan source files for hardcoded credentials."""
    findings: List[Dict[str, Any]] = []
    scanned = 0
    for path in iter_files(root, (".py", ".sh", ".bash", ".yaml", ".yml", ".json",
                                  ".toml", ".nix", ".js", ".ts", ".rs", ".go", ".env")):
        rel = path.relative_to(root).as_posix()
        if _SECRET_ALLOW.search(rel):
            continue
        text = read_text(path)
        if not text:
            continue
        scanned += 1
        for lineno, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith(("#", "//", "*")) and "BEGIN" not in line:
                continue
            for pattern, label in _SECRET_PATTERNS:
                if re.search(pattern, line):
                    findings.append({
                        "severity": "high", "status": "open",
                        "location": {"path": rel, "line_range": str(lineno)},
                        "claim": f"possible {label} committed in source",
                    })
                    break
    return result("secret-grep", True, score_from_density(len(findings), root), findings,
                  f"scanned {scanned} files")


def probe_py_compile(root: Path) -> Dict[str, Any]:
    """Syntax-check every Python file (stdlib compile, no imports executed)."""
    findings: List[Dict[str, Any]] = []
    files = iter_files(root, (".py",))
    for path in files:
        rel = path.relative_to(root).as_posix()
        try:
            compile(read_text(path), str(path), "exec", dont_inherit=True)
        except SyntaxError as exc:
            findings.append({
                "severity": "critical", "status": "open",
                "location": {"path": rel, "line_range": str(exc.lineno or 0)},
                "claim": f"Python syntax error: {exc.msg}",
                "falsifiable_check": f"python -m py_compile {rel}",
            })
    return result("py-compile", True, score_from_density(len(findings) * 3, root), findings,
                  f"compiled {len(files)} files")


def probe_bash_n(root: Path) -> Dict[str, Any]:
    """Syntax-check shell scripts with bash -n when bash is available."""
    import shutil
    import subprocess

    files = iter_files(root, (".sh", ".bash"))
    bash = shutil.which("bash")
    if not bash:
        return result("bash-n", False, None, [], "bash not on PATH", parsed=False)
    findings: List[Dict[str, Any]] = []
    for path in files:
        try:
            proc = subprocess.run([bash, "-n", str(path)], capture_output=True,
                                  text=True, timeout=20)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if proc.returncode != 0:
            findings.append({
                "severity": "high", "status": "open",
                "location": {"path": path.relative_to(root).as_posix(), "line_range": ""},
                "claim": (proc.stderr or "bash -n failed").strip().splitlines()[0][:200],
                "falsifiable_check": f"bash -n {path.name}",
            })
    return result("bash-n", True, score_from_density(len(findings) * 2, root), findings,
                  f"checked {len(files)} scripts")


def probe_complexity(root: Path) -> Dict[str, Any]:
    """Cyclomatic complexity per function via ast; flags the worst offenders."""
    findings: List[Dict[str, Any]] = []
    funcs = 0
    for path in iter_files(root, (".py",)):
        rel = path.relative_to(root).as_posix()
        try:
            tree = ast.parse(read_text(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            funcs += 1
            complexity = 1
            for child in ast.walk(node):
                if isinstance(child, (ast.If, ast.For, ast.While, ast.ExceptHandler,
                                      ast.With, ast.BoolOp, ast.IfExp, ast.comprehension)):
                    complexity += 1
            # 10 is the usual "refactor me" line; 20+ is a real hotspot.
            if complexity >= 15:
                findings.append({
                    "severity": "medium" if complexity >= 25 else "low",
                    "status": "open",
                    "location": {"path": rel, "line_range": str(node.lineno)},
                    "claim": f"{node.name}() has cyclomatic complexity {complexity}",
                    "falsifiable_check": f"inspect {rel}:{node.lineno}",
                })
    return result("complexity", True, score_from_density(len(findings), root), findings,
                  f"analysed {funcs} functions")


def probe_dep_graph(root: Path) -> Dict[str, Any]:
    """Build the intra-repo import graph; flag cycles and high-fan-out modules."""
    findings: List[Dict[str, Any]] = []
    modules: Dict[str, set] = {}
    for path in iter_files(root, (".py",)):
        rel = path.relative_to(root).as_posix()
        try:
            tree = ast.parse(read_text(path))
        except SyntaxError:
            continue
        deps: set = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                deps.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                deps.add(node.module.split(".")[0])
        modules[rel] = deps

    # Fan-out: a module importing many local siblings is a coupling smell.
    local_tops = {Path(m).stem for m in modules}
    for rel, deps in modules.items():
        local_deps = {d for d in deps if d in local_tops and d != Path(rel).stem}
        if len(local_deps) >= 12:
            findings.append({
                "severity": "low", "status": "open",
                "location": {"path": rel, "line_range": ""},
                "claim": f"module imports {len(local_deps)} local modules (high coupling)",
            })

    return result("dep-graph", True, score_from_density(len(findings), root), findings,
                  f"{len(modules)} modules, {sum(len(d) for d in modules.values())} edges")


def probe_declared_rules(root: Path) -> Dict[str, Any]:
    """Architecture needs declared rules to have any deterministic signal
    (research/deterministic-quality-tooling.md). Absent rules = one finding."""
    candidates = ("AGENTS.md", "CLAUDE.md", ".hermes.md", "ARCHITECTURE.md",
                  "docs/ARCHITECTURE.md", "docs/architecture.md")
    present = [c for c in candidates if (root / c).exists()]
    if present:
        return result("declared-rules", True, 100.0, [],
                      f"declared: {', '.join(present)}")
    return result("declared-rules", True, 40.0, [{
        "severity": "low", "status": "open",
        "location": {"path": ".", "line_range": ""},
        "claim": "no architecture rules declared (AGENTS.md / ARCHITECTURE.md)",
    }], "no architecture rules found")


# --- Nix probes -------------------------------------------------------------
# These run in the pinned toolchain from flake.lock; see research/nix-tooling.md.

def _bridge(root: Path, args: List[str], timeout: int = 600,
            env_extra: Optional[Dict[str, str]] = None) -> Tuple[int, str]:
    """Run a command in the pinned toolchain. Returns (rc, combined output).

    (127, reason) when the toolchain is unavailable, so the probe reports
    ran=False rather than fabricating a result.
    """
    return toolchain.run(args, repo=root, timeout=timeout, env_extra=env_extra)


def _nix_files(root: Path, limit: int = 400) -> List[str]:
    return [p.relative_to(root).as_posix() for p in iter_files(root, (".nix",))][:limit]


def _json_objects(text: str) -> List[Dict[str, Any]]:
    """Parse a stream of CONCATENATED JSON objects (pretty-printed or JSONL).

    statix and deadnix both emit a sequence of JSON objects rather than one JSON
    array — but their formatting differs: deadnix is one object per line (JSONL),
    while statix pretty-prints each object across many lines. A line-based parser
    therefore works for one and silently returns zero for the other, which reads
    as a clean bill of health on a file that does not even parse. raw_decode over
    the whole text handles both shapes.
    """
    import json as _json
    decoder = _json.JSONDecoder()
    out: List[Dict[str, Any]] = []
    idx, length = 0, len(text)
    while idx < length:
        while idx < length and text[idx] in " \t\r\n,":
            idx += 1
        if idx >= length:
            break
        try:
            obj, end = decoder.raw_decode(text, idx)
        except ValueError:
            # Not valid JSON here — likely a banner/warning line. Skip to the
            # next object start and carry on, rather than abandoning the rest of
            # the stream (a single warning line must not hide every finding).
            nxt = text.find("{", idx + 1)
            if nxt == -1:
                break
            idx = nxt
            continue
        if isinstance(obj, dict):
            out.append(obj)
        elif isinstance(obj, list):
            # ruff emits one JSON ARRAY; statix and deadnix emit concatenated
            # objects. Accepting both keeps ONE parser for every tool.
            out.extend(item for item in obj if isinstance(item, dict))
        idx = end
    return out


def probe_statix(root: Path) -> Dict[str, Any]:
    """`statix check . -o json` — Nix lints (research/nix-tooling.md §1).

    Output is JSONL: {"file": ..., "report": [{"severity", "diagnostics": [
    {"at": {"from": {"line"}}, "message"}]}]}."""
    files = _nix_files(root)
    if not files:
        return result("statix", False, None, [], "no .nix files in the tree", parsed=False)
    rc, out = _bridge(root, ["statix", "check", ".", "-o", "json"])
    if rc == 127:
        return result("statix", False, None, [], out[:200], parsed=False)

    findings: List[Dict[str, Any]] = []
    for obj in _json_objects(out):
        path = str(obj.get("file", "")).lstrip("./")
        for entry in obj.get("report") or []:
            severity = str(entry.get("severity", "")).lower()
            note = str(entry.get("note", ""))
            diagnostics = entry.get("diagnostics") or []
            if not diagnostics:
                findings.append({
                    "severity": "medium" if severity == "error" else "low",
                    "status": "open",
                    "location": {"path": path, "line_range": ""},
                    "claim": f"statix {note}".strip()[:200],
                })
            for diag in diagnostics:
                line = ((diag.get("at") or {}).get("from") or {}).get("line", "")
                findings.append({
                    "severity": "medium" if severity == "error" else "low",
                    "status": "open",
                    "location": {"path": path, "line_range": str(line)},
                    "claim": f"statix {note}: {diag.get('message', '')}".strip()[:200],
                    "falsifiable_check": f"statix check {path} -o json",
                })
    return result("statix", True, score_from_density(len(findings), root), findings,
                  f"{len(findings)} lints over {len(files)} files")


def probe_deadnix(root: Path) -> Dict[str, Any]:
    """`deadnix --output-format json .` — dead Nix code (§1).

    Output is JSONL: {"file": ..., "results": [{"line", "column", "message"}]}."""
    files = _nix_files(root)
    if not files:
        return result("deadnix", False, None, [], "no .nix files in the tree", parsed=False)
    rc, out = _bridge(root, ["deadnix", "--output-format", "json", "."])
    if rc == 127:
        return result("deadnix", False, None, [], out[:200], parsed=False)

    findings: List[Dict[str, Any]] = []
    for obj in _json_objects(out):
        path = str(obj.get("file", "")).lstrip("./")
        for r in obj.get("results") or []:
            findings.append({
                "severity": "low", "status": "open",
                "location": {"path": path, "line_range": str(r.get("line", ""))},
                "claim": f"deadnix: {r.get('message', 'unused binding')}"[:200],
                "falsifiable_check": f"deadnix {path}",
            })
    return result("deadnix", True, score_from_density(len(findings), root), findings,
                  f"{len(findings)} dead bindings over {len(files)} files")


def probe_nixfmt(root: Path) -> Dict[str, Any]:
    """`nixfmt --check <files>` — RFC 166 formatting. A BINARY gate, not a
    density term (§1: "Formatting is a separate binary gate")."""
    files = _nix_files(root)
    if not files:
        return result("nixfmt", False, None, [], "no .nix files in the tree", parsed=False)
    rc, out = _bridge(root, ["nixfmt", "--check"] + files)
    if rc == 127:
        return result("nixfmt", False, None, [], out[:200], parsed=False)
    if rc == 0:
        return result("nixfmt", True, 100.0, [], f"{len(files)} files formatted")
    unformatted = [line.strip() for line in out.splitlines() if line.strip().endswith(".nix")]
    findings = [{
        "severity": "low", "status": "open",
        "location": {"path": f, "line_range": ""},
        "claim": "not formatted per RFC 166 (nixfmt --check fails)",
        "falsifiable_check": f"nixfmt --check {f}",
    } for f in (unformatted or files[:10])]
    return result("nixfmt", True, 0.0, findings, f"{len(findings)} file(s) need formatting")


def probe_flake_check(root: Path) -> Dict[str, Any]:
    """`nix flake check --no-build --keep-going` — the hard correctness gate (§2).

    Binary: exit 0 passes, anything else fails. `--keep-going` collects every
    error rather than stopping at the first."""
    if not (root / "flake.nix").exists():
        return result("flake-check", False, None, [],
                      "no flake.nix — nix flake check does not apply", parsed=False)
    rc, out = _bridge(root, ["nix", "flake", "check", "--no-build", "--keep-going"],
                      timeout=900)
    if rc == 127:
        return result("flake-check", False, None, [], out[:200], parsed=False)
    if rc == 0:
        return result("flake-check", True, 100.0, [], "flake check passed")
    errors = [line.strip() for line in out.splitlines()
              if "error:" in line.lower()][:20]
    findings = [{
        "severity": "critical", "status": "open",
        "location": {"path": "flake.nix", "line_range": ""},
        "claim": msg[:200],
        "falsifiable_check": "nix flake check --no-build --keep-going",
    } for msg in (errors or ["nix flake check failed"])]
    return result("flake-check", True, 0.0, findings, "flake check FAILED")


def probe_nix_eval(root: Path) -> Dict[str, Any]:
    """`nix-instantiate --parse` per file — syntax errors, the pure parser (§2).

    Cheaper and more granular than a full eval: it reports per-file syntax errors
    without touching the store."""
    files = _nix_files(root)
    if not files:
        return result("nix-eval", False, None, [], "no .nix files in the tree", parsed=False)
    findings: List[Dict[str, Any]] = []
    checked = 0
    for rel in files[:60]:
        rc, out = _bridge(root, ["nix-instantiate", "--parse", rel], timeout=120)
        if rc == 127:
            return result("nix-eval", False, None, [], out[:200], parsed=False)
        checked += 1
        if rc != 0:
            findings.append({
                "severity": "critical", "status": "open",
                "location": {"path": rel, "line_range": ""},
                "claim": (out.strip().splitlines() or ["parse failed"])[-1][:200],
                "falsifiable_check": f"nix-instantiate --parse {rel}",
            })
    return result("nix-eval", True, score_from_density(len(findings) * 3, root), findings,
                  f"parsed {checked} files")


# Where a pinned eval baseline may live. The first is the canonical, committed
# location (a baseline is a pinned reference like flake.lock — it must be
# version-controlled to mean anything across machines). The second is accepted
# for compatibility with earlier runs.
BASELINE_RELPATHS: Tuple[str, ...] = (
    "scripts/eval-baseline.json",
    ".review-council/eval-baseline.json",
)


def load_eval_baseline(root: Path) -> Tuple[Optional[float], Optional[Path]]:
    """Return (seconds, path) for the pinned eval baseline, or (None, None)."""
    for rel in BASELINE_RELPATHS:
        path = root / rel
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            seconds = float(data.get("seconds"))
        except (OSError, ValueError, TypeError, AttributeError):
            continue
        if seconds > 0:
            return seconds, path
    return None, None


def probe_nix_eval_time(root: Path) -> Dict[str, Any]:
    """`nix eval` wall-clock, as a REGRESSION RATIO against a pinned baseline.

    research/nix-tooling.md's design principle is explicit that wall-clock timing
    is one of only two non-reproducible inputs, and must therefore be handled as
    "regression ratios against a pinned baseline rather than as absolute values".
    So: with no baseline this is informational (signal None — it still counts as
    ran for beta, but contributes no det score); with a baseline it scores the
    ratio.

    Pin one with `python probes.py nix-eval-time --repo . --pin-baseline`.
    """
    import time as _time
    if not (root / "flake.nix").exists():
        return result("nix-eval-time", False, None, [],
                      "no flake.nix — nothing to evaluate", parsed=False)

    started = _time.monotonic()
    rc, out = _bridge(root, ["nix", "eval", "--raw",
                             ".#packages.x86_64-linux.toolchain.name"], timeout=600)
    elapsed = _time.monotonic() - started
    if rc == 127:
        return result("nix-eval-time", False, None, [], out[:200], parsed=False)

    baseline, baseline_path = load_eval_baseline(root)

    if baseline is None:
        return result("nix-eval-time", True, None, [],
                      f"eval took {elapsed:.1f}s — no baseline pinned, so recorded but not scored "
                      f"(pin with --pin-baseline)")

    ratio = elapsed / baseline if baseline > 0 else 1.0
    # 1.0x = 100, 2.0x = 50, 3.0x+ = 0. Linear in the ratio, floored at 0.
    signal = max(0.0, min(100.0, 100.0 * (2.0 - ratio)))
    findings: List[Dict[str, Any]] = []
    if ratio >= 1.5:
        findings.append({
            "severity": "medium" if ratio >= 2.0 else "low", "status": "open",
            "location": {"path": "flake.nix", "line_range": ""},
            "claim": (f"nix eval regression: {elapsed:.1f}s vs baseline {baseline:.1f}s "
                      f"({ratio:.2f}x)"),
            "falsifiable_check": "time nix eval --raw .#packages.x86_64-linux.toolchain.name",
        })
    return result("nix-eval-time", True, signal, findings,
                  f"eval {elapsed:.1f}s vs baseline {baseline:.1f}s ({ratio:.2f}x)")


def pin_eval_baseline(root: Path, samples: int = 3) -> Dict[str, Any]:
    """Measure the eval `samples` times and write the MEDIAN as the pinned baseline.

    The median, not the mean or a single run: one cold eval can be 3x a warm one,
    and a baseline set from an outlier would either never fire or fire constantly.
    """
    import time as _time
    times: List[float] = []
    for _ in range(max(1, samples)):
        started = _time.monotonic()
        rc, _out = _bridge(root, ["nix", "eval", "--raw",
                                  ".#packages.x86_64-linux.toolchain.name"], timeout=600)
        if rc == 127:
            return {"ok": False, "reason": "toolchain unavailable"}
        times.append(_time.monotonic() - started)
    times.sort()
    median = times[len(times) // 2]

    path = root / BASELINE_RELPATHS[0]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "seconds": round(median, 3),
        "samples": [round(t, 3) for t in times],
        "measured": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "note": ("Pinned reference for the nix-eval-time probe. The probe scores "
                 "the RATIO against this, never the absolute value "
                 "(research/nix-tooling.md §3). Re-pin deliberately when the "
                 "machine or the flake's eval cost legitimately changes."),
    }, indent=2) + "\n", encoding="utf-8", newline="\n")
    return {"ok": True, "path": str(path), "seconds": round(median, 3),
            "samples": [round(t, 3) for t in times]}


# --- Python analyzers, through the pinned toolchain --------------------------
#
# These run exactly the way the Nix ones do: through `_bridge`, which resolves the
# PINNED toolchain. They exist because the gate EXPECTED them and nothing ran them
# -- so beta measured the reviewer's diligence instead of the harness's coverage,
# and a reviewer who did not invoke ruff cost the readability dimension 40% of its
# determinism while ruff sat pinned on PATH the whole time.
#
# Running them here makes the deterministic half a property of the HARNESS. The
# reviewer's own report stops being the measurement and becomes supporting
# evidence, which is also why the fragile parsing of free-text command strings
# stops mattering: a probe's tool name is exact.
#
# Every tool that caches by default is given a cache location OUTSIDE the tree it
# is inspecting. A review must not leave files in the repository it reviews.

def _py_files(root: Path, limit: int = 5000) -> List[str]:
    return [p.relative_to(root).as_posix() for p in iter_files(root, (".py",))][:limit]


def _scratch_env(tmp: str) -> Dict[str, str]:
    """Redirect every cache these tools write by default away from the target tree."""
    return {
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPYCACHEPREFIX": tmp,
        "MYPY_CACHE_DIR": tmp,
        "RUFF_CACHE_DIR": tmp,
        "TMPDIR": tmp,
    }


def _severity_from_bandit(value: Any) -> str:
    return {"HIGH": "high", "MEDIUM": "medium", "LOW": "low"}.get(
        str(value or "").upper(), "low")


def _severity_from_cvss(score: Any) -> str:
    """CVSS bands. An unparseable score is `medium`, never `low`: unknown is not
    the same as minor, and defaulting down would understate a real advisory."""
    try:
        value = float(score)
    except (TypeError, ValueError):
        return "medium"
    if value >= 9.0:
        return "critical"
    if value >= 7.0:
        return "high"
    if value >= 4.0:
        return "medium"
    return "low"


def probe_ruff(root: Path) -> Dict[str, Any]:
    """`ruff check --output-format json` — Python lints (readability)."""
    files = _py_files(root)
    if not files:
        return result("ruff", False, None, [], "no .py files in the tree", parsed=False)
    with tempfile.TemporaryDirectory(prefix="rc-ruff-") as tmp:
        rc, out = _bridge(root, ["ruff", "check", "--output-format", "json", "."],
                          env_extra=_scratch_env(tmp))
    if rc == 127:
        return result("ruff", False, None, [], out[:200], parsed=False)
    if rc not in (0, 1):
        return result("ruff", False, None, [], f"ruff exited {rc}: {out[:160]}", parsed=False)

    findings: List[Dict[str, Any]] = []
    for item in _json_objects(out):
        code = str(item.get("code") or "")
        row = (item.get("location") or {}).get("row", "")
        findings.append({
            # `F` is pyflakes -- an undefined name, an unused import that hides a
            # missing call. `E` is pycodestyle, which is style.
            "severity": "medium" if code.startswith("F") else "low",
            "status": "open",
            "location": {"path": str(item.get("filename") or "").lstrip("./"),
                         "line_range": str(row)},
            "claim": f"ruff {code}: {str(item.get('message', '')).strip()}".strip()[:200],
            "falsifiable_check": f"ruff check {item.get('filename')}",
        })
    return result("ruff", True, score_from_density(len(findings), root), findings,
                  f"{len(findings)} findings over {len(files)} files")


def probe_mypy(root: Path) -> Dict[str, Any]:
    """`mypy --output json` — static types (readability)."""
    files = _py_files(root)
    if not files:
        return result("mypy", False, None, [], "no .py files in the tree", parsed=False)
    # `--python-executable` points mypy at the PINNED interpreter, so it resolves
    # imports against the toolchain's site-packages instead of the host's. Without
    # it every third-party import is reported as a missing stub -- a false positive
    # that says more about mypy's search path than about the code.
    toolchain_python = toolchain.which("python3") or "python3"
    with tempfile.TemporaryDirectory(prefix="rc-mypy-") as tmp:
        rc, out = _bridge(root, ["mypy", "--output", "json",
                                 "--python-executable", toolchain_python, "."],
                          env_extra=_scratch_env(tmp), timeout=900)
    if rc == 127:
        return result("mypy", False, None, [], out[:200], parsed=False)
    # mypy exits 1 when it FOUND errors, which is a successful run with findings.
    # Only 2 is fatal, so treating non-zero as failure would report a clean repo.
    if rc not in (0, 1):
        return result("mypy", False, None, [], f"mypy exited {rc}: {out[:160]}", parsed=False)

    findings: List[Dict[str, Any]] = []
    for obj in _json_objects(out):
        severity = str(obj.get("severity") or "error").lower()
        findings.append({
            "severity": "low" if severity == "note" else "medium",
            "status": "open",
            "location": {"path": str(obj.get("file") or "").lstrip("./"),
                         "line_range": str(obj.get("line", ""))},
            "claim": f"mypy: {str(obj.get('message', '')).strip()}"[:200],
            "falsifiable_check": f"mypy {obj.get('file')}",
        })
    return result("mypy", True, score_from_density(len(findings), root), findings,
                  f"{len(findings)} type errors over {len(files)} files")


def probe_bandit(root: Path) -> Dict[str, Any]:
    """`bandit -r -ll -f json` — Python security lints (security).

    `-ll` reports MEDIUM and above. Measured on this repository: the default
    reports 775 findings of which 738 are LOW, and the LOW band is dominated by
    B101 (assert_used, 680) -- present by design in every test suite -- plus
    B603/B404/B607 (subprocess, 75), which flag every subprocess call in a tool
    whose job is running analyzers. Emitting 775 near-identical LOWs would swamp
    the signal that the MEDIUM band carries: 16 real findings.
    """
    files = _py_files(root)
    if not files:
        return result("bandit", False, None, [], "no .py files in the tree", parsed=False)
    with tempfile.TemporaryDirectory(prefix="rc-bandit-") as tmp:
        rc, out = _bridge(root, ["bandit", "-r", ".", "-f", "json", "-q", "-ll"],
                          env_extra=_scratch_env(tmp))
    if rc == 127:
        return result("bandit", False, None, [], out[:200], parsed=False)
    docs = _json_objects(out)
    if not docs:
        return result("bandit", False, None, [], f"bandit exited {rc}: {out[:160]}",
                      parsed=False)

    findings: List[Dict[str, Any]] = []
    for item in docs[0].get("results") or []:
        findings.append({
            "severity": _severity_from_bandit(item.get("issue_severity")),
            "status": "open",
            "location": {"path": str(item.get("filename") or "").lstrip("./"),
                         "line_range": str(item.get("line_number", ""))},
            "claim": (f"bandit {item.get('test_id', '')}: "
                      f"{str(item.get('issue_text', '')).strip()}")[:200],
            "falsifiable_check": f"bandit -r {item.get('filename')}",
        })
    return result("bandit", True, score_from_density(len(findings), root), findings,
                  f"{len(findings)} issues over {len(files)} files")


# Lockfiles osv-scanner understands. A MANIFEST it cannot parse is not an audit --
# pyproject.toml alone declares nothing it can read -- so the probe reports
# ran=False with that reason rather than a clean bill of health.
_OSV_LOCKFILES = frozenset({
    "requirements.txt", "poetry.lock", "uv.lock", "Pipfile.lock",
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "Cargo.lock", "go.sum", "Gemfile.lock", "composer.lock",
})


def _lockfiles(root: Path, limit: int = 20) -> List[Path]:
    out: List[Path] = []
    for path in root.rglob("*"):
        if len(out) >= limit:
            break
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        name = path.name
        if name in _OSV_LOCKFILES or (name.startswith("requirements") and name.endswith(".txt")):
            out.append(path)
    return out


def _declares_python_deps(root: Path) -> bool:
    """True when the repo declares Python dependencies without a readable lockfile.

    `pyproject.toml` is a MANIFEST, not a lockfile: osv-scanner cannot read it, so
    dependencies declared only there are genuinely unaudited. Saying so is
    actionable ("generate a lockfile"); reporting a clean result would not be.
    """
    for name in ("pyproject.toml", "setup.py", "setup.cfg"):
        path = root / name
        if not path.is_file():
            continue
        text = read_text(path)
        if re.search(r"(?m)^\s*(dependencies|install_requires|requires)\s*[=:]", text):
            return True
    return False


def probe_osv_scanner(root: Path) -> Dict[str, Any]:
    """`osv-scanner scan --format json -r .` — dependency CVEs (security).

    Replaces `pip-audit`, which cannot run in this toolchain at all: its nixpkgs
    wrapper execs `sys.executable -m pip --version`, and the interpreter it runs
    under ships no pip, so the dependency scanner sat on PATH unable to execute.
    `osv-scanner` is one static binary with no runtime dependency of its own, and
    it reads the lockfiles of every ecosystem this framework covers.
    """
    locks = _lockfiles(root)
    if not locks:
        # "Nothing to audit" and "cannot audit" are different facts, and only one
        # of them is clean. A repo with no dependencies has no dependency risk;
        # a repo that DECLARES dependencies in a manifest osv-scanner cannot read
        # has unaudited risk, and the note says what to do about it.
        if _declares_python_deps(root):
            return result("osv-scanner", False, None, [],
                          "dependencies are declared but no lockfile osv-scanner can "
                          "read exists (generate requirements.txt, uv.lock or "
                          "poetry.lock to make dependency risk auditable)",
                          parsed=False)
        return result("osv-scanner", True, 100.0, [],
                      "no dependencies declared, so there is nothing to audit")
    with tempfile.TemporaryDirectory(prefix="rc-osv-") as tmp:
        rc, out = _bridge(root, ["osv-scanner", "scan", "--format", "json", "-r", "."],
                          env_extra=_scratch_env(tmp), timeout=900)
    if rc == 127:
        return result("osv-scanner", False, None, [], out[:200], parsed=False)
    docs = _json_objects(out)
    if not docs:
        return result("osv-scanner", False, None, [],
                      f"osv-scanner exited {rc}: {out[:160]}", parsed=False)

    findings: List[Dict[str, Any]] = []
    packages = 0
    for entry in docs[0].get("results") or []:
        lock = str((entry.get("source") or {}).get("path") or "").lstrip("./")
        for pkg in entry.get("packages") or []:
            packages += 1
            name = str((pkg.get("package") or {}).get("name") or "?")
            version = str((pkg.get("package") or {}).get("version") or "")
            for group in pkg.get("groups") or []:
                ids = group.get("aliases") or group.get("ids") or []
                findings.append({
                    "severity": _severity_from_cvss(group.get("max_severity")),
                    "status": "open",
                    "location": {"path": lock, "line_range": ""},
                    "claim": f"{name} {version}: {', '.join(ids)}"[:200],
                    "falsifiable_check": f"osv-scanner scan --lockfile {lock}",
                })
    return result("osv-scanner", True, score_from_density(len(findings), root), findings,
                  f"{len(findings)} advisories over {packages} packages in "
                  f"{len(locks)} lockfile(s)")


def probe_pytest(root: Path) -> Dict[str, Any]:
    """`python3 -B -m pytest -q -p no:cacheprovider` — the repo's suite (correctness).

    This EXECUTES the target repository's tests. That is inherent to scoring
    correctness from a real test run, and the reviewer was already asked to do it;
    running it here makes it the harness's measurement rather than the reviewer's
    claim. `-B` and `no:cacheprovider` keep it from writing bytecode or a cache
    into the tree it is reviewing.
    """
    files = _py_files(root)
    if not files:
        return result("pytest", False, None, [], "no .py files in the tree", parsed=False)
    with tempfile.TemporaryDirectory(prefix="rc-pytest-") as tmp:
        rc, out = _bridge(root, ["python3", "-B", "-m", "pytest", "-q",
                                 "-p", "no:cacheprovider"],
                          env_extra=_scratch_env(tmp), timeout=1800)
    if rc == 127:
        return result("pytest", False, None, [], out[:200], parsed=False)
    if rc == 5:
        # No tests collected: not a pass and not a failure. There was nothing to
        # run, so the tool did not exercise the dimension.
        return result("pytest", False, None, [], "no tests collected", parsed=False)
    if rc not in (0, 1, 2, 3, 4):
        return result("pytest", False, None, [], f"pytest exited {rc}: {out[-160:]}",
                      parsed=False)

    findings: List[Dict[str, Any]] = []
    for line in out.splitlines():
        text = line.strip()
        if not text.startswith(("FAILED ", "ERROR ")):
            continue
        head = text.split(" - ", 1)[0]
        target = head.split(" ", 1)[1] if " " in head else ""
        findings.append({
            "severity": "medium", "status": "open",
            "location": {"path": target.split("::")[0], "line_range": ""},
            "claim": text[:200],
            "falsifiable_check": f"python3 -m pytest {target}",
        })
    summary = next((line.strip() for line in reversed(out.splitlines())
                    if "passed" in line or "failed" in line or "error" in line),
                   f"pytest exited {rc}")
    if not findings and rc != 0:
        # A non-zero status with no parseable failure line is still a failure; say
        # so rather than reporting the run as clean because the text was unusual.
        findings.append({
            "severity": "medium", "status": "open",
            "location": {"path": "", "line_range": ""},
            "claim": f"pytest exited {rc}: {summary}"[:200],
            "falsifiable_check": "python3 -m pytest -q",
        })
    return result("pytest", True, score_from_density(len(findings), root), findings, summary[:120])


PROBES: Dict[str, Callable[[Path], Dict[str, Any]]] = {
    "secret-grep": probe_secret_grep,
    "py-compile": probe_py_compile,
    "bash-n": probe_bash_n,
    "complexity": probe_complexity,
    "dep-graph": probe_dep_graph,
    "declared-rules": probe_declared_rules,
    "statix": probe_statix,
    "deadnix": probe_deadnix,
    "nixfmt": probe_nixfmt,
    "flake-check": probe_flake_check,
    "nix-eval": probe_nix_eval,
    "nix-eval-time": probe_nix_eval_time,
    "ruff": probe_ruff,
    "mypy": probe_mypy,
    "bandit": probe_bandit,
    "osv-scanner": probe_osv_scanner,
    "pytest": probe_pytest,
}


def run_probe(name: str, root: Path) -> Dict[str, Any]:
    fn = PROBES.get(name)
    if fn is None:
        return result(name, False, None, [], f"unknown probe {name!r}", parsed=False)
    try:
        return fn(root)
    except Exception as exc:  # a broken probe must not break the run
        return result(name, False, None, [], f"{type(exc).__name__}: {exc}", parsed=False)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="probes.py",
                                     description="Built-in deterministic checks for the review-council.")
    parser.add_argument("name", nargs="?", help="Probe to run")
    parser.add_argument("--repo", default=".", help="Repository root (default: cwd)")
    parser.add_argument("--list", action="store_true", help="List available probes")
    parser.add_argument("--all", action="store_true", help="Run every probe")
    parser.add_argument("--pin-baseline", action="store_true",
                        help="Measure the eval time and pin it as the nix-eval-time baseline")
    parser.add_argument("--samples", type=int, default=3,
                        help="Samples to take when pinning a baseline (median is used)")
    args = parser.parse_args(argv)

    if args.list or (not args.name and not args.all and not args.pin_baseline):
        print(json.dumps({"probes": sorted(PROBES)}, indent=2))
        return 0

    root = Path(args.repo).expanduser().resolve()
    if not root.is_dir():
        print(f"probes: not a directory: {root}", file=sys.stderr)
        return 2

    if args.pin_baseline:
        outcome = pin_eval_baseline(root, samples=args.samples)
        print(json.dumps(outcome, indent=2))
        return 0 if outcome.get("ok") else 1

    names = sorted(PROBES) if args.all else [args.name]
    out = [run_probe(n, root) for n in names]
    print(json.dumps(out if args.all else out[0], indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    # Not a program: reached through `council <verb>`. See council.py.
    from council import require_dispatch

    require_dispatch("probes")
    sys.exit(main())
