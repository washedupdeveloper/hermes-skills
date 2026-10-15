#!/usr/bin/env python3
"""install_dispatcher.py — run the kanban dispatcher as a systemd user service (M7)."""

from __future__ import annotations

import getpass
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

UNIT_NAME = "hermes-kanban-dispatch.service"
UNIT_DIR = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "systemd" / "user"
UNIT_PATH = UNIT_DIR / UNIT_NAME
USER = os.environ.get("USER") or getpass.getuser()

# Every place `nix` can live, in precedence order; a user unit sources no profile.
PATH_TAIL = "%h/.nix-profile/bin:/nix/var/nix/profiles/default/bin:/run/current-system/sw/bin:/usr/local/bin:/usr/bin:/bin"

# --help is byte-identical to what the shell version printed.
USAGE = """Install the kanban dispatcher as a systemd USER service (M7).

WHY THIS EXISTS. A kanban board is durable storage; it is not a scheduler. Nothing
advances a swarm unless a dispatcher ticks: the board sat idle for three minutes
with a `ready` root card and nothing claimed it. `hermes kanban dispatch` advances
it once, by hand. A review that only progresses when a human runs a command is not
the durability M7 is for, so the dispatcher runs as a service that survives logout
(linger), restarts on failure, and comes back after a reboot.

WHY NOT THE GATEWAY. Hermes' supported home for the dispatcher is the messaging
gateway (`hermes gateway`), which runs it embedded. This machine runs `hermes
serve` — the desktop backend — which does NOT dispatch, so there is no embedded
dispatcher to use. `hermes kanban daemon --force` is the documented standalone
path when no gateway exists. Installing a whole messaging gateway to schedule
reviews would be a much larger footprint for the same ticks.

THE RACE, stated plainly: if a messaging gateway is ever installed on this machine
with `kanban.dispatch_in_gateway: true` (the default), there will be TWO
dispatchers claiming the same board. The daemon refuses to start in that case
unless forced, which is why `--force` is here and why this script says so.

    council setup dispatcher [--interval SECONDS] [--uninstall] [--status]

UNIT_NAME="hermes-kanban-dispatch.service"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT_PATH="$UNIT_DIR/$UNIT_NAME"
INTERVAL=60
MODE="install"
"""


def unit_text(hermes: str, interval: str) -> str:
    """The unit body, with the resolved binary and PATH written in at install time."""
    return f"""# Installed by review-council's dispatcher installer (M7).
#
# A kanban board is durable storage, not a scheduler: without a dispatcher ticking,
# a swarm never advances. This runs the standalone dispatcher so a review progresses
# unattended and resumes after a reboot.
#
# --force: the standalone daemon refuses to start when it believes a gateway owns
# dispatch. This machine runs `hermes serve` (the desktop backend), which does NOT
# dispatch, so there is no embedded dispatcher to defer to. If a messaging gateway
# is ever installed here, REMOVE THIS UNIT — two dispatchers race for the same board.
[Unit]
Description=Hermes kanban dispatcher (review-council, standalone)
After=network.target

[Service]
Type=simple
ExecStart={hermes} kanban daemon --force --interval {interval} --verbose
Environment=PATH={os.path.dirname(hermes)}:{PATH_TAIL}
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
"""


def run(args: list, **kwargs) -> subprocess.CompletedProcess:
    """Run a command; a missing binary reads as exit 127, the way the shell does."""
    try:
        return subprocess.run(args, **kwargs)
    except OSError as exc:
        print(f"{args[0]}: {exc}", file=sys.stderr)
        return subprocess.CompletedProcess(args, 127)


def systemctl(*args: str, **kwargs) -> subprocess.CompletedProcess:
    return run(["systemctl", "--user", *args], **kwargs)


def lines(text: str) -> list:
    parts = (text or "").split("\n")
    if parts and parts[-1] == "":
        parts.pop()
    return parts


def head(text: str, count: int) -> str:
    return "".join(line + "\n" for line in lines(text)[:count])


