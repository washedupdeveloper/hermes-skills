"""Behaviour tests for the modules that had none.

The council's finding was that four of the modules this refactor introduced had no
test exercising them: entrypoint.py, sync_to_skill.py, install_dispatcher.py and
toolchain.py. What is testable without a container or a daemon is their argument
handling and their pure decisions, and those are exactly the parts that broke --
an option without a value raised IndexError, and a destination guard had to exist
before it could be trusted.

Run standalone (no pytest needed):
    python tests/test_modules.py
"""
from __future__ import annotations

import ast
import contextlib
import functools
import importlib.util
import inspect
import io
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS))


def _load(name: str) -> Any:
    """The module, or None when this tree does not carry it.

    The council skill's DEPLOYMENT deliberately omits `sync_to_skill.py` — the
    copier's own copy loop excludes itself ("the copier never ships") — so this
    file has to import cleanly there too. Returning None keeps the import honest;
    a test that needs the module skips by name rather than passing vacuously.
    """
    path = SCRIPTS / f"{name}.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader, f"cannot load {name}.py"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def needs(name: str, module):
    """Skip a test when *module* is not in this tree, instead of not collecting.

    Raising SkipTest (rather than aborting the import) matters because an import
    error here aborts collection of the WHOLE file — in the deployment that meant
    none of these tests ran at all. pytest honours SkipTest natively; the
    standalone runner in `main()` catches it and prints a skip.
    """
    def deco(fn):
        if module is not None:
            return fn

        @functools.wraps(fn)
        def _skipped(*args, **kwargs):
            raise unittest.SkipTest(f"{name}.py is not shipped in this tree")

        return _skipped

    return deco


sync = _load("sync_to_skill")
toolchain = _load("toolchain")
dispatcher = _load("install_dispatcher")
hermes_home = _load("hermes_home")


def _run(module, argv):
    """Call module.main(argv); return (rc, stdout+stderr)."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        try:
            rc = module.main(argv)
        except SystemExit as exc:
            rc = exc.code if isinstance(exc.code, int) else 2
    return rc, out.getvalue()


# --- sync_to_skill: the destination guard -----------------------------------
# Skipped in the deployment, where the copier is absent by design.

@needs("sync_to_skill", sync)
def test_destination_may_not_exist_yet():
    with tempfile.TemporaryDirectory() as td:
        assert sync.is_our_destination(str(Path(td) / "council"))


@needs("sync_to_skill", sync)
def test_an_empty_destination_is_fine():
    with tempfile.TemporaryDirectory() as td:
        assert sync.is_our_destination(td)


@needs("sync_to_skill", sync)
def test_a_destination_that_is_the_council_skill_is_accepted():
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / "SKILL.md").write_text(
            "---\nname: council\ndescription: x\n---\n", encoding="utf-8")
        assert sync.is_our_destination(td)


@needs("sync_to_skill", sync)
def test_a_foreign_destination_is_refused():
    """The reproduced failure: DEST_SKILL pointed at a library root, and the sync's
    prune deleted files belonging to another skill."""
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / "other-skill").mkdir()
        (Path(td) / "other-skill" / "SKILL.md").write_text(
            "---\nname: other\n---\n", encoding="utf-8")
        assert not sync.is_our_destination(td)


# --- sync_to_skill: host caches are not content ------------------------------
# `--check` used to flag bytecode as EXTRA, so a deployment went permanently red
# the moment anyone verified it the documented way -- by running its suite in
# place. 40 `.pyc` files from one pytest run were enough to fail the gate.

def _prune(src: Path, dst: Path) -> tuple[bool, str]:
    """Run prune_tree in CHECK mode; return (drifted, output)."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        sync.CHECK_ONLY = True
        sync.DRIFT = False
        try:
            sync.prune_tree(str(src), str(dst))
            return sync.DRIFT, out.getvalue()
        finally:
            sync.CHECK_ONLY = False
            sync.DRIFT = False


