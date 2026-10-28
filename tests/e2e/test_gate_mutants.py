#!/usr/bin/env python3
"""The gate's own mutants: every rule must fail on the state it forbids.

    python3 tests/e2e/test_gate_mutants.py

An eval-tier check decides its outcome at evaluation time, so `nix build` cannot tell a right
tree from a wrong one — a failing assertion throws while the derivation is being evaluated, and
the derivation is a constant. This therefore runs `nix eval` on `checks.workflows`, which is
where the assertions actually run.

Each entry below is one of two things:

  * a forbidden state put into this checkout (a floating runner, a range pin, an off-version
    site, a fifth adoption site, a missing adopted file), or
  * one rule neutered so it can no longer fire, while its negative control expects it to.

Every entry must make the gate exit non-zero. Two failures mean different things:

  * a mutant the gate ACCEPTS is a bug in the rule — the state it names is not measured;
  * a mutant whose anchor is GONE is drift in this file — the rule was reworded and the mutant
    must be re-pointed.

The tree is restored from a backup after each mutant, in a `finally`, so an interrupted run
leaves no `.mutant-bak` file behind and no edited source.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import re
import shutil
import stat
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[2]
TESTS = REPO / "nix/tests.nix"
PINS = REPO / "nix/pins.nix"
CI = REPO / ".github/workflows/ci.yml"
TEMPLATE = REPO / "skills/software-development/openspec/templates/ci-job.yml"
BOOTSTRAP = REPO / "skills/software-development/openspec/scripts/bootstrap.sh"
AGENTS = REPO / "AGENTS.md"
FIFTH = REPO / "scripts/install-openspec.sh"
PKG = "@fission-ai/openspec"

CHECK = ".#checks.x86_64-linux.workflows.drvPath"


def pinned() -> str:
    """The version this harness builds its anchors from, read from the one source."""
    text = PINS.read_text(encoding="utf-8")
    m = re.search(r'openspecCli\s*=\s*"([^"]+)"', text)
    if m is None:
        sys.exit("nix/pins.nix names no openspecCli version")
    return m.group(1)


def nix_eval() -> tuple[int, str]:
    try:
        proc = subprocess.run(
            ["nix", "eval", "--raw", CHECK],
            cwd=REPO, capture_output=True, text=True, timeout=600,
        )
    except FileNotFoundError:
        sys.exit("nix is not on PATH; this test needs the gate, not a stub")
    except subprocess.TimeoutExpired:
        return 124, "timed out"
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def summary(text: str) -> str:
    names = list(dict.fromkeys(re.findall(r"test_[a-z_]+", text)))[:2]
    m = re.search(r"error: \d+ tests failed", text)
    head = m.group(0) if m else ("timeout" if text == "timed out" else "error")
    return f"{head} :: {', '.join(names)}" if names else head


def mutants(pin: str) -> list[dict]:
    """One entry per state the gate claims to reject. Order matches the archived work order."""
    exact = f"{PKG}@{pin}"
    other = f"{PKG}@{pin.rsplit('.', 1)[0]}.0-mutant"  # exact shape, wrong value
    return [
        # 1.1 — every form a floating runner takes
        {"id": "1.1a", "what": "matrix os list", "file": CI, "kind": "append",
         "add": '\n        os: [ubuntu-latest]\n', "expect": "ci.yml"},
        {"id": "1.1b", "what": "quoted scalar runner", "file": CI,
         "old": "runs-on: ubuntu-24.04", "new": 'runs-on: "ubuntu-latest"', "expect": "ci.yml"},
        {"id": "1.1c", "what": "bracketed runner list", "file": CI,
         "old": "runs-on: ubuntu-24.04", "new": "runs-on: [ubuntu-latest]", "expect": "ci.yml"},
        {"id": "1.1d", "what": "block-list runner", "file": CI,
         "old": "runs-on: ubuntu-24.04", "new": "runs-on:\n      - ubuntu-latest",
         "expect": "ci.yml"},
        {"id": "1.1e", "what": "runner from inputs", "file": CI,
         "old": "runs-on: ubuntu-24.04", "new": "runs-on: \${{ inputs.os }}", "expect": "ci.yml"},
        # 1.2 — every non-exact install form
        {"id": "1.2a", "what": "@latest", "file": AGENTS, "old": exact,
         "new": f"{PKG}@latest", "expect": "AGENTS.md"},
        {"id": "1.2b", "what": "@^range", "file": AGENTS, "old": exact,
         "new": f"{PKG}@^{pin}", "expect": "AGENTS.md"},
        {"id": "1.2c", "what": "@~range", "file": AGENTS, "old": exact,
         "new": f"{PKG}@~{pin}", "expect": "AGENTS.md"},
        {"id": "1.2d", "what": "two-part version", "file": AGENTS, "old": exact,
         "new": f"{PKG}@{'.'.join(pin.split('.')[:2])}", "expect": "AGENTS.md"},
        {"id": "1.2e", "what": "versionless", "file": AGENTS, "old": exact,
         "new": PKG, "expect": "AGENTS.md"},
        {"id": "1.2f", "what": "trailing comment after a major", "file": AGENTS, "old": exact,
         "new": f"{PKG}@1   # a comment after the version", "expect": "AGENTS.md"},
        {"id": "1.2g", "what": "npm i -g @1", "file": CI,
         "old": f"npm install -g --ignore-scripts {exact}",
         "new": f"npm i -g {PKG}@1", "expect": "ci.yml"},
        {"id": "1.2h", "what": "npm install --global @1", "file": TEMPLATE,
         "old": f"npm install -g --ignore-scripts {exact}",
         "new": f"npm install --global {PKG}@1", "expect": "templates/ci-job.yml"},
        # 3.1 — an exact version that is not the pinned one
        {"id": "3.1a", "what": "AGENTS.md off-version", "file": AGENTS, "old": exact,
         "new": other, "expect": "AGENTS.md"},
        {"id": "3.1b", "what": "ci.yml off-version", "file": CI, "old": exact,
         "new": other, "expect": "ci.yml"},
        {"id": "3.1c", "what": "template off-version", "file": TEMPLATE, "old": exact,
         "new": other, "expect": "templates/ci-job.yml"},
        {"id": "3.1d", "what": "bootstrap.sh off-version", "file": BOOTSTRAP, "old": exact,
         "new": other, "expect": "bootstrap.sh"},
        # 3.2 — a fifth adoption site
        {"id": "3.2a", "what": "fifth site", "file": FIFTH, "kind": "create",
         "add": f"#!/usr/bin/env bash\nnpx -y {exact} validate\n",
         "expect": "scripts/install-openspec.sh"},
        # 2.1 — an adopted file that is not there
        {"id": "2.1a", "what": "adopted file missing", "file": TEMPLATE, "kind": "move",
         "expect": "skills/software-development/openspec/templates/ci-job.yml"},
        # 1.3 — rules neutered while their negative controls expect them to fire
        {"id": "1.3a", "what": "runner rule never fires", "file": TESTS,
         "old": '  runnerFloats = line: mentions "-latest" (stripComment line);',
         "new": "  runnerFloats = _line: false;",
         "expect": "test_the_runner_rule_rejects_every_form"},
        {"id": "1.3b", "what": "install rule never fires", "file": TESTS,
         "old": "ts = tokens line;", "new": "ts = [ ];",
         "expect": "test_the_install_rule_rejects_every_non_exact_form"},
        {"id": "1.3c", "what": "exactness accepts anything", "file": TESTS,
         "old": "spec: spec != null", "new": "spec: true || spec != null",
         "expect": "test_the_install_rule_rejects_every_non_exact_form"},
        {"id": "1.3d", "what": "containment fires everywhere", "file": TESTS,
         "old": '(builtins.replaceStrings [ needle ] [ "" ] text)',
         "new": '"x"',
         "expect": "test_no_adopted_file_pins_a_floating_runner"},
    ]


def run(entry: dict, scratch: pathlib.Path) -> tuple[str, str]:
    """Apply one mutant, run the gate, restore. Returns (verdict, failure summary)."""
    path: pathlib.Path = entry["file"]
    kind = entry.get("kind", "replace")
    backup = scratch / f"{entry['id']}-{path.name}.bak"
    created = False
    original_mode: int | None = None
    original_bytes: bytes | None = None
    try:
        if kind in ("replace", "append"):
            original_bytes = path.read_bytes()
            original_mode = stat.S_IMODE(path.stat().st_mode)
            # copy2, not write_text: a restored file must keep its executable bit. `bootstrap.sh`
            # is 755, and restoring it as 644 breaks it without changing a byte of content.
            shutil.copy2(path, backup)
            text = path.read_text(encoding="utf-8")
            if kind == "replace":
                if text.count(entry["old"]) < 1:
                    return "ANCHOR GONE — harness drift", "re-point this mutant"
                path.write_text(text.replace(entry["old"], entry["new"], 1), encoding="utf-8")
            else:
                path.write_text(text + entry["add"], encoding="utf-8")
        elif kind == "create":
            if path.exists():
                return "TARGET EXISTS — harness drift", str(path.relative_to(REPO))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(entry["add"], encoding="utf-8")
            created = True
            # Nix reads the git tree; an intent-to-add makes the file visible without staging
            # content.
            subprocess.run(["git", "add", "-N", str(path.relative_to(REPO))],
                           cwd=REPO, capture_output=True, text=True)
        elif kind == "move":
            shutil.move(str(path), str(scratch / "held-aside"))
        else:
            return "UNKNOWN KIND", kind

        rc, out = nix_eval()
        if rc == 0:
            return "ACCEPTED — the rule does not fire", "gate exited 0"
        if entry["expect"] not in out:
            return "FAILED, but did not name it", f"expected {entry['expect']!r} in the output"
        return "fails as required", summary(out)
    finally:
        # Prove the restore, mode included: a mutant that leaves the tree changed would make the
        # next mutant measure the wrong thing.
        if kind in ("replace", "append") and backup.exists():
            shutil.copy2(backup, path)
            if original_mode is not None:
                os.chmod(path, original_mode)
            if original_bytes is not None and path.read_bytes() != original_bytes:
                raise RuntimeError(f"{entry['id']}: restore left {path} changed")
            if original_mode is not None and stat.S_IMODE(path.stat().st_mode) != original_mode:
                raise RuntimeError(f"{entry['id']}: restore left {path} with the wrong mode")
        if created and path.exists():
            path.unlink()
            subprocess.run(["git", "rm", "--cached", "--quiet", str(path.relative_to(REPO))],
                           cwd=REPO, capture_output=True, text=True)
        elif kind == "move" and (scratch / "held-aside").exists():
            shutil.move(str(scratch / "held-aside"), str(path))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--only", help="run one mutant id (e.g. 1.1a)")
    args = ap.parse_args()

    pin = pinned()
    print(f"modal: {PKG}@{pin}, from nix/pins.nix")
    entries = [m for m in mutants(pin) if args.only in (None, m["id"])]
    if not entries:
        sys.exit(f"no mutant matches {args.only!r}")

    rc, _ = nix_eval()
    if rc != 0:
        sys.exit("the committed tree already fails the gate; fix that before mutating")

    width = max(len(e["what"]) for e in entries) + 2
    bad = []
    with tempfile.TemporaryDirectory(prefix="gate-mutants-") as td:
        scratch = pathlib.Path(td)
        for e in entries:
            verdict, detail = run(e, scratch)
            print(f"  {e['id']:<6}{e['what']:<{width}}{verdict:<32}{detail[:70]}")
            if not verdict.startswith("fails as required"):
                bad.append((e["id"], verdict))

    print(f"\n{len(entries) - len(bad)}/{len(entries)} mutants behaved")
    for mid, verdict in bad:
        print(f"  {mid}: {verdict}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())