def tail(text: str, count: int) -> str:
    return "".join(line + "\n" for line in lines(text)[-count:])


def do_status() -> int:
    proc = systemctl("status", UNIT_NAME, "--no-pager",
                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    sys.stdout.write(head(proc.stdout, 20))
    return 0


def do_uninstall() -> int:
    systemctl("disable", "--now", UNIT_NAME, stderr=subprocess.DEVNULL)
    try:
        UNIT_PATH.unlink()
    except OSError:
        pass
    systemctl("daemon-reload")
    print(f"removed {UNIT_NAME}")
    return 0


def do_install(interval: str) -> int:
    hermes = shutil.which("hermes")
    if not hermes:
        print("council setup dispatcher: 'hermes' is not on PATH — it owns the board, so the",
              file=sys.stderr)
        print("  dispatcher cannot run without it.", file=sys.stderr)
        return 1
    hermes = os.path.realpath(hermes)

    # Refuse to write a unit that would fail on every start.
    probe = run([hermes, "kanban", "daemon", "--help"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if probe.returncode != 0:
        print("council setup dispatcher: 'hermes kanban daemon' is unavailable in this build.",
              file=sys.stderr)
        print("  The dispatcher may now be gateway-only; check 'hermes gateway --help'.",
              file=sys.stderr)
        return 1

    try:
        UNIT_DIR.mkdir(parents=True, exist_ok=True)
        with open(UNIT_PATH, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(unit_text(hermes, interval))
    except OSError as exc:
        print(f"council setup dispatcher: cannot write {UNIT_PATH}: {exc}", file=sys.stderr)

    systemctl("daemon-reload")
    systemctl("enable", "--now", UNIT_NAME,
              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Verify, rather than assume: a silently dead unit is found weeks later.
    time.sleep(3)
    active = systemctl("is-active", "--quiet", UNIT_NAME,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if active.returncode == 0:
        print(f"dispatcher: running (interval {interval}s)")
        print(f"  unit:  {UNIT_PATH}")
        print(f"  check: systemctl --user status {UNIT_NAME}")
        print(f"  logs:  journalctl --user -u {UNIT_NAME} -n 30")
        linger = run(["loginctl", "show-user", USER, "-p", "Linger", "--value"],
                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        if (linger.stdout or "").strip() != "yes":
            print()
            print("  NOTE: linger is OFF, so this stops when you log out.")
            print(f"        enable with: loginctl enable-linger {USER}")
        return 0

    print("dispatcher: FAILED to start", file=sys.stderr)
    proc = systemctl("status", UNIT_NAME, "--no-pager",
                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    sys.stderr.write(tail(proc.stdout, 12))
    return 1


def main(argv: list | None = None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    interval = "60"
    mode = "install"

    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--interval":
            if i + 1 >= len(argv):
                # the shell died on the unset $2 here, with the same status
                print("council setup dispatcher: --interval needs a value", file=sys.stderr)
                return 1
            value = argv[i + 1]
            # Written into the unit's ExecStart, so a non-number produces a service
            # that fails at start rather than at install.
            if not value.isdigit() or int(value) < 1:
                print(f"council setup dispatcher: --interval must be a positive "
                      f"integer, not {value!r}", file=sys.stderr)
                return 1
            interval = value
            i += 2
        elif arg == "--uninstall":
            mode = "uninstall"
            i += 1
        elif arg == "--status":
            mode = "status"
            i += 1
        elif arg in ("-h", "--help"):
            sys.stdout.write(USAGE)
            return 0
        else:
            print(f"council setup dispatcher: unknown option: {arg}", file=sys.stderr)
            return 2

    if mode == "status":
        return do_status()
    if mode == "uninstall":
        return do_uninstall()
    return do_install(interval)


if __name__ == "__main__":
    # Not a program: reached through `council <verb>`. See council.py.
    from council import require_dispatch

    require_dispatch("setup dispatcher")
    sys.exit(main())