@needs("sync_to_skill", sync)
def test_find_files_skips_host_caches():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "scripts" / "__pycache__").mkdir(parents=True)
        (root / "scripts" / "real.py").write_text("x = 1\n", encoding="utf-8")
        (root / "scripts" / "__pycache__" / "real.cpython-314.pyc").write_bytes(b"\x00")
        (root / "stray.pyc").write_bytes(b"\x00")
        (root / ".pytest_cache").mkdir()
        (root / ".pytest_cache" / "CACHEDIR.TAG").write_text("x\n", encoding="utf-8")
        # as_posix(): relpath() yields OS separators, and this asserts WHICH files
        # were found, not how the platform spells a path.
        found = sorted(Path(os.path.relpath(p, root)).as_posix()
                       for p in sync.find_files(td))
        assert found == ["scripts/real.py"], found


@needs("sync_to_skill", sync)
def test_bytecode_in_a_deployment_is_not_reported_as_drift():
    """The regression: verifying a deployment must not make --check fail."""
    with tempfile.TemporaryDirectory() as td:
        src, dst = Path(td) / "src", Path(td) / "dst"
        (src / "scripts").mkdir(parents=True)
        (src / "scripts" / "real.py").write_text("x = 1\n", encoding="utf-8")
        (src / "tests").mkdir()
        (src / "tests" / "test_x.py").write_text("y = 2\n", encoding="utf-8")
        (dst / "scripts" / "__pycache__").mkdir(parents=True)
        (dst / "scripts" / "real.py").write_text("x = 1\n", encoding="utf-8")
        (dst / "scripts" / "__pycache__" / "real.cpython-314.pyc").write_bytes(b"\x00")
        (dst / "tests").mkdir()
        (dst / "tests" / "test_x.py").write_text("y = 2\n", encoding="utf-8")
        (dst / "tests" / "__pycache__").mkdir()
        (dst / "tests" / "__pycache__" / "test_x.cpython-314.pyc").write_bytes(b"\x00")
        drifted, out = _prune(src, dst)
        assert not drifted, out
        assert "EXTRA" not in out, out


@needs("sync_to_skill", sync)
def test_a_genuinely_stray_file_is_still_reported():
    """The filter must not blind the check it exists to make usable."""
    with tempfile.TemporaryDirectory() as td:
        src, dst = Path(td) / "src", Path(td) / "dst"
        src.mkdir()
        dst.mkdir()
        (src / "real.py").write_text("x = 1\n", encoding="utf-8")
        (dst / "real.py").write_text("x = 1\n", encoding="utf-8")
        (dst / "notes.md").write_text("left behind\n", encoding="utf-8")
        drifted, out = _prune(src, dst)
        assert drifted, "a stray file must still be drift"
        assert "EXTRA" in out and "notes.md" in out, out


# --- toolchain: argument handling -------------------------------------------

def test_a_flagged_option_without_a_value_is_an_error_not_a_traceback():
    for flag in ("--repo", "--flake", "--which"):
        rc, out = _run(toolchain, [flag])
        assert rc == 2, f"{flag}: rc={rc} out={out}"
        assert "needs a value" in out, f"{flag}: {out}"


def test_the_baked_toolchain_wins_and_is_returned():
    """REVIEW_COUNCIL_TOOLCHAIN is what the image sets; asking nix first would need
    a writable store, which a container does not have."""
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / "bin").mkdir()
        os.environ["REVIEW_COUNCIL_TOOLCHAIN"] = td
        try:
            rc, out = _run(toolchain, ["--path"])
        finally:
            os.environ.pop("REVIEW_COUNCIL_TOOLCHAIN", None)
        assert rc == 0, out
        assert td in out, out


