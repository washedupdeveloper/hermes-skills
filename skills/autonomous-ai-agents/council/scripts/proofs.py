"""Proofs: the closed vocabulary a claim must speak to be believed.

A finding is prose. A *proof* is a check with three possible outcomes — `supported`, `refuted`,
`unrunnable` — and the orchestrator, not the reviewer, decides which one holds. This module is the
only place a proof kind is executed, and `protocol/proofs.json` is the only place one is declared:
a kind that exists in one and not the other is a test failure, not a runtime surprise.

Three rules make this evidence rather than theatre:

* **The vocabulary is closed.** An unknown kind, an unknown parameter or a wrong type is
  `unrunnable`, with the reason. Nothing is inferred, nothing is defaulted into existence.
* **`unrunnable` is not `refuted`.** No browser, no server, no toolchain means the claim stayed
  unevaluated. Folding that into "false" would let a missing tool certify code.
* **A blocking claim needs a control.** `adjudicate()` runs the claim's control and requires it to
  be *refuted*: a check that has never been observed to fail is a guess. Without one the claim is
  `uncontrolled` — real enough to report, not enough to block. This mirrors the rule the gates
  already live by, at the one place where a claim can cost someone a merge.

What this is NOT: a sandbox. `command` runs with the invoking user's privileges, in the repo, with
the same trust the deterministic probes already have — it restricts *which* executables may run (an
allowlist plus repo-local scripts), not what a permitted one may do. Say that plainly rather than
imply otherwise; the honest boundary is the reviewer's own shell access, which it already has.

CLI (through the dispatcher — nothing under scripts/ runs by hand):
    council proofs --list
    council proofs --self-test [--json]
    council proofs --file claim.json --root . [--json]
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CONTRACT = ROOT / "protocol" / "proofs.json"

sys.path.insert(0, str(HERE))

STATUSES = ("supported", "refuted", "unrunnable")
# What a verified proof earns. `proven` is the only admission that may lower a score or block a
# merge; the other two are recorded so the verdict can say "I could not settle this".
ADMISSIONS = ("proven", "uncontrolled", "control_did_not_fail", "refuted", "unrunnable")

# Executables a `command` proof may name, by basename. Absolute paths and repo-local scripts are
# also allowed (below), but an unlisted binary is refused: the point is that a proof cannot quietly
# become "run something arbitrary and report success".
ALLOWED_EXECUTABLES = frozenset({
    "git", "rg", "grep", "find", "sh", "bash", "make", "just",
    "nix", "nix-build", "nix-shell", "nixfmt", "statix", "deadnix", "nil", "treefmt",
    "pytest", "bandit", "ruff", "mypy", "pip-audit", "uv", "poetry", "tox",
    "node", "npm", "pnpm", "yarn", "tsc", "jest", "vitest",
    "cargo", "go", "lua", "luacheck",
})
SKIP_DIRS = frozenset({".git", ".hg", ".svn", "node_modules", ".venv", "venv", "__pycache__",
                       ".mypy_cache", ".pytest_cache", ".ruff_cache", "result"})
MAX_FILE_BYTES = 2_000_000
LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost"})


class ProofError(ValueError):
    """A proof that cannot be evaluated as written. Never a silent `refuted`."""


@dataclass(frozen=True)
class Context:
    """Where a proof runs. Frozen: an executor cannot move the ground it stands on."""
    root: Path
    artefact_dir: Path
    diff_base: Optional[str] = None
    timeout: int = 120
    drivers: Dict[str, str] = field(default_factory=dict)
    #: The clean revision the change is measured against. When it is present, a claim that arrives
    #: without a control gets one synthesised from it: the same check, run where the defect is not.
    base_root: Optional[Path] = None


# --- the contract ---------------------------------------------------------------


_contract: Optional[Dict[str, Any]] = None


def contract() -> Dict[str, Any]:
    global _contract
    if _contract is None:
        try:
            _contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:  # pragma: no cover - packaging error
            raise ProofError(f"the proof contract is missing at {CONTRACT}") from exc
        except json.JSONDecodeError as exc:  # pragma: no cover - packaging error
            raise ProofError(f"the proof contract at {CONTRACT} is not JSON: {exc}") from exc
    assert _contract is not None
    return _contract


def kinds() -> Dict[str, Dict[str, Any]]:
    return contract()["kinds"]


def _check_type(kind: str, name: str, value: Any, spec: Dict[str, Any]) -> Any:
    want = spec["type"]
    ok = {
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "array": isinstance(value, list) and all(isinstance(v, str) for v in value),
        "object": isinstance(value, dict),
        "any": True,
    }.get(want)
    if want not in {"string", "integer", "boolean", "array", "object", "any"}:
        raise ProofError(f"{kind}: parameter `{name}` declares unknown type `{want}` in the contract")
    if not ok:
        raise ProofError(f"{kind}: parameter `{name}` must be {want}, got {type(value).__name__}")
    if "enum" in spec and value not in spec["enum"]:
        raise ProofError(f"{kind}: parameter `{name}` must be one of {spec['enum']}, got {value!r}")
    return value


def normalise(kind: str, params: Dict[str, Any], where: str = "proof") -> Dict[str, Any]:
    """Validate `params` against the contract and apply defaults. Unknown keys are refused."""
    if kind not in kinds():
        raise ProofError(f"{where}: unknown proof kind `{kind}` — the vocabulary is closed "
                         f"({', '.join(sorted(kinds()))})")
    declared = kinds()[kind]["params"]
    unknown = sorted(set(params) - set(declared))
    if unknown:
        raise ProofError(f"{where}: `{kind}` has no parameter(s) {', '.join(unknown)}")
    out: Dict[str, Any] = {}
    for name, spec in declared.items():
        if name in params:
            out[name] = _check_type(kind, name, params[name], spec)
        elif spec.get("required"):
            raise ProofError(f"{where}: `{kind}` requires `{name}`")
        elif "default" in spec:
            out[name] = spec["default"]
    return out


# --- helpers ---------------------------------------------------------------------


def _rel_files(root: Path, include: List[str], exclude: List[str], limit: int) -> List[str]:
    """Every regular file under `root` whose POSIX relative path matches, sorted.

    Sorted, not walked: the order must not depend on the filesystem, or two runs of the same proof
    report different first hits. Unreadable directories are skipped by the walk, not by us.
    """
    found: List[str] = []
    for base, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for name in sorted(names):
            path = Path(base) / name
            rel = path.relative_to(root).as_posix()
            if not any(fnmatch.fnmatch(rel, pattern) for pattern in include):
                continue
            if any(fnmatch.fnmatch(rel, pattern) for pattern in exclude):
                continue
            found.append(rel)
            if len(found) > limit:
                raise ProofError(
                    f"more than {limit} files match {include}: the proof is unbounded, so it is "
                    f"unrunnable — narrow `include` rather than accept a silent cap")
    return sorted(found)


def _read(path: Path) -> Optional[str]:
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _artefact(ctx: Context, name: str, text: str) -> Optional[str]:
    try:
        ctx.artefact_dir.mkdir(parents=True, exist_ok=True)
        path = ctx.artefact_dir / name
        path.write_text(text, encoding="utf-8", newline="\n")
        return str(path)
    except OSError:  # pragma: no cover - a read-only artefact dir must not fail a proof
        return None


def _executable_allowed(argv0: str, root: Path,
                        toolchain: Optional[Path] = None) -> Tuple[bool, str]:
    """May this proof run this executable?

    Three answers, in order: inside the pinned toolchain (the project declared it), inside the
    repository (the project wrote it), or an allowlisted name. Anything else is refused — but the
    toolchain check matters most in practice: a claim about a gitleaks hit names a gitleaks binary,
    and an allowlist that lists analyzers by hand goes stale the first time one is added.
    """
    prefix = toolchain or (Path(os.environ["REVIEW_COUNCIL_TOOLCHAIN"])
                           if os.environ.get("REVIEW_COUNCIL_TOOLCHAIN") else None)
    if "/" in argv0 or os.sep in argv0:
        candidate = Path(argv0)
        resolved = (root / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
        if _toolchain_provides(prefix, resolved.name, resolved):
            return True, ""
        if not str(resolved).startswith(str(root.resolve())):
            if resolved.name in ALLOWED_EXECUTABLES or resolved.name.startswith("python3"):
                return True, ""
            return False, (f"`{argv0}` is outside the repository and not on the pinned toolchain, "
                           f"and its name is not allowlisted")
        if not resolved.is_file():
            return False, f"`{argv0}` does not exist inside the repository"
        return True, ""
    if argv0 in ALLOWED_EXECUTABLES or argv0.startswith("python3"):
        return True, ""
    found = shutil.which(argv0)
    if _toolchain_provides(prefix, argv0, Path(found).resolve() if found else None):
        return True, ""
    return False, (f"`{argv0}` is not on the pinned toolchain and not allowlisted; a proof may run "
                   f"the project's own analyzers, not arbitrary binaries")


def _toolchain_provides(prefix: Optional[Path], name: str,
                        resolved: Optional[Path] = None) -> bool:
    """Does the pinned toolchain provide this executable?

    The toolchain is a `symlinkJoin`: `<prefix>/bin/gitleaks` is a symlink to
    `/nix/store/<hash>-gitleaks-8.30.1/bin/gitleaks`, which is NOT under `<prefix>`. Comparing
    resolved paths against the prefix therefore refuses every tool in a working toolchain — the
    question has to be asked the other way round: does `<prefix>/bin/<name>` point here?
    """
    if prefix is None or not name:
        return False
    candidate = prefix / "bin" / name
    try:
        if not candidate.exists():
            return False
        return resolved is None or candidate.resolve() == resolved
    except OSError:  # pragma: no cover - a broken link is not a working tool
        return False


# --- executors -------------------------------------------------------------------
# Each returns (supported, detail, observed). `supported=None` means unrunnable.


def _run_absent(p: Dict[str, Any], ctx: Context) -> Tuple[Optional[bool], str, Dict[str, Any]]:
    try:
        rx = re.compile(p["pattern"])
    except re.error as exc:
        raise ProofError(f"absent: `pattern` is not a valid regex ({exc})")
    files = _rel_files(ctx.root, p["include"], p["exclude"], int(p["max_files"]))
    hits: List[str] = []
    for rel in files:
        text = _read(ctx.root / rel)
        if text is None:
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if rx.search(line):
                hits.append(f"{rel}:{number}")
                if len(hits) >= 20:
                    break
        if len(hits) >= 20:
            break
    if hits:
        return False, f"{len(hits)}+ match(es) for `{p['pattern']}`: {', '.join(hits[:5])}", {
            "pattern": p["pattern"], "files_scanned": len(files), "hits": hits[:20]}
    return True, f"no match for `{p['pattern']}` in {len(files)} file(s)", {
        "pattern": p["pattern"], "files_scanned": len(files), "hits": []}


def _run_present(p: Dict[str, Any], ctx: Context) -> Tuple[Optional[bool], str, Dict[str, Any]]:
    path = ctx.root / p["path"]
    if not path.is_file():
        return False, f"{p['path']} does not exist", {"path": p["path"]}
    text = _read(path)
    if text is None:
        raise ProofError(f"present: {p['path']} is unreadable or larger than {MAX_FILE_BYTES} bytes")
    lines = text.splitlines()
    start = int(p["line"])
    end = int(p.get("line_end") or start)
    if start < 1 or end < start:
        raise ProofError("present: `line` must be >= 1 and `line_end` >= `line`")
    if start > len(lines):
        return False, f"{p['path']} has {len(lines)} line(s); {start} does not exist", {
            "path": p["path"], "lines": len(lines)}
    window = "\n".join(lines[start - 1:end])
    found = p["text"] in window
    return found, (f"line(s) {start}-{end} of {p['path']} " +
                   ("contain" if found else "do not contain") + f" `{p['text']}`"), {
        "path": p["path"], "line": start, "line_end": end, "excerpt": window[:400]}


def _resolve_binary(argv0: str, root: Path) -> str:
    """The absolute path the allowlist just approved, so `PATH` cannot make it unrunnable.

    `_executable_allowed` accepts a bare name the pinned toolchain provides — but
    `subprocess.run(["gitleaks", …])` still needs the binary on `PATH`. Outside the container,
    where the toolchain is not on `PATH`, that reported an approved tool as "not installed": a
    false `unrunnable` on exactly the proofs the toolchain exists for. The allowlist already knows
    where the binary is; this makes the execution use that knowledge.
    """
    if "/" in argv0 or os.sep in argv0:
        return argv0          # a path the allowlist already checked
    prefix = os.environ.get("REVIEW_COUNCIL_TOOLCHAIN")
    if not (prefix and (Path(prefix) / "bin" / argv0).exists()):
        # Measured: six passes proved a complexity defect with `ruff`, and three came back
        # "`ruff` is not installed" — because the caller had not exported the variable, while the
        # allowlist had just approved ruff as a pinned tool. A pinned tool that the allowlist
        # accepts must be runnable without an environment variable, so the toolchain is resolved
        # the same way the rest of the CLI resolves it.
        try:
            import toolchain  # noqa: PLC0415 - only needed when the variable is absent
            resolved = toolchain.resolve()
            if resolved:
                prefix = resolved
        except Exception:  # noqa: BLE001 - resolution is best effort; PATH is the fallback
            pass
    if prefix:
        candidate = Path(prefix) / "bin" / argv0
        try:
            if candidate.exists():
                return str(candidate)
        except OSError:  # pragma: no cover - a broken link is not a working tool
            pass
    return shutil.which(argv0) or argv0


def _run_command(p: Dict[str, Any], ctx: Context) -> Tuple[Optional[bool], str, Dict[str, Any]]:
    argv = list(p["argv"])
    if not argv:
        raise ProofError("command: `argv` is empty")
    # First, because a missing tree is a precondition for EVERY proof — and `subprocess` raises
    # FileNotFoundError for a missing CWD as well as a missing executable, which reported a
    # present, working `gitleaks` as "not installed". Measured: a re-adjudication pointed at a
    # tree that did not exist and every proof came back unrunnable naming the binary.
    if not Path(ctx.root).is_dir():
        raise ProofError(f"command: the repository root `{ctx.root}` does not exist")
    ok, why = _executable_allowed(argv[0], ctx.root)
    if not ok:
        return None, why, {}
    argv[0] = _resolve_binary(argv[0], ctx.root)
    expect = p["expect"]
    if not isinstance(expect, dict) or "exit" not in expect:
        raise ProofError("command: `expect` needs an `exit` of 'zero', 'nonzero' or an integer")
    timeout = int(p.get("timeout") or ctx.timeout)
    env = dict(os.environ, TZ="UTC", NO_COLOR="1")
    try:
        proc = subprocess.run(argv, cwd=str(ctx.root), capture_output=True, text=True,
                              timeout=timeout, env=env)
    except FileNotFoundError:
        return None, f"`{argv[0]}` is not installed", {}
    except subprocess.TimeoutExpired:
        return None, f"`{' '.join(argv)}` exceeded {timeout}s — unrunnable, not refuted", {}
    want = expect["exit"]
    if want == "zero":
        exit_ok = proc.returncode == 0
    elif want == "nonzero":
        exit_ok = proc.returncode != 0
    elif isinstance(want, int) and not isinstance(want, bool):
        exit_ok = proc.returncode == want
    else:
        raise ProofError("command: `expect.exit` must be 'zero', 'nonzero' or an integer")
    stdout_ok = True
    if expect.get("stdout_contains"):
        stdout_ok = expect["stdout_contains"] in proc.stdout
    absent_ok = True
    if expect.get("stdout_absent"):
        absent_ok = expect["stdout_absent"] not in proc.stdout
    supported = exit_ok and stdout_ok and absent_ok
    observed = {
        "argv": argv, "exit": proc.returncode, "expected_exit": want,
        "stdout_head": proc.stdout[:2000], "stderr_head": proc.stderr[:2000],
        "stdout_contains": bool(stdout_ok), "stdout_absent": bool(absent_ok),
    }
    artefact = _artefact(ctx, "command-" + re.sub(r"\W+", "-", " ".join(argv))[:60] + ".txt",
                         f"$ {' '.join(argv)}\nexit: {proc.returncode}\n\n{proc.stdout}\n"
                         f"--- stderr ---\n{proc.stderr}")
    if artefact:
        observed["artefact"] = artefact
    why = (f"`{' '.join(argv)}` exited {proc.returncode} "
           f"(expected {want})" + ("" if stdout_ok else "; stdout did not contain the expected text")
           + ("" if absent_ok else "; stdout contained text it must not"))
    return supported, why, observed


def _run_dom(p: Dict[str, Any], ctx: Context) -> Tuple[Optional[bool], str, Dict[str, Any]]:
    import probes  # local import: probes is a peer module, and this keeps import order honest

    driver = ctx.drivers.get("browser") or probes.browser_driver()
    if not driver:
        return None, ("no headless browser found (set COUNCIL_BROWSER_CMD) — the page was not "
                      "loaded, so the claim is unproven"), {}
    url = p.get("url") or os.environ.get("COUNCIL_WEB_URL", "").strip()
    if not url:
        for candidate in probes.WEB_ENTRIES:
            if (ctx.root / candidate).is_file():
                url = (ctx.root / candidate).resolve().as_uri()
                break
    if not url:
        return None, "no `url`, no $COUNCIL_WEB_URL and no web entry point in the tree", {}
    scratch = Path(tempfile.mkdtemp(prefix="council-proof-dom-"))
    shot = scratch / "page.png"
    argv = probes.browser_argv(driver, url, shot)
    try:
        proc = subprocess.run(argv, cwd=str(ctx.root), capture_output=True, text=True,
                              timeout=int(p.get("timeout") or ctx.timeout),
                              env=dict(os.environ, TZ="UTC", NO_COLOR="1"))
    except subprocess.TimeoutExpired:
        return None, f"the browser did not exit within the timeout for {url}", {}
    dom = proc.stdout if "<" in proc.stdout else ""
    if not dom:
        return None, f"the browser returned no DOM for {url} (exit {proc.returncode})", {}
    present = probes.selector_present(dom, p["selector"])
    want = p["expect"] == "present"
    observed = {"url": url, "selector": p["selector"], "present": present,
                "expected": p["expect"], "bytes": len(dom)}
    artefact = _artefact(ctx, "dom-" + re.sub(r"\W+", "-", p["selector"])[:40] + ".html", dom)
    if artefact:
        observed["artefact"] = artefact
    # The screenshot is the evidence a human can actually read: a DOM dump proves the element is
    # in the markup, the PNG proves what the page looked like. Copied out of the browser's scratch
    # dir, which is otherwise lost when the run ends.
    if shot.is_file():
        try:
            ctx.artefact_dir.mkdir(parents=True, exist_ok=True)
            kept = ctx.artefact_dir / (Path(artefact).stem + ".png" if artefact else "dom.png")
            kept.write_bytes(shot.read_bytes())
            observed["screenshot"] = str(kept)
        except OSError:  # pragma: no cover - a read-only artefact dir must not fail a proof
            pass
    return present == want, (f"`{p['selector']}` is {'present' if present else 'absent'} in {url} "
                             f"(expected {p['expect']})"), observed


def _run_http(p: Dict[str, Any], ctx: Context) -> Tuple[Optional[bool], str, Dict[str, Any]]:
    parsed = urllib.parse.urlparse(p["url"])
    if parsed.hostname not in LOOPBACK:
        raise ProofError(f"http: `{p['url']}` is not a loopback address — a proof that reaches the "
                         f"network is not reproducible, so only 127.0.0.1/::1/localhost are allowed")
    try:
        with urllib.request.urlopen(p["url"], timeout=int(p.get("timeout") or ctx.timeout)) as reply:
            status = reply.status
            body = reply.read(200_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        status, body = exc.code, ""
    except (urllib.error.URLError, OSError) as exc:
        return None, f"no server answered {p['url']}: {exc}", {}
    want_body = p.get("body_contains") or ""
    supported = status == int(p["expect_status"]) and (want_body in body if want_body else True)
    return supported, (f"GET {p['url']} -> {status} (expected {p['expect_status']})"
                       + ("" if not want_body else f"; body {'contains' if want_body in body else 'lacks'} `{want_body}`")), {
        "url": p["url"], "status": status, "body_head": body[:1000]}


def _run_json(p: Dict[str, Any], ctx: Context) -> Tuple[Optional[bool], str, Dict[str, Any]]:
    path = ctx.root / p["path"]
    if not path.is_file():
        return False, f"{p['path']} does not exist", {"path": p["path"]}
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProofError(f"json: {p['path']} could not be parsed ({exc})")
    node: Any = document
    pointer = p.get("pointer") or ""
    if pointer:
        if not pointer.startswith("/"):
            raise ProofError("json: `pointer` must start with '/' (RFC 6901)")
        for token in pointer.split("/")[1:]:
            token = token.replace("~1", "/").replace("~0", "~")
            if isinstance(node, list):
                try:
                    node = node[int(token)]
                except (ValueError, IndexError):
                    return False, f"{p['path']}#{pointer} does not exist", {"path": p["path"]}
            elif isinstance(node, dict) and token in node:
                node = node[token]
            else:
                return False, f"{p['path']}#{pointer} does not exist", {"path": p["path"]}
    if p.get("absent"):
        return False, f"{p['path']}#{pointer or '/'} exists", {"value": node}
    if "equals" not in p:
        raise ProofError("json: give `equals` or `absent: true` — a pointer alone proves nothing")
    supported = node == p["equals"]
    return supported, (f"{p['path']}#{pointer or '/'} is {json.dumps(node)[:120]} "
                       f"(expected {json.dumps(p['equals'])[:120]})"), {
        "path": p["path"], "pointer": pointer, "value": node}


def parse_diff(stdout: str) -> Tuple[Set[int], Set[int]]:
    """The line numbers a `git diff --unified=0` added (new side) and removed (old side).

    Pure and total, because this parser has already shipped one bug that no test caught: resetting
    a per-hunk flag kept only the LAST hunk's answer, and every genuine change above it was refuted
    (measured on a two-hunk file: the addition at line 2 read "not added in this change" while the
    addition at line 21 matched). A pure function can be property-tested against a model; a
    function that shells out to git first can only be spot-checked.
    """
    added: Set[int] = set()
    removed: Set[int] = set()
    old_line = 0
    new_line = 0
    for raw in stdout.splitlines():
        if raw.startswith("@@"):
            match = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", raw)
            if not match:
                continue
            old_line, new_line = int(match.group(1)), int(match.group(3))
        elif raw.startswith("---") or raw.startswith("+++"):
            continue          # the file headers, not a content line
        elif raw.startswith("-"):
            removed.add(old_line)
            old_line += 1
        elif raw.startswith("+"):
            added.add(new_line)
            new_line += 1
        elif raw.startswith(" "):
            # Context lines advance BOTH sides. `--unified=0` emits none, but a caller who changes
            # the flags must not silently shift every line number by the hunk's context.
            old_line += 1
            new_line += 1
    return added, removed


def _run_diff(p: Dict[str, Any], ctx: Context) -> Tuple[Optional[bool], str, Dict[str, Any]]:
    base = ctx.diff_base
    if not base:
        return None, ("this run has no base revision, so no line can be shown to be new — "
                      "the claim is unproven rather than false"), {}
    try:
        proc = subprocess.run(["git", "diff", "--unified=0", base, "--", p["path"]],
                              cwd=str(ctx.root), capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"git diff could not run: {exc}", {}
    if proc.returncode != 0:
        return None, f"git diff failed: {proc.stderr.strip()[:200]}", {}
    line = int(p["line"])
    added, removed = parse_diff(proc.stdout)
    target = removed if p.get("mode") == "removed" else added
    found = line in target
    verb = "removed by" if p.get("mode") == "removed" else "added in"
    return found, f"{p['path']}:{line} is {'not ' if not found else ''}{verb} this change", {
        "path": p["path"], "line": line, "mode": p.get("mode"), "base": base}


EXECUTORS: Dict[str, Callable[[Dict[str, Any], Context], Tuple[Optional[bool], str, Dict[str, Any]]]] = {
    "absent": _run_absent,
    "present": _run_present,
    "command": _run_command,
    "dom": _run_dom,
    "http": _run_http,
    "json": _run_json,
    "diff": _run_diff,
}


# --- evaluation and adjudication ---------------------------------------------------


def _result(kind: str, params: Dict[str, Any], status: str, detail: str,
            observed: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {"kind": kind, "params": params, "status": status, "detail": detail,
            "observed": observed or {}, "artefact": (observed or {}).get("artefact")}


def evaluate(proof: Dict[str, Any], ctx: Context) -> Dict[str, Any]:
    """Run one proof. Three outcomes and no fourth: nothing here can 'probably' be true."""
    if not isinstance(proof, dict):
        return _result("", {}, "unrunnable", "a proof must be an object")
    kind = str(proof.get("kind") or "")
    try:
        params = normalise(kind, proof.get("params") or {}, "proof")
    except ProofError as exc:
        return _result(kind, {}, "unrunnable", str(exc))
    executor = EXECUTORS.get(kind)
    if executor is None:  # declared in the contract, not implemented here
        return _result(kind, params, "unrunnable", f"`{kind}` is declared but has no executor")
    try:
        supported, detail, observed = executor(params, ctx)
    except ProofError as exc:
        return _result(kind, params, "unrunnable", str(exc))
    except Exception as exc:  # noqa: BLE001 - an executor crash is unrunnable, never a pass
        return _result(kind, params, "unrunnable", f"{type(exc).__name__}: {exc}")
    if supported is None:
        return _result(kind, params, "unrunnable", detail, observed)
    return _result(kind, params, "supported" if supported else "refuted", detail, observed)


#: Kinds whose control is the same check re-run against the base revision.
_BASE_CONTROL_KINDS = ("absent", "present", "command", "json")


def synthesise_control(proof: Dict[str, Any], ctx: Context) -> Optional[Dict[str, Any]]:
    """The control the reviewer should have written, derived from the proof itself.

    Two shapes, because there are two kinds of check:

    * a check that reads the tree (`absent`, `present`, `command`, `json`) is controlled by running
      the SAME check against the base revision. If it holds there too, it is not evidence about
      this change — it is evidence about the repository, and the claim is uncontrolled.
    * a check that observes a running system (`dom`, `http`) or the diff itself (`diff`) cannot be
      re-run against a tree, so its control is the same observation with the opposite expectation:
      a selector claimed present is controlled by the same selector being absent, a line claimed
      added by the same line being removed.

    Returns None when no control can be derived — no base revision for a tree-reading kind. That is
    `uncontrolled`, never `proven`: the absence of a control is not a control.
    """
    kind = str(proof.get("kind") or "")
    params = dict(proof.get("params") or {})
    if kind == "dom":
        flipped = dict(params)
        flipped["expect"] = "absent" if params.get("expect") == "present" else "present"
        return {"kind": kind, "params": flipped, "source": "orchestrator:expectation-flip"}
    if kind == "http":
        flipped = dict(params)
        flipped["expect_status"] = 404 if int(params.get("expect_status", 200)) == 200 else 200
        return {"kind": kind, "params": flipped, "source": "orchestrator:expectation-flip"}
    if kind == "diff":
        flipped = dict(params)
        flipped["mode"] = "removed" if params.get("mode", "added") == "added" else "added"
        return {"kind": kind, "params": flipped, "source": "orchestrator:mode-flip"}
    if kind in _BASE_CONTROL_KINDS and ctx.base_root is not None:
        return {"kind": kind, "params": params, "source": "orchestrator:base-revision"}
    return None


def _rebase(value: Any, root: Path, base_root: Path) -> Any:
    """Point absolute paths inside *root* at the same place inside *base_root*.

    A control that re-runs `["/repo/check.sh"]` against the base tree would execute the DEFECTIVE
    tree's script and prove nothing. Every absolute path under the root is rewritten; anything
    outside it (a toolchain binary, a system path) is left alone.
    """
    if isinstance(value, str):
        candidate = Path(value)
        if not candidate.is_absolute():
            return value
        try:
            relative = candidate.relative_to(root)
        except ValueError:
            return value
        return str(base_root / relative)
    if isinstance(value, list):
        return [_rebase(item, root, base_root) for item in value]
    if isinstance(value, dict):
        return {key: _rebase(item, root, base_root) for key, item in value.items()}
    return value


def _control_context(ctx: Context, source: str) -> Context:
    """Where the control runs. A base-revision control runs on the base tree, not this one."""
    if source != "orchestrator:base-revision":
        return ctx
    if ctx.base_root is None:
        raise ProofError("a base-revision control needs a base tree")
    artefact_dir = ctx.artefact_dir / "control"
    artefact_dir.mkdir(parents=True, exist_ok=True)
    return Context(root=ctx.base_root, artefact_dir=artefact_dir, diff_base=ctx.diff_base,
                   timeout=ctx.timeout, drivers=ctx.drivers, base_root=None)


def adjudicate(proof: Dict[str, Any], ctx: Context) -> Dict[str, Any]:
    """Evaluate a claim's proof, then its control, and say what the claim is worth.

    The control is the claim's negative control: a proof the orchestrator runs and requires to be
    REFUTED. Only then is the claim `proven`. A supported proof with no control is `uncontrolled`
    — reportable, not blockable — and a control that also passes is `control_did_not_fail`, which is
    the vacuity detector: the check cannot tell this claim apart from the opposite one.
    """
    verdict = evaluate(proof, ctx)
    if verdict["status"] != "supported":
        verdict["admission"] = verdict["status"]
        verdict["control"] = None
        verdict["class"] = ("refuted" if verdict["status"] == "refuted" else "unrunnable")
        return verdict
    control = proof.get("control")
    source = "reviewer"
    if not control:
        # The reviewer wrote no control. The orchestrator writes one from the proof itself, so
        # "the check can fail" stops being a promise the reviewer makes about its own work.
        control = synthesise_control(proof, ctx)
        source = (control or {}).get("source") or "none"
        if control is None:
            verdict["admission"] = "uncontrolled"
            verdict["control"] = None
            verdict["control_source"] = "none"
            verdict["class"] = "unproven"
            verdict["detail"] = (
                f"{verdict['detail']} — no control, and none could be synthesised"
                + ("" if ctx.base_root else " (no base revision supplied)"))
            return verdict
    if not isinstance(control, dict):
        verdict["admission"] = "uncontrolled"
        verdict["control"] = {"error": "`control` must be an object"}
        verdict["control_source"] = source
        verdict["class"] = "unproven"
        return verdict
    control_params = control.get("params") or {}
    if source == "orchestrator:base-revision":
        if ctx.base_root is None:
            raise ProofError("a base-revision control needs a base tree")
        control_params = _rebase(control_params, ctx.root, ctx.base_root)
    control_proof = {"kind": control.get("kind") or verdict["kind"], "params": control_params}
    ctrl = evaluate(control_proof, _control_context(ctx, source))
    verdict["control"] = {"kind": ctrl["kind"], "status": ctrl["status"], "detail": ctrl["detail"],
                          "source": source}
    verdict["control_source"] = source
    if ctrl["status"] == "refuted":
        verdict["admission"] = "proven"
        verdict["class"] = "proven"
    elif ctrl["status"] == "unrunnable":
        verdict["admission"] = "uncontrolled"
        verdict["class"] = "unproven"
        verdict["control"]["detail"] = f"the control could not run: {ctrl['detail']}"
    else:
        verdict["admission"] = "control_did_not_fail"
        verdict["class"] = "unproven"
    return verdict


# --- self-test ---------------------------------------------------------------------


def _fixture_tree(tmp: Path) -> Path:
    """A tree that makes every kind provable and refutable, built rather than committed.

    Built here so `--self-test` works inside the container image, where `tests/` is not shipped.
    """
    (tmp / "good.py").write_text("def helper():\n    return 1\n\nhelper()\n", encoding="utf-8")
    (tmp / "bad.py").write_text("def unused_helper():\n    return 2\n", encoding="utf-8")
    (tmp / "page.html").write_text(
        '<html><body><div id="app"><button class="cta">Go</button></div></body></html>',
        encoding="utf-8")
    (tmp / "data.json").write_text('{"version": 3, "name": "fixture"}', encoding="utf-8")
    return tmp


def self_test() -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Every kind, both directions. A kind that cannot fail its negative case is not a proof."""
    cases: List[Dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="council-proofs-") as raw:
        root = _fixture_tree(Path(raw))
        ctx = Context(root=root, artefact_dir=root / ".artefacts")
        py = sys.executable

        def case(name: str, proof: Dict[str, Any], want: str) -> None:
            got = evaluate(proof, ctx)["status"]
            cases.append({"case": name, "kind": proof["kind"], "want": want, "got": got,
                          "ok": got == want})

        case("absent finds the symbol", {"kind": "absent",
                                         "params": {"pattern": "unused_helper"}}, "refuted")
        case("absent excludes the definition site", {"kind": "absent",
                                                     "params": {"pattern": "unused_helper\\(",
                                                                "exclude": ["bad.py"]}}, "supported")
        case("present reads the cited line", {"kind": "present",
                                              "params": {"path": "bad.py", "line": 1,
                                                         "text": "def unused_helper"}}, "supported")
        case("present refuses a wrong citation", {"kind": "present",
                                                  "params": {"path": "bad.py", "line": 1,
                                                             "text": "def used_helper"}}, "refuted")
        case("command sees exit 0", {"kind": "command",
                                     "params": {"argv": [py, "-c", "import sys; sys.exit(0)"],
                                                "expect": {"exit": "zero"}}}, "supported")
        case("command sees a failure", {"kind": "command",
                                        "params": {"argv": [py, "-c", "import sys; sys.exit(3)"],
                                                   "expect": {"exit": "nonzero"}}}, "supported")
        # Both directions: a command that succeeded cannot support a claim that it failed.
        case("command refutes a failure that did not happen", {"kind": "command",
                                                              "params": {"argv": [py, "-c", "import sys; sys.exit(0)"],
                                                                         "expect": {"exit": "nonzero"}}}, "refuted")
        case("json reads a pointer", {"kind": "json",
                                      "params": {"path": "data.json", "pointer": "/version",
                                                 "equals": 3}}, "supported")
        case("json catches a wrong value", {"kind": "json",
                                            "params": {"path": "data.json", "pointer": "/version",
                                                       "equals": 4}}, "refuted")
        cases.extend(_self_test_http(root, ctx))
        cases.extend(_self_test_dom(root, ctx))
        cases.extend(_self_test_diff(root))

    # Green has to mean every kind was exercised in BOTH directions, not that the cases someone
    # remembered to write passed. `diff` had no case at all while the summary still read
    # "10/10 exercised and passed", which is how a hunk bug survived the suite.
    cases.extend(_coverage_gaps(cases))
    failures = [c for c in cases if c.get("ok") is False]
    return cases, failures  # type: ignore[return-value]


