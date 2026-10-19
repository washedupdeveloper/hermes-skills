#!/usr/bin/env python3
"""Container entrypoint for review-council."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys

# COUNCIL_ROOT overrides; otherwise the framework root this file sits in.
REPO_DIR = (os.environ.get("COUNCIL_ROOT")
            or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Defaulting HERMES_HOME keeps this runnable (and testable) outside a container.
HERMES_HOME = os.environ.get("HERMES_HOME") or os.path.join(
    os.environ.get("HOME") or "/home/council", ".hermes")
os.environ["HERMES_HOME"] = HERMES_HOME

PROFILES_DIR = os.path.join(HERMES_HOME, "profiles")
PROFILES = ("council-generalist", "council-orchestrator")
HARNESS = os.path.join(REPO_DIR, "scripts", "council_loop.py")
INSTALL_BOTS = os.path.join(REPO_DIR, "scripts", "install_bots.py")
COUNCIL = os.path.join(REPO_DIR, "scripts", "council.py")

NO_HERMES = """\
ERROR: no Hermes found.

This image does not install Hermes -- the council is a Hermes application and
uses the Hermes you already have. Mount one in, which is the normal way:

  docker run --rm \\
    -v /path/to/repo:/repo \\
    -v "$HOME/.hermes:/home/council/.hermes" \\
    -v /path/to/hermes:/opt/hermes:ro \\
    review-council /repo

/opt/hermes/bin/hermes is found without being told; set HERMES_BIN only if the
binary lives somewhere else inside the mount.

Without it the deterministic probes still run, but nothing can review.
"""


def log(message: str) -> None:
    print(f"  {message}", file=sys.stderr)


# The image does not install Hermes: HERMES_BIN wins, then the usual mount.
def resolve_hermes() -> str | None:
    hermes_bin = os.environ.get("HERMES_BIN", "")
    if hermes_bin:
        if os.access(hermes_bin, os.X_OK):
            return hermes_bin
        found = shutil.which(hermes_bin)
        if found:
            return found
        log(f"HERMES_BIN is set to '{hermes_bin}' but nothing executable is there.")
        return None
    if os.access("/opt/hermes/bin/hermes", os.X_OK):
        return "/opt/hermes/bin/hermes"
    return shutil.which("hermes")


def passwd_line(uid: int, gid: int) -> str:
    return f"council:x:{uid}:{gid}:council:/home/council:/bin/sh\n"


def ensure_passwd_entry(uid: int | None = None, gid: int | None = None,
                        passwd: str = "/etc/passwd", group: str = "/etc/group") -> bool:
    """Make the runtime uid resolvable, and say whether an entry was added.

    The image runs as uid 1000 unless the caller says otherwise, and
    `--user "$(id -u):$(id -g)"` is how a mounted repository becomes writable.
    That uid has no entry in the image's passwd, and `nix` resolves $HOME through
    getpwuid: without an entry `nix eval` fails with "cannot determine user's home
    directory" *even when HOME is set*, which silently degrades every nix probe —
    flake-check, nix-eval, nix-eval-time — and drops beta for correctness and
    performance. Measured, not assumed.

    The image makes `/etc/passwd` and `/etc/group` writable for this reason. It is
    a disposable container, and an entry appended per run disappears with it.
    """
    try:
        import pwd  # POSIX only; this module also ships to Windows.
    except ImportError:
        return False
    getuid = getattr(os, "getuid", None)
    getgid = getattr(os, "getgid", None)
    getpwuid = getattr(pwd, "getpwuid", None)
    if getuid is None or getgid is None or getpwuid is None:
        return False
    real_uid = uid if uid is not None else getuid()
    real_gid = gid if gid is not None else getgid()
    try:
        getpwuid(real_uid)
        return False
    except KeyError:
        pass
    if not os.path.exists(passwd):
        return False
    try:
        with open(passwd, "a", encoding="utf-8") as handle:
            handle.write(passwd_line(real_uid, real_gid))
        if os.path.exists(group):
            with open(group, "a", encoding="utf-8") as handle:
                handle.write(f"council:x:{real_gid}:\n")
    except OSError as exc:
        log(f"WARNING: cannot add a passwd entry for uid {real_uid}: {exc}")
        log("         nix probes will fail with 'cannot determine user's home directory'.")
        return False
    return True


def install_profiles() -> None:
    log("creating the council profiles (first run on this volume)")
    try:
        code = subprocess.run([sys.executable, INSTALL_BOTS], stdout=sys.stderr,
                              stderr=sys.stderr).returncode
    except OSError as exc:
        log(f"ERROR: {exc}")
        code = 1
    if code != 0:
        log("ERROR: install_bots.py failed; the council cannot run without its profiles.")
        sys.exit(1)


def seed(source: str, name: str) -> None:
    for profile in PROFILES:
        target = os.path.join(PROFILES_DIR, profile, name)
        try:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copy(source, target)
        except OSError as exc:
            log(f"WARNING: could not seed {name}: {exc}")


def seed_credentials() -> None:
    if os.path.isfile("/seed/config.yaml"):
        log("seeding profile credentials from /seed/config.yaml")
        seed("/seed/config.yaml", "config.yaml")
    if os.path.isfile("/seed/.env"):
        log("seeding environment from /seed/.env")
        seed("/seed/.env", ".env")


def have_credentials() -> bool:
    for profile in PROFILES:
        config = os.path.join(PROFILES_DIR, profile, "config.yaml")
        if not os.path.isfile(config):
            continue
        try:
            with open(config, "rb") as handle:
                data = handle.read()
        except OSError:
            continue
        if re.search(rb"api_key|provider", data):
            return True
    return False


def run_harness(args: list[str]) -> None:
    """Replace this process with the harness, keeping its exit code."""
    try:
        # sys.executable, not the name `python3`: this process is already the
        # interpreter that should run the harness, and a name is a PATH lookup.
        os.execv(sys.executable, [sys.executable, HARNESS, *args])
    except OSError as exc:
        print(f"entrypoint: cannot run {sys.executable}: {exc}", file=sys.stderr)
        sys.exit(127)


def cli_verbs() -> set:
    """The verb table, asked of the CLI rather than copied.

    Loaded by path so this works from the framework tree and from a checkout. A
    copy here would be a second table, and the two would drift.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location("council", COUNCIL)
    if spec is None or spec.loader is None:
        return set()
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("council", module)
    spec.loader.exec_module(module)
    return set(module.VERBS) | set(module.SETUP) | {"setup", "inventory"}


