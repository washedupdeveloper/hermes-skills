#!/usr/bin/env python3
"""Build a corpus whose defects are known by construction.

Inject defects into EXISTING files of a repository the council has already
cleaned, so every injected defect is truth and every finding outside the
manifest is a genuine false positive. Each injection is format-clean by the
target's own formatter and contradicts a comment already in the file.

    council corpus --base <repo> --out <dir> [--manifest <path>]
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

# Every `find` must appear EXACTLY once in its file, or the run aborts. A silent
# mismatch would mean a defect that is not there while the manifest claims it is.
INJECTIONS: List[Dict[str, Any]] = [
    {
        "id": "SEC-1",
        "path": "modules/clanServices/base-system/default.nix",
        "dimension": "security",
        "severity": "critical",
        "claim": "SSH password authentication is force-enabled, so the account's "
                 "vars-backed password becomes a network-reachable credential. "
                 "Key-only access is the stated posture. `mkForce` means it wins "
                 "silently over the clan sshd service's `false`.",
        "find": "                PasswordAuthentication = false;\n",
        "replace": "                PasswordAuthentication = lib.mkForce true;\n",
    },
    {
        "id": "SEC-2",
        "path": "modules/clanServices/base-system/default.nix",
        "dimension": "security",
        "severity": "high",
        "claim": "accept-flake-config is on, so every flake this machine "
                 "evaluates can inject substituters and trusted public keys.",
        "find": "                auto-optimise-store = lib.mkDefault true;\n",
        "replace": "                auto-optimise-store = lib.mkDefault true;\n"
                   "                accept-flake-config = true;\n",
    },
    {
        "id": "SEC-3",
        "path": "modules/clanServices/base-system/default.nix",
        "dimension": "security",
        "severity": "medium",
        "claim": "sudo is force-restricted away from wheel, so the module's "
                 "hardening no longer applies to the group it was written for.",
        "find": "            security.sudo.execWheelOnly = lib.mkDefault true;\n",
        "replace": "            security.sudo.execWheelOnly = lib.mkForce false;\n",
    },
    {
        "id": "SEC-4",
        "path": "machines/host/configuration.nix",
        "dimension": "security",
        "severity": "high",
        "claim": "The broker port is opened on every interface rather than "
                 "eth0. Under mirrored networking that covers the Windows "
                 "host's interfaces, not just the guest's.",
        "find": "  networking.firewall.interfaces.eth0.allowedTCPPorts = [ 1883 ];\n",
        "replace": "  networking.firewall.allowedTCPPorts = [\n"
                   "    1883\n"
                   "    9001\n"
                   "  ];\n",
    },
    {
        "id": "COR-1",
        "path": "modules/clanServices/base-system/default.nix",
        "dimension": "correctness",
        "severity": "medium",
        "claim": "system.stateVersion is force-set, overriding the clan-managed "
                 "value. It must never change after install, and `mkForce` makes "
                 "the override silent.",
        "find": "            users.mutableUsers = lib.mkDefault false;\n",
        "replace": "            users.mutableUsers = lib.mkDefault false;\n"
                   "            system.stateVersion = lib.mkForce \"24.11\";\n",
    },
    {
        "id": "COR-2",
        "path": "machines/host/configuration.nix",
        "dimension": "correctness",
        "severity": "medium",
        "claim": "/mnt is no longer pruned from the locate index, so the daily "
                 "updatedb walks the host's 9p volumes from inside the guest.",
        "find": "        \"/mnt\"\n        \"/tmp\"\n",
        "replace": "        \"/tmp\"\n",
    },
    {
        "id": "PERF-1",
        "path": "machines/host/configuration.nix",
        "dimension": "performance",
        "severity": "medium",
        "claim": "Dev-only lint and format tools are installed system-wide as "
                 "well as in the devshell, so every rebuild carries them.",
        "find": "  programs.nix-ld.enable = true;\n",
        "replace": "  programs.nix-ld.enable = true;\n"
                   "\n"
                   "  environment.systemPackages = with pkgs; [\n"
                   "    nil\n"
                   "    nixfmt\n"
                   "    statix\n"
                   "    deadnix\n"
                   "  ];\n",
    },
    {
        "id": "PERF-2",
        "path": "machines/host/configuration.nix",
        "dimension": "performance",
        "severity": "low",
        "claim": "download-buffer-size is raised, against the note above that "
                 "Nix 2.33 lowered the default deliberately.",
        "find": "  nix.settings = {\n    max-jobs = 6;\n    cores = 2;\n  };\n",
        "replace": "  nix.settings = {\n    max-jobs = 6;\n    cores = 2;\n"
                   "    download-buffer-size = 104857600;\n  };\n",
    },
    {
        "id": "RD-1",
        "path": "modules/clanServices/base-system/default.nix",
        "dimension": "readability",
        "severity": "low",
        "claim": "The comment above the i18n block asserts the opposite of what the "
                 "code does -- it claims the clan-wide locale is not applied, while "
                 "the very next lines apply it. A reader is actively misled.",
        "find": "            i18n = {\n",
        "replace": "            # Locale is pinned to the POSIX default; the clan-wide\n"
                   "            # value is deliberately not applied here.\n"
                   "            i18n = {\n",
    },
    {
        "id": "RD-2",
        "path": "machines/host/configuration.nix",
        "dimension": "readability",
        "severity": "low",
        "claim": "A commented-out duplicate of the block below it is left in "
                 "place, leaving two versions of the same setting to drift.",
        "find": "  programs.nh = {\n    enable = true;\n",
        "replace": "  # programs.nh = {\n  #   enable = false;\n"
                   "  #   clean.enable = false;\n  # };\n"
                   "  programs.nh = {\n    enable = true;\n",
    },
    # --- the hard class -------------------------------------------------------
    # Invisible in their own file (nothing there is wrong, the tree evaluates): each
    # exists only BETWEEN files, e.g. a plain definition quietly beating another
    # module's `lib.mkDefault`. A single generalist pass found 8 of the 10 above.
    {
        "id": "SEC-5",
        "path": "modules/clanServices/wsl/default.nix",
        "dimension": "security",
        "severity": "medium",
        "claim": "hardware.graphics is force-enabled, contradicting the note "
                 "directly above it that the stack is ~0.8 GiB of the closure "
                 "and nothing here runs a graphical program.",
        "find": "          hardware.graphics.enable = lib.mkForce false;\n",
        "replace": "          hardware.graphics.enable = lib.mkForce true;\n",
    },
    {
        "id": "SEC-6",
        "path": "modules/home/git.nix",
        "dimension": "security",
        "severity": "high",
        "claim": "Commit signing is disabled, so every commit this machine "
                 "produces is unsigned -- the opposite of what the file is for.",
        "find": "      commit.gpgsign = lib.mkDefault true;\n",
        "replace": "      commit.gpgsign = lib.mkDefault false;\n",
    },
    {
        "id": "SEC-7",
        "path": "modules/flake/git-hooks.nix",
        "dimension": "security",
        "severity": "high",
        "claim": "The gitleaks secret-scanning hook is disabled, so a credential "
                 "committed to this repo is no longer caught before it lands.",
        "find": "            gitleaks = {\n              enable = true;\n",
        "replace": "            gitleaks = {\n              enable = false;\n",
    },
    {
        "id": "SEC-8",
        "path": "machines/host/configuration.nix",
        "dimension": "security",
        "severity": "high",
        "claim": "A second `trusted-users` list is declared here. The option is a "
                 "list, so this MERGES with base-system's rather than replacing "
                 "it: the host appears to narrow trust and instead widens it to "
                 "every account in @users, who may then set restricted nix "
                 "options. Nothing in this file is wrong on its own.",
        "find": "    cores = 2;\n",
        "replace": "    cores = 2;\n"
                   "    trusted-users = [ \"@users\" ];\n",
    },
    {
        "id": "SEC-9",
        "path": "machines/host/configuration.nix",
        "dimension": "security",
        "severity": "medium",
        "claim": "The broker ACL grants `readwrite #` -- every topic -- where it "
                 "was scoped to `plants/#`. The client's own topic restriction is "
                 "gone, so a compromised monitor can rewrite any topic on the broker.",
        "find": "          acl = [ \"readwrite plants/#\" ];\n",
        "replace": "          acl = [ \"readwrite #\" ];\n",
    },
    {
        "id": "SEC-10",
        "path": "machines/host/configuration.nix",
        "dimension": "security",
        "severity": "medium",
        "claim": "useDHCP is enabled on a guest whose address comes from WSL "
                 "mirrored networking, contradicting the comment above it: the "
                 "generated DHCP client competes with the Windows host for the lease.",
        "find": "    useDHCP = false;\n",
        "replace": "    useDHCP = true;\n",
    },
    {
        "id": "COR-3",
        "path": "modules/clanServices/base-system/default.nix",
        "dimension": "correctness",
        "severity": "high",
        "claim": "The GC retention is `--delete-older-than 7`, which is seven "
                 "SECONDS, not seven days. Every automatic GC would delete almost "
                 "the entire store. The unit suffix is missing.",
        "find": "                options = lib.mkDefault \"--delete-older-than 7d\";\n",
        "replace": "                options = lib.mkDefault \"--delete-older-than 7\";\n",
    },
    {
        "id": "COR-4",
        "path": "modules/home/default.nix",
        "dimension": "correctness",
        "severity": "medium",
        "claim": "The home directory is hardcoded to one machine's user instead of "
                 "deriving from the clan-provided username, so the configuration no "
                 "longer works for anyone else -- the portability the repo is built "
                 "around is silently lost.",
        "find": "        homeDirectory = \"/home/${username}\";\n",
        "replace": "        homeDirectory = \"/home/otheruser\";\n",
    },
    {
        "id": "COR-5",
        "path": "modules/flake/git-hooks.nix",
        "dimension": "correctness",
        "severity": "high",
        "claim": "The large-file guard is disabled, so a binary or dataset can be "
                 "committed to the repository and land in its history permanently.",
        "find": "            check-added-large-files.enable = true;\n",
        "replace": "            check-added-large-files.enable = false;\n",
    },
    {
        "id": "COR-6",
        "path": "modules/clanServices/wsl/default.nix",
        "dimension": "correctness",
        "severity": "medium",
        "claim": "systemd-binfmt is re-enabled. The comment above it records that "
                 "WSL exposes binfmt_misc with a read-only status file, so the "
                 "service can never apply its rules and fails at boot.",
        "find": "          systemd.services.systemd-binfmt.enable = false;\n",
        "replace": "          systemd.services.systemd-binfmt.enable = true;\n",
    },
    {
        "id": "COR-7",
        "path": "modules/home/git.nix",
        "dimension": "correctness",
        "severity": "low",
        "claim": "allowedSignersFile lost both its mkDefault and its `~/.ssh/` "
                 "prefix, so it now resolves relative to whatever directory git "
                 "happens to run in and can no longer be overridden.",
        "find": "      gpg.ssh.allowedSignersFile = lib.mkDefault \"~/.ssh/allowed_signers\";\n",
        "replace": "      gpg.ssh.allowedSignersFile = \"allowed_signers\";\n",
    },
    {
        "id": "PERF-3",
        "path": "modules/home/default.nix",
        "dimension": "performance",
        "severity": "medium",
        "claim": "useGlobalPkgs is turned off, so home-manager instantiates its "
                 "own nixpkgs instead of sharing the system's. That is a second "
                 "evaluation of the whole package set and a second copy of every "
                 "package home-manager installs.",
        "find": "    useGlobalPkgs = true;\n",
        "replace": "    useGlobalPkgs = false;\n",
    },
]


# Locates each defect in the FINISHED file: for a deletion the marker is the anchor
# that remains. Separate from the edits so no line number is ever recorded from a
# half-applied file.
MARKERS: Dict[str, str] = {
    "SEC-1":  '                PasswordAuthentication = lib.mkForce true;',
    "SEC-2":  '                accept-flake-config = true;',
    "SEC-3":  '            security.sudo.execWheelOnly = lib.mkForce false;',
    "SEC-4":  '  networking.firewall.allowedTCPPorts = [',
    "COR-1":  '            system.stateVersion = lib.mkForce "24.11";',
    "COR-2":  '      prunePaths = [\n        "/tmp"\n',
    "PERF-1": '  environment.systemPackages = with pkgs; [',
    "PERF-2": '    download-buffer-size = 104857600;',
    "RD-1":   '            # Locale is pinned to the POSIX default; the clan-wide',
    "RD-2":   '  # programs.nh = {',
    "SEC-5":  '          hardware.graphics.enable = lib.mkForce true;',
    "SEC-6":  '      commit.gpgsign = lib.mkDefault false;',
    "SEC-7":  '              enable = false;',
    "SEC-8":  '    trusted-users = [ "@users" ];',
    "SEC-9":  '          acl = [ "readwrite #" ];',
    "SEC-10": '    useDHCP = true;',
    "COR-3":  '                options = lib.mkDefault "--delete-older-than 7";',
    "COR-4":  '        homeDirectory = "/home/otheruser";',
    "COR-5":  '            check-added-large-files.enable = false;',
    "COR-6":  '          systemd.services.systemd-binfmt.enable = true;',
    "COR-7":  '      gpg.ssh.allowedSignersFile = "allowed_signers";',
    "PERF-3": '    useGlobalPkgs = false;',
}


def line_of(text: str, needle: str) -> int:
    """1-indexed line number where `needle` starts."""
    return text[: text.index(needle)].count("\n") + 1


def apply_and_locate(injections: List[Dict[str, Any]], out: Path) -> List[Dict[str, Any]]:
    """Apply every injection, then locate each defect in the FINAL text.

    Line numbers cannot be recorded as the injections are applied: a later edit to
    the same file shifts every earlier line, so the manifest would point at the
    wrong place. Apply everything first, then find each defect's marker once.
    """
    texts: Dict[str, str] = {}
    for inj in injections:
        rel = inj["path"]
        target = out / rel
        if not target.exists():
            raise SystemExit(f"council corpus: {rel} missing from the base")
        text = texts.get(rel)
        if text is None:
            text = target.read_text(encoding="utf-8")
        occurrences = text.count(inj["find"])
        if occurrences != 1:
            raise SystemExit(
                f"council corpus: {inj['id']} matched {occurrences} times in {rel} "
                f"(expected exactly 1) — refusing to write a corpus whose manifest "
                f"does not match its contents")
        texts[rel] = text.replace(inj["find"], inj["replace"], 1)

    manifest: List[Dict[str, Any]] = []
    for inj in injections:
        rel = inj["path"]
        text = texts[rel]
        marker = MARKERS[inj["id"]]
        if text.count(marker) != 1:
            raise SystemExit(
                f"council corpus: {inj['id']} marker matched {text.count(marker)} times "
                f"in {rel} — the manifest cannot name a single line")
        manifest.append({
            "id": inj["id"],
            "path": rel,
            "line_range": str(line_of(text, marker)),
            "dimension": inj["dimension"],
            "severity": inj["severity"],
            "claim": inj["claim"],
        })

    for rel, text in texts.items():
        # newline="\n": the corpus must be LF-only, or the probes measure a
        # different file from the one the reviewers read.
        (out / rel).write_text(text, encoding="utf-8", newline="\n")
    return manifest


def check_separation(base: Path, out: Path) -> None:
    """Refuse an `--out` that overlaps `--base`.

    `out` is deleted before it is written, so `--base B --out B` removed the base
    and then died in copytree, and an `--out` that is an ancestor of the base took
    the base with it. Measured: `--base B --out V`, with V an unrelated populated
    directory, deleted V's contents and only then reported that B was the wrong
    base. The dangerous input is an ARGUMENT, not the invocation path, so the
    dispatch guard cannot cover this one.
    """
    if out == base:
        raise SystemExit(f"council corpus: --out and --base are the same path ({out})")
    # `out in base.parents` means out is an ANCESTOR of base, so writing out would
    # take the base with it; `base in out.parents` is the other direction.
    if out in base.parents:
        raise SystemExit(f"council corpus: --out {out} contains --base {base}")
    if base in out.parents:
        raise SystemExit(f"council corpus: --out {out} is inside --base {base}")


def check_targets(base: Path) -> None:
    """Validate every injection against the BASE, before anything is deleted.

    `apply_and_locate` raises the same errors on the copy, but by then `out` has
    already been removed and rewritten — so a wrong `--base` cost the caller their
    output directory and only then reported the mistake. Read-only, so it is safe
    to run first.
    """
    for inj in INJECTIONS:
        rel = inj["path"]
        target = base / rel
        if not target.exists():
            raise SystemExit(f"council corpus: {rel} missing from the base")
        occurrences = target.read_text(encoding="utf-8").count(inj["find"])
        if occurrences != 1:
            raise SystemExit(
                f"council corpus: {inj['id']} matched {occurrences} times in {rel} "
                f"(expected exactly 1) — refusing to write a corpus whose manifest "
                f"does not match its contents")


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="council corpus",
                                     description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--base", required=True, help="clean repository to copy")
    parser.add_argument("--out", required=True, help="where to write the corpus")
    parser.add_argument("--manifest", default=None,
                        help="manifest path (default: <out>/../injected-manifest.json)")
    args = parser.parse_args(argv)

    base, out = Path(args.base).resolve(), Path(args.out).resolve()
    if not base.is_dir():
        print(f"council corpus: {base} is not a directory", file=sys.stderr)
        return 2

    # Both checks run BEFORE the deletion: `out` is removed before it is written, so a
    # bad input would cost the caller data first and report the mistake second.
    check_separation(base, out)
    check_targets(base)

    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(base, out,
                    ignore=shutil.ignore_patterns(".git", ".review-council",
                                                  "__pycache__", ".direnv"))

    manifest = apply_and_locate(INJECTIONS, out)

    # Nix only sees a file git knows about: an uncommitted tree makes `nix eval` and
    # `nix flake check` fail and the probe layer report nothing. Never `git add -N`:
    # intent-to-add records empty blobs, which is a different failure.
    for cmd in (["git", "init", "-q"],
                ["git", "add", "-A"],
                ["git", "-c", "user.name=corpus", "-c", "user.email=corpus@localhost",
                 "commit", "-q", "-m", "corpus: injected defects"]):
        subprocess.run(cmd, cwd=out, capture_output=True, text=True, check=False)

    dest = Path(args.manifest) if args.manifest else out.parent / "injected-manifest.json"
    dest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")

    print(f"  corpus:   {out}")
    print(f"  manifest: {dest}")
    print(f"  injected {len(manifest)} defects:")
    by_dim: Dict[str, int] = {}
    by_sev: Dict[str, int] = {}
    for m in manifest:
        by_dim[m["dimension"]] = by_dim.get(m["dimension"], 0) + 1
        by_sev[m["severity"]] = by_sev.get(m["severity"], 0) + 1
        print(f"    {m['id']:8s} {m['dimension']:12s} {m['severity']:9s} "
              f"{m['path']}:{m['line_range']}")
    print(f"  by dimension: {by_dim}")
    print(f"  by severity:  {by_sev}")
    return 0


if __name__ == "__main__":
    # Not a program: reached through `council <verb>`. See council.py.
    from council import require_dispatch

    require_dispatch("corpus")
    raise SystemExit(main())