def _coverage_gaps(cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One failing case per kind that is not exercised in both directions."""
    covered: Dict[str, set] = {}
    for entry in cases:
        covered.setdefault(entry.get("kind", ""), set()).add(entry["want"])
    return [{"case": f"coverage: {kind} is exercised both ways", "kind": kind,
             "want": "both directions", "got": sorted(covered.get(kind, [])), "ok": False}
            for kind in EXECUTORS if covered.get(kind) != {"supported", "refuted"}]


def _self_test_http(root: Path, ctx: Context) -> List[Dict[str, Any]]:
    import http.server
    import threading

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib naming
            body = b'{"ok": true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:  # silence the request log
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        got = evaluate({"kind": "http", "params": {"url": f"http://127.0.0.1:{port}/",
                                                   "expect_status": 200,
                                                   "body_contains": '"ok"'}}, ctx)["status"]
        returns = evaluate({"kind": "http", "params": {"url": f"http://127.0.0.1:{port}/",
                                                       "expect_status": 404}}, ctx)["status"]
    finally:
        server.shutdown()
        server.server_close()
    return [
        {"case": "http sees a local server answer", "kind": "http", "want": "supported",
         "got": got, "ok": got == "supported"},
        {"case": "http refuses a wrong status", "kind": "http", "want": "refuted",
         "got": returns, "ok": returns == "refuted"},
    ]


def _self_test_dom(root: Path, ctx: Context) -> List[Dict[str, Any]]:
    import probes

    url = (root / "page.html").resolve().as_uri()
    driver = probes.browser_driver()
    if not driver:
        # NOT `ok: True`. A lane that was never exercised is not a lane that passed, and a summary
        # that says "10/10" for a run which skipped one is the same lie as a test that never ran.
        return [
            {"case": "dom finds a rendered element", "kind": "dom", "want": "supported",
             "got": "skipped", "ok": None, "skipped": True,
             "detail": "no headless browser on this host — the dom lane is not exercised here"},
            {"case": "dom refuses a missing element", "kind": "dom", "want": "refuted",
             "got": "skipped", "ok": None, "skipped": True,
             "detail": "no headless browser on this host — the dom lane is not exercised here"},
        ]
    present = evaluate({"kind": "dom", "params": {"selector": "#app", "expect": "present",
                                                 "url": url}}, ctx)["status"]
    # A browser that is PRESENT and cannot render is a broken lane, not a skipped one. This case
    # used to accept `unrunnable` and reported 10/10 inside an image whose chromium aborted on a
    # missing /dev/null — the exact failure a self-test exists to catch, waved through.
    absent = evaluate({"kind": "dom", "params": {"selector": "#missing", "expect": "present",
                                                "url": url}}, ctx)["status"]
    return [
        {"case": "dom finds a rendered element", "kind": "dom", "want": "supported",
         "got": present, "ok": present == "supported",
         "detail": "" if present == "supported" else
                   f"a driver was found at {driver!r} and the lane still failed"},
        {"case": "dom refuses a missing element", "kind": "dom", "want": "refuted",
         "got": absent, "ok": absent == "refuted",
         "detail": "" if absent == "refuted" else
                   f"a selector that is absent came back {absent!r} — the lane cannot refute"},
    ]


def _self_test_diff(root: Path) -> List[Dict[str, Any]]:
    """Both directions, on a MULTI-HUNK change.

    One hunk is the easy case and it hid the bug: the parser reset its answer at every hunk
    header, so only the last region was ever matched, and every genuine change above it came
    back "not added in this change". Two hunks, far apart, is the shape that catches it.
    """
    import subprocess as sp

    repo = root / "diffrepo"
    repo.mkdir()
    if not (repo / ".git").exists():
        sp.run(["git", "init", "-q"], cwd=repo, check=True)
        sp.run(["git", "config", "user.email", "selftest@example.invalid"], cwd=repo, check=True)
        sp.run(["git", "config", "user.name", "self test"], cwd=repo, check=True)
        lines = [f"line{i} = 'original'" for i in range(1, 31)]
        (repo / "a.py").write_text("\n".join(lines) + "\n", encoding="utf-8")
        sp.run(["git", "add", "a.py"], cwd=repo, check=True)
        sp.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
        changed = list(lines)
        changed[1] = "line2 = 'changed'"     # first hunk, line 2
        changed[20] = "line21 = 'changed'"   # last hunk, line 21
        (repo / "a.py").write_text("\n".join(changed) + "\n", encoding="utf-8")
    diff_ctx = Context(root=repo, artefact_dir=root / ".artefacts", diff_base="HEAD")

    def run(line: int, mode: str) -> str:
        return evaluate({"kind": "diff", "params": {"path": "a.py", "line": line, "mode": mode}},
                        diff_ctx)["status"]

    checks = [
        ("diff sees an addition in the FIRST hunk", run(2, "added"), "supported"),
        ("diff sees an addition in the last hunk", run(21, "added"), "supported"),
        ("diff refutes an unchanged line", run(5, "added"), "refuted"),
        ("diff sees a removal in the first hunk", run(2, "removed"), "supported"),
        ("diff refutes a removal that did not happen", run(5, "removed"), "refuted"),
    ]
    return [{"case": name, "kind": "diff", "want": want, "got": got, "ok": got == want}
            for name, got, want in checks]


# --- CLI ---------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="proofs",
        description=(__doc__ or "").splitlines()[0] if (__doc__ or "").strip() else None)
    parser.add_argument("--list", action="store_true", help="print the closed vocabulary")
    parser.add_argument("--self-test", action="store_true", help="every kind, both directions")
    parser.add_argument("--file", help="a JSON proof to evaluate")
    parser.add_argument("--root", default=".", help="the tree the proof runs against")
    parser.add_argument("--base", help="git revision a `diff` proof measures against "
                                       "(without it, `diff` is unrunnable, never assumed)")
    parser.add_argument("--base-tree", help="a clean checkout of the base revision; a claim that "
                                            "arrives without a control gets one synthesised from "
                                            "it (the same check, run where the defect is not)")
    parser.add_argument("--json", action="store_true", help="machine output")
    args = parser.parse_args(argv)

    if args.list:
        for name, spec in sorted(kinds().items()):
            required = ", ".join(f"{k}" for k, v in spec["params"].items() if v.get("required"))
            print(f"{name:9s} {spec['description']}\n          requires: {required}")
        return 0

    if args.self_test:
        cases, failures = self_test()
        skipped = [case for case in cases if case.get("skipped")]
        # Three outcomes, because "did not run" is not "passed":
        #   0  every kind was exercised and none failed
        #   3  some kind was never exercised — INCOMPLETE, and it says which
        #   1  a kind that ran, failed
        # A caller that only checks for non-zero still learns the truth; a caller that checks for
        # 0 can no longer be told a green summary by a run that skipped a lane.
        if args.json:
            print(json.dumps({"cases": cases, "failures": len(failures),
                              "skipped": [case["case"] for case in skipped],
                              "complete": not skipped}, indent=2))
        else:
            for case in cases:
                mark = "skip" if case.get("skipped") else ("ok  " if case.get("ok") else "FAIL")
                print(f"{mark} {case['case']}: wanted {case['want']}, got {case['got']}")
            passed = len(cases) - len(failures) - len(skipped)
            print(f"{passed}/{len(cases) - len(skipped)} exercised and passed"
                  + (f"; {len(skipped)} not exercised" if skipped else ""))
        if failures:
            return 1
        if skipped:
            print("INCOMPLETE: not exercised on this host — "
                  + ", ".join(case["case"] for case in skipped)
                  + ". An unexercised lane is not a passing one.")
            return 3
        return 0

    if not args.file:
        parser.print_help()
        return 2

    root = Path(args.root).resolve()
    proof = json.loads(Path(args.file).read_text(encoding="utf-8"))
    verdict = adjudicate(proof, Context(
        root=root, artefact_dir=root / ".review-council" / "proofs", diff_base=args.base,
        base_root=Path(args.base_tree).resolve() if args.base_tree else None))
    if args.json:
        print(json.dumps(verdict, indent=2, sort_keys=True))
    else:
        print(f"{verdict['kind']}: {verdict['admission']} — {verdict['detail']}")
    return 0 if verdict["class"] == "proven" else 1


if __name__ == "__main__":
    # Not a program: reached through `council <verb>`. See council.py.
    from council import require_dispatch

    require_dispatch("proofs")
    sys.exit(main())