def is_cli_invocation(argv: list[str]) -> bool:
    """True when the arguments are the CLI's business rather than a review's.

    `--help`, a verb, or nothing at all. None of it needs Hermes, and all of it
    used to be unreachable in the image: the entrypoint resolved Hermes before
    looking at its arguments, so `docker run review-council` -- whose Cmd is
    `--help` -- printed a credential error instead of the help, and there was no
    way to reach `doctor` or `gate` at all.
    """
    if not argv:
        return True
    first = argv[0]
    if first in ("-h", "--help", "help", "--verbs-json"):
        return True
    return first in cli_verbs()


def run_cli(argv: list[str]) -> None:
    """Hand off to the CLI. Same process image, so the exit code is the CLI's."""
    try:
        os.execv(sys.executable, [sys.executable, COUNCIL, *argv])
    except OSError as exc:
        print(f"entrypoint: cannot run {COUNCIL}: {exc}", file=sys.stderr)
        sys.exit(127)


def main() -> None:
    argv = sys.argv[1:]

    # First: `--user "$(id -u):$(id -g)"` gives a uid the image's passwd lacks, and
    # `nix` needs it resolvable. See ensure_passwd_entry.
    if ensure_passwd_entry():
        log("added a passwd entry for the runtime uid (nix needs one)")

    # Anything that is not a review goes to the CLI before Hermes is required: the
    # setup below exists to run a REVIEW, so gating `--help` and `doctor` behind a
    # Hermes mount made the image useless without one.
    if is_cli_invocation(argv):
        # Said here, not only in the docs: a container is exactly where someone
        # arrives without having read them.
        if argv and argv[0] != "setup" and not os.path.isfile(
                os.path.join(HERMES_HOME, "review-council.toml")):
            log("first run: `setup` walks you through configuring this machine")
        run_cli(argv)

    hermes = resolve_hermes()
    if not hermes:
        sys.stderr.write(NO_HERMES)
        sys.exit(1)
    log(f"hermes: {hermes}")

    # install_bots.py resolves `hermes` by name, so its directory goes on PATH.
    if "/" in hermes:
        hermes_dir = hermes.rsplit("/", 1)[0]
        if hermes_dir not in os.environ.get("PATH", "").split(":"):
            os.environ["PATH"] = hermes_dir + ":" + os.environ.get("PATH", "")

    if not all(os.path.isdir(os.path.join(PROFILES_DIR, p)) for p in PROFILES):
        install_profiles()

    seed_credentials()

    if not have_credentials():
        log("WARNING: no provider credentials in the profile configs.")
        log("         Mount a prepared home (-v ~/.hermes:/home/council/.hermes) or")
        log("         seed one (-v <config>:/seed/config.yaml:ro).")

    log("running: council " + " ".join(argv))
    run_harness(argv)


if __name__ == "__main__":
    # Not reached through `council`: the container ENTRYPOINT (flake.nix) runs this and
    # sets the dispatch variable. A bare run would install profiles, then start a review.
    import os

    if os.environ.get("REVIEW_COUNCIL_DISPATCHED") != "1":
        raise SystemExit(
            "entrypoint: this is the container's ENTRYPOINT, not a program.\n"
            "  run a review:  docker run --rm -v <repo>:/repo review-council <repo>\n"
            "  or from the flake:  council review <repo>\n"
            "Nothing under scripts/ is meant to be run by hand."
        )
    main()