def test_resolve_is_cached_per_flake():
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / "bin").mkdir()
        os.environ["REVIEW_COUNCIL_TOOLCHAIN"] = td
        try:
            toolchain._RESOLVED.clear()
            assert toolchain.resolve() == td
            assert toolchain.resolve() == td
            assert toolchain._RESOLVED, "a success must be remembered"
        finally:
            os.environ.pop("REVIEW_COUNCIL_TOOLCHAIN", None)
            toolchain._RESOLVED.clear()


# --- install_dispatcher: the interval written into the unit ------------------

def test_a_non_numeric_interval_is_refused():
    """It goes into the unit's ExecStart, so a non-number is a service that fails
    at start rather than at install."""
    rc, out = _run(dispatcher, ["--interval", "foo"])
    assert rc == 1, f"rc={rc} out={out}"
    assert "positive integer" in out, out


def test_a_missing_interval_value_is_refused():
    rc, out = _run(dispatcher, ["--interval"])
    assert rc == 1, f"rc={rc} out={out}"
    assert "needs a value" in out, out


def test_the_unit_names_every_place_nix_lives():
    """The unit does not inherit the caller's PATH, so its list has to be complete."""
    text = dispatcher.unit_text("/usr/bin/hermes", "60")
    for location in ("/run/current-system/sw/bin", ".nix-profile/bin",
                     "/nix/var/nix/profiles/default/bin"):
        assert location in text, f"the unit's PATH is missing {location}"


# --- hermes_home -------------------------------------------------------------

def test_hermes_home_is_honoured():
    os.environ["HERMES_HOME"] = "/tmp/explicit-home"
    try:
        assert hermes_home.resolve() == "/tmp/explicit-home"
    finally:
        os.environ.pop("HERMES_HOME", None)


# --- entrypoint: the Hermes resolution order --------------------------------

def test_entrypoint_prefers_hermes_bin():
    saved = dict(os.environ)
    try:
        os.environ["HERMES_BIN"] = sys.executable
        entry = _load("entrypoint")
        assert entry.resolve_hermes() == sys.executable
    finally:
        os.environ.clear()
        os.environ.update(saved)


def test_entrypoint_reports_no_hermes_rather_than_guessing():
    saved = dict(os.environ)
    try:
        os.environ.pop("HERMES_BIN", None)
        os.environ["PATH"] = "/nonexistent"
        entry = _load("entrypoint")
        with contextlib.redirect_stderr(io.StringIO()):
            assert entry.resolve_hermes() is None
    finally:
        os.environ.clear()
        os.environ.update(saved)


# --- entrypoint: what is a review, and what is the CLI ------------------------
#
# The container's Cmd is `--help`, and the entrypoint used to resolve Hermes
# BEFORE looking at its arguments -- so `docker run review-council` printed a
# credential error instead of the help, and `doctor` or `gate` were unreachable
# in the image. Only a REVIEW needs Hermes.

def test_entrypoint_sends_the_cli_verbs_to_the_cli():
    entry = _load("entrypoint")
    for argv in ([], ["--help"], ["-h"], ["help"], ["--verbs-json"],
                 ["doctor"], ["gate"], ["probes"], ["setup"], ["inventory"]):
        assert entry.is_cli_invocation(argv), argv


def test_entrypoint_treats_a_target_as_a_review():
    entry = _load("entrypoint")
    for argv in (["/repo"], ["/repo", "--mode", "advisory"], ["./somewhere"],
                 ["/repo", "--max-rounds", "1", "--samples", "1"]):
        assert not entry.is_cli_invocation(argv), argv


def test_entrypoint_reads_the_real_verb_table():
    """Not a copy: the table it consults is the CLI's own, so a new verb is
    reachable in the container the moment it exists."""
    entry = _load("entrypoint")
    verbs = entry.cli_verbs()
    assert {"review", "gate", "doctor", "probes", "baseline"} <= verbs, sorted(verbs)
    # and it is the CLI's table, not a literal here
    assert "not-a-verb" not in verbs


