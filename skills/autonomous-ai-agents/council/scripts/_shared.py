"""Helpers shared by more than one module under scripts/.

Loaded BY PATH, like every sibling here: these modules are separate programs, not a
package, and a plain import would depend on `sys.path[0]` being this directory --
true when `council` execs a module, but not when a test or `entrypoint.py` loads one
by path. An explicit path also cannot be shadowed by a third-party module of the
same name.

Only things whose second copy had ALREADY started to drift live here:

* the density denominator -- two implementations, two floors (0.0 and 0.001);
* the source-suffix set -- one `set`, one `frozenset`, same ten entries;
* the finding fingerprint -- three variants, and the third normalised the claim
  differently, so a carried finding and a re-found one could hash apart;
* the `hermes` subprocess wrapper -- two copies with different return shapes.

Pure helpers only: nothing here reads configuration, touches the network, or writes
a file.
"""
from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Dict, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent

#: Directories that are not source: VCS metadata, review output, dependency trees.
SKIP_PARTS = frozenset({".git", ".review-council", "node_modules", "result"})

#: The file types the density denominators count. ONE set, so the gate and the
#: calibration cannot disagree about what "source" means.
SOURCE_SUFFIXES = frozenset({
    ".py", ".nix", ".sh", ".bash", ".js", ".ts", ".go", ".rs", ".c", ".h",
})


def load_module(name: str, path: Optional[Path] = None) -> ModuleType:
    """Load a sibling module by path, once per process.

    By path, not by import: these scripts are the framework tree, run from the Nix
    store and from a bare checkout, and neither is an installed package.
    """
    cached = sys.modules.get(name)
    if cached is not None:
        return cached
    target = Path(path) if path is not None else HERE / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, target)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {name} from {target}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def norm_path(value: Any) -> str:
    """Repo-relative, forward-slashed. A Windows checkout may echo backslashes."""
    text = str(value or "").strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return text


def fingerprint(finding: Dict[str, Any]) -> str:
    """A stable identity for a finding.

    Deliberately coarse: the claim is normalised hard, because two passes -- or two
    ablation arms -- describing the same defect will not phrase it identically.
    """
    loc = finding.get("location") or {}
    path = norm_path(loc.get("path"))
    lines = str(loc.get("line_range") or "").strip()
    claim = str(finding.get("claim") or "")
    claim = re.sub(r"[^a-z0-9 ]+", " ", claim.lower())
    claim = " ".join(claim.split())[:120]
    return f"{path}|{lines}|{claim}"


def kloc(root: Optional[Path], *, floor: float = 0.0) -> float:
    """Thousands of source lines -- the denominator for findings density.

    `floor` is the caller's business, and the two callers differ deliberately: the
    scorer returns 0.0 for an unmeasurable repo, which switches it back to raw
    counts (you cannot normalise by a size you have not measured), while the
    calibration floors at a small positive number so a density is always defined.
    """
    if root is None or not root.is_dir():
        return 0.0
    total = 0
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix not in SOURCE_SUFFIXES:
            continue
        if any(part in SKIP_PARTS for part in path.parts):
            continue
        try:
            total += sum(1 for _ in path.open("r", encoding="utf-8", errors="replace"))
        except OSError:
            continue
    return max(total / 1000.0, floor)


def hermes_run(args: Sequence[str]) -> Tuple[int, str]:
    """A `hermes ...` call's exit status and stdout; stderr dropped.

    127 for a missing executable rather than an exception: every caller is reporting
    what can be known about an optional tool.
    """
    try:
        proc = subprocess.run(list(args), stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, text=True,
                              encoding="utf-8", errors="replace")
    except OSError:
        return 127, ""
    return proc.returncode, proc.stdout or ""