# --- the runtime uid needs a passwd entry ------------------------------------
#
# `--user "$(id -u):$(id -g)"` is how a mounted repo becomes writable, and it gives
# the container a uid the image's passwd does not know. nix resolves $HOME through
# getpwuid and fails without an entry -- "cannot determine user's home directory" --
# even when HOME is set, so every nix probe degrades and beta silently drops.

# `ensure_passwd_entry` needs `pwd`: the container path appends to /etc/passwd, and
# Windows has no passwd database at all, so there the function reports "nothing
# added" rather than raising. The capability is POSIX/container-only, so the test
# that requires it is guarded; the Windows behaviour is pinned separately below, on
# every platform, by hiding the module.
_HAS_PWD = importlib.util.find_spec("pwd") is not None
_ABSENT = object()


def test_a_passwd_entry_is_added_for_an_unknown_uid(tmp_path):
    if not _HAS_PWD:
        raise unittest.SkipTest("no pwd module: the passwd path is container-only")
    entry = _load("entrypoint")
    passwd = tmp_path / "passwd"
    group = tmp_path / "group"
    passwd.write_text("root:x:0:0:root:/root:/bin/sh\n", encoding="utf-8")
    group.write_text("root:x:0:\n", encoding="utf-8")

    added = entry.ensure_passwd_entry(uid=4242, gid=4242,
                                      passwd=str(passwd), group=str(group))
    assert added is True
    text = passwd.read_text(encoding="utf-8")
    assert "4242" in text, text
    assert text.startswith("root:x:0:0:root:/root:/bin/sh\n"), "the existing entry was lost"
    assert "4242" in group.read_text(encoding="utf-8")


def test_no_passwd_entry_is_reported_when_pwd_is_absent(tmp_path):
    """Windows has no `pwd`, and there the container-only path must report "nothing
    added" rather than raising. That is what it does on the Windows CI runner, which
    is why the test above is guarded. Reproduced on any platform by hiding the
    module, putting this interpreter in exactly the state Windows is in."""
    entry = _load("entrypoint")
    saved = sys.modules.get("pwd", _ABSENT)
    sys.modules["pwd"] = None  # type: ignore[assignment]  # `import pwd` raises ImportError
    try:
        added = entry.ensure_passwd_entry(uid=4242, gid=4242,
                                          passwd=str(tmp_path / "passwd"),
                                          group=str(tmp_path / "group"))
    finally:
        if saved is _ABSENT:
            sys.modules.pop("pwd", None)
        else:
            sys.modules["pwd"] = saved  # type: ignore[assignment]
    assert added is False


def test_no_passwd_entry_is_added_for_a_known_uid(tmp_path):
    """An entry that already resolves must not be duplicated — the file would grow
    on every container start."""
    entry = _load("entrypoint")
    passwd = tmp_path / "passwd"
    group = tmp_path / "group"
    passwd.write_text("root:x:0:0:root:/root:/bin/sh\n", encoding="utf-8")
    group.write_text("root:x:0:\n", encoding="utf-8")
    before = passwd.read_text(encoding="utf-8")

    # uid 0 always resolves.
    assert entry.ensure_passwd_entry(uid=0, gid=0, passwd=str(passwd),
                                     group=str(group)) is False
    assert passwd.read_text(encoding="utf-8") == before


def test_a_missing_passwd_file_is_not_an_error(tmp_path):
    """Outside the container there is nothing to append to, and that must not
    abort the run."""
    entry = _load("entrypoint")
    assert entry.ensure_passwd_entry(uid=4242, gid=4242,
                                     passwd=str(tmp_path / "absent"),
                                     group=str(tmp_path / "absent-too")) is False


# --- the dispatch rule --------------------------------------------------------
#
# A module under scripts/ is not a program. Several of them ACT rather than
# report — `setup bots` writes into HERMES_HOME, `setup skill` prunes a skill
# deployment, `corpus` plants defects in a repository it is pointed at, and
# `review`, `sample` and `ablate` spend real agent turns — so a bare
# `python3 scripts/<module>.py` must refuse.
#
# The guard lives in `__main__`, never at import: the suite loads these files as
# LIBRARIES and calls main() directly, which is not a hand-run. The tests above
# depend on that, so this is also the test that keeps the guard from being moved
# somewhere it would break them.

def _main_blocks():
    """(module, verb) for every module that has a `__main__` block."""
    out = {}
    for path in sorted(SCRIPTS.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, ast.If):
                continue
            if "__main__" not in ast.dump(node.test):
                continue
            out[path.name] = ast.dump(node)
    return out


def test_every_module_refuses_a_direct_invocation():
    blocks = _main_blocks()
    assert blocks, "no __main__ blocks found — the walker is broken"
    unguarded = sorted(n for n, dump in blocks.items()
                       if n != "council.py" and "require_dispatch" not in dump
                       and "REVIEW_COUNCIL_DISPATCHED" not in dump)
    assert not unguarded, (
        "these modules would run if someone invoked the file directly:\n  "
        + "\n  ".join(unguarded)
    )


def test_the_dispatcher_itself_is_not_guarded():
    """council.py IS the entry point: guarding it would make the CLI unusable."""
    assert "require_dispatch" not in _main_blocks().get("council.py", "")


def test_the_guard_names_the_verb_the_cli_actually_exposes():
    """The message tells a reader what to run instead, so the verb it names has to
    be one the CLI accepts. A module renamed without its guard would otherwise
    point at a verb that does not exist."""
    cli = _load("council")
    by_script = {spec[0]: name for name, spec in cli.VERBS.items()}
    by_script.update({script: f"setup {name}" for name, (script, _) in cli.SETUP.items()})

    wrong = []
    for path in sorted(SCRIPTS.glob("*.py")):
        if path.name in ("council.py", "entrypoint.py"):
            continue
        src = path.read_text(encoding="utf-8")
        if "require_dispatch(" not in src:
            continue
        match = re.search(r'require_dispatch\("([^"]+)"\)', src)
        claimed = match.group(1) if match else None
        expected = by_script.get(path.name)
        if expected != claimed:
            wrong.append(f"{path.name}: says {claimed!r}, the CLI calls it {expected!r}")
    assert not wrong, "\n".join(wrong)


def test_the_guard_covers_every_verb_that_acts():
    """Every module in the CLI's table has a guard. A new verb whose module forgot
    one would be the exact hole this closes."""
    cli = _load("council")
    scripts = {spec[0] for spec in cli.VERBS.values()}
    scripts |= {script for script, _ in cli.SETUP.values()}
    blocks = _main_blocks()
    missing = sorted(s for s in scripts
                     if s in blocks and "require_dispatch" not in blocks[s])
    assert not missing, f"verbs whose module is unguarded: {missing}"


def _requires_a_fixture(fn) -> bool:
    """True when *fn* takes a required argument, i.e. a pytest fixture.

    This runner calls every `test_*` with no arguments, so a `tmp_path` test used to
    raise TypeError and abort the whole run — the module's "run standalone, no pytest
    needed" claim was half false. Those tests are pytest's to run; skip them plainly.
    """
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False
    return any(p.default is inspect.Parameter.empty
               and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
               for p in params.values())


def main() -> int:
    failures = 0
    skipped = 0
    for name, fn in sorted(globals().items()):
        if not (name.startswith("test_") and callable(fn)):
            continue
        if _requires_a_fixture(fn):
            skipped += 1
            print(f"  skip  {name}  (needs pytest: takes a fixture)")
            continue
        try:
            fn()
            print(f"  ok    {name}")
        except unittest.SkipTest as exc:
            skipped += 1
            print(f"  skip  {name}  ({exc})")
        except AssertionError as exc:
            failures += 1
            print(f"  FAIL  {name}\n        {exc}")
    print(f"\n  {failures} failure(s), {skipped} skipped")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
