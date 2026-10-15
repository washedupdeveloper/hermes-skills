"""Tests for the corpus builder (scripts/inject_defects.py).

Run standalone (no pytest needed):
    python tests/test_inject_defects.py

The injector is the only source of ground truth for the ablation, so a silent
failure here would produce a corpus whose manifest does not describe it — and
every recall number computed from that corpus would be wrong. These tests pin
the two ways that can happen: an edit that does not apply exactly once, and a
manifest line that points somewhere other than the defect.
"""
from __future__ import annotations

import importlib.util
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS))

_spec = importlib.util.spec_from_file_location("inject_defects",
                                              SCRIPTS / "inject_defects.py")
inject = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(inject)

BASE_SYSTEM = "modules/clanServices/base-system/default.nix"
host = "machines/host/configuration.nix"


# --- the output path is deleted before it is written --------------------------
#
# `--out` is rmtree'd, so an `--out` that overlaps `--base` destroys the base, and
# an `--out` that is somebody else's directory destroys that. Reported by the
# council on this repository, with the damage reproduced: `--base B --out B` left
# B gone, and `--base B --out V` emptied V and only then said B was the wrong base.

def test_out_equal_to_base_is_refused():
    with tempfile.TemporaryDirectory() as td:
        base = Path(td) / "base"
        base.mkdir()
        try:
            inject.check_separation(base, base)
        except SystemExit as exc:
            assert "same path" in str(exc)
        else:
            raise AssertionError("--out == --base was accepted")


def test_out_containing_base_is_refused():
    with tempfile.TemporaryDirectory() as td:
        base = Path(td) / "parent" / "base"
        base.mkdir(parents=True)
        try:
            inject.check_separation(base, Path(td) / "parent")
        except SystemExit as exc:
            assert "contains --base" in str(exc)
        else:
            raise AssertionError("an --out containing --base was accepted")


def test_out_inside_base_is_refused():
    with tempfile.TemporaryDirectory() as td:
        base = Path(td) / "base"
        base.mkdir()
        try:
            inject.check_separation(base, base / "corpus")
        except SystemExit as exc:
            assert "inside --base" in str(exc)
        else:
            raise AssertionError("an --out inside --base was accepted")


def test_separate_paths_are_allowed():
    with tempfile.TemporaryDirectory() as td:
        base = Path(td) / "base"
        base.mkdir()
        inject.check_separation(base, Path(td) / "corpus")  # must not raise


def test_a_bad_base_is_reported_before_anything_is_deleted():
    """The validation used to run on the COPY, so a wrong --base cost the caller
    their output directory and only then reported the mistake."""
    with tempfile.TemporaryDirectory() as td:
        base = Path(td) / "base"
        base.mkdir()          # empty: every injection target is missing
        try:
            inject.check_targets(base)
        except SystemExit as exc:
            assert "missing from the base" in str(exc)
        else:
            raise AssertionError("an unusable base was accepted")


def test_the_main_path_validates_before_deleting(tmp_path):
    """End to end: a populated --out survives a --base that cannot be used."""
    base = tmp_path / "base"
    base.mkdir()
    out = tmp_path / "out"
    out.mkdir()
    precious = out / "PRECIOUS.txt"
    precious.write_text("do not delete me\n", encoding="utf-8")

    # check_targets raises SystemExit, which is how the CLI reports a refusal.
    try:
        rc = inject.main(["--base", str(base), "--out", str(out)])
    except SystemExit as exc:
        rc = str(exc)
    assert rc, "an unusable base was accepted"
    assert precious.is_file(), "the output directory was emptied before the base was checked"
    assert precious.read_text(encoding="utf-8") == "do not delete me\n"


def test_the_main_path_refuses_out_equal_to_base(tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    marker = base / "PRECIOUS.txt"
    marker.write_text("do not delete me\n", encoding="utf-8")

    try:
        inject.main(["--base", str(base), "--out", str(base)])
    except SystemExit:
        pass
    assert marker.is_file(), "--base was destroyed by an --out pointing at it"


WSL = "modules/clanServices/wsl/default.nix"
GIT = "modules/home/git.nix"
GIT_HOOKS = "modules/flake/git-hooks.nix"
HOME_DEFAULT = "modules/home/default.nix"

# A fixture carrying exactly the strings the injections look for, once each. If an
# injection gains an anchor that is missing here, apply_and_locate aborts and the
# test fails -- which is the point: the fixture cannot silently drift from the
# injections it exists to exercise.
FIXTURE = {
    BASE_SYSTEM: (
        "{\n"
        "  roles.default = {\n"
        "    interface =\n"
        "      { lib, ... }:\n"
        "      {\n"
        "        options = { };\n"
        "      };\n"
        "    perInstance =\n"
        "      { config, ... }:\n"
        "      {\n"
        "            i18n = {\n"
        "              defaultLocale = lib.mkDefault \"en_DK.UTF-8\";\n"
        "            };\n"
        "        services.openssh = {\n"
        "          settings = {\n"
        "                PasswordAuthentication = false;\n"
        "                KbdInteractiveAuthentication = false;\n"
        "          };\n"
        "        };\n"
        "            users.mutableUsers = lib.mkDefault false;\n"
        "            security.sudo.execWheelOnly = lib.mkDefault true;\n"
        "            nix = {\n"
        "              gc = {\n"
        "                options = lib.mkDefault \"--delete-older-than 7d\";\n"
        "              };\n"
        "              settings = {\n"
        "                experimental-features = [ \"pipe-operators\" ];\n"
        "                auto-optimise-store = lib.mkDefault true;\n"
        "              };\n"
        "            };\n"
        "      };\n"
        "  };\n"
        "}\n"
    ),
    host: (
        "{\n"
        "  config,\n"
        "  lib,\n"
        "  pkgs,\n"
        "  username,\n"
        "  ...\n"
        "}:\n"
        "{\n"
        "  networking = {\n"
        "    hostName = \"host\";\n"
        "    useDHCP = false;\n"
        "  };\n"
        "\n"
        "  nixpkgs.hostPlatform = \"x86_64-linux\";\n"
        "\n"
        "  programs.nix-ld.enable = true;\n"
        "\n"
        "  nix.settings = {\n"
        "    max-jobs = 6;\n"
        "    cores = 2;\n"
        "  };\n"
        "\n"
        "  programs.nh = {\n"
        "    enable = true;\n"
        "    clean.enable = true;\n"
        "    clean.extraArgs = \"--keep-since 7d --keep 4\";\n"
        "    flake = \"/home/${username}/projects/example-infra\";\n"
        "  };\n"
        "\n"
        "  networking.firewall.interfaces.eth0.allowedTCPPorts = [ 1883 ];\n"
        "  services.locate = {\n"
        "      prunePaths = [\n"
        "        \"/mnt\"\n"
        "        \"/tmp\"\n"
        "    ];\n"
        "  };\n"
        "  services.mosquitto = {\n"
        "      listeners = [\n"
        "        {\n"
        "          acl = [ \"readwrite plants/#\" ];\n"
        "        }\n"
        "      ];\n"
        "  };\n"
        "}\n"
    ),
    WSL: (
        "{\n"
        "  roles.default = {\n"
        "    perInstance = _: {\n"
        "      nixosModule =\n"
        "        {\n"
        "          pkgs,\n"
        "          lib,\n"
        "          ...\n"
        "        }:\n"
        "        {\n"
        "          systemd.services.systemd-binfmt.enable = false;\n"
        "          hardware.graphics.enable = lib.mkForce false;\n"
        "        };\n"
        "    };\n"
        "  };\n"
        "}\n"
    ),
    GIT: (
        "{\n"
        "  lib,\n"
        "  identity,\n"
        "  gitSigningKey,\n"
        "  ...\n"
        "}:\n"
        "{\n"
        "  programs.git = {\n"
        "    settings = {\n"
        "      commit.gpgsign = lib.mkDefault true;\n"
        "      gpg.ssh.allowedSignersFile = lib.mkDefault \"~/.ssh/allowed_signers\";\n"
        "    };\n"
        "  };\n"
        "}\n"
    ),
    GIT_HOOKS: (
        "{ inputs, ... }:\n"
        "{\n"
        "  perSystem =\n"
        "    { pkgs, ... }:\n"
        "    {\n"
        "      pre-commit = {\n"
        "        settings = {\n"
        "          hooks = {\n"
        "            flake-check = {\n"
        "              enable = true;\n"
        "              stages = [ \"pre-push\" ];\n"
        "            };\n"
        "            check-added-large-files.enable = true;\n"
        "            gitleaks = {\n"
        "              enable = true;\n"
        "            };\n"
        "          };\n"
        "        };\n"
        "      };\n"
        "    };\n"
        "}\n"
    ),
    HOME_DEFAULT: (
        "{\n"
        "  config,\n"
        "  lib,\n"
        "  username,\n"
        "  ...\n"
        "}:\n"
        "{\n"
        "  home-manager = {\n"
        "    useGlobalPkgs = true;\n"
        "    users.${username} = {\n"
        "      home = {\n"
        "        homeDirectory = \"/home/${username}\";\n"
        "        inherit (config.system) stateVersion;\n"
        "      };\n"
        "    };\n"
        "  };\n"
        "}\n"
    ),
}


def build_fixture(root: Path) -> None:
    for rel, text in FIXTURE.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="\n")


def make_base(tmp: Path) -> Path:
    base = tmp / "base"
    build_fixture(base)
    return base


# --- the injections themselves ----------------------------------------------

def test_every_injection_has_a_marker():
    """A missing marker means that defect can never be located in the manifest."""
    for inj in inject.INJECTIONS:
        assert inj["id"] in inject.MARKERS, inj["id"]


def test_ids_are_unique():
    ids = [inj["id"] for inj in inject.INJECTIONS]
    assert len(ids) == len(set(ids)), ids


def test_every_injection_is_well_formed():
    for inj in inject.INJECTIONS:
        for key in ("id", "path", "dimension", "severity", "claim", "find", "replace"):
            assert inj.get(key), f"{inj['id']} is missing {key}"
        assert inj["find"] != inj["replace"], inj["id"]
        assert inj["severity"] in {"info", "low", "medium", "high", "critical"}, inj["id"]
        assert inj["dimension"] in {"security", "correctness", "readability",
                                    "architecture", "performance"}, inj["id"]


def test_the_injections_span_every_dimension_and_a_range_of_severities():
    """A corpus of one kind of defect at one severity would not separate the arms."""
    dims = {inj["dimension"] for inj in inject.INJECTIONS}
    sevs = {inj["severity"] for inj in inject.INJECTIONS}
    assert dims == {"security", "correctness", "readability", "performance"}, dims
    assert {"critical", "high", "medium", "low"} <= sevs, sevs


def test_a_silent_defect_uses_explicit_priority():
    """Adding a plain definition where one already exists is a conflict ERROR, not a
    silent defect. Anything meant to override an existing option must say so."""
    overriding = [inj for inj in inject.INJECTIONS
                  if inj["id"] in {"SEC-1", "SEC-3", "COR-1"}]
    assert overriding, "expected the overriding defects to still exist"
    for inj in overriding:
        assert "mkForce" in inj["replace"], (
            f"{inj['id']} overrides an existing option without mkForce — in a NixOS "
            "module system that is a conflict error, so the defect would be caught "
            "by evaluation rather than by reasoning")


# --- applying and locating --------------------------------------------------

def test_apply_and_locate_records_the_line_of_the_defect():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        base = make_base(tmp)
        out = tmp / "corpus"
        shutil.copytree(base, out)

        manifest = inject.apply_and_locate(inject.INJECTIONS, out)
        assert len(manifest) == len(inject.INJECTIONS)

        for entry in manifest:
            lines = (out / entry["path"]).read_text().splitlines()
            n = int(entry["line_range"])
            assert 1 <= n <= len(lines), f"{entry['id']} line {n} out of range"
            assert inject.MARKERS[entry["id"]].splitlines()[0].strip() in lines[n - 1], (
                f"{entry['id']} points at {lines[n-1]!r}, not the defect")


def test_line_numbers_survive_later_edits_to_the_same_file():
    """The first bug this caught: recording a line as edits are applied, so a later
    edit to the same file shifted every earlier line and the manifest lied."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        base = make_base(tmp)
        out = tmp / "corpus"
        shutil.copytree(base, out)

        manifest = inject.apply_and_locate(inject.INJECTIONS, out)
        per_file = {}
        for entry in manifest:
            per_file.setdefault(entry["path"], []).append(entry)
        multi = {p: e for p, e in per_file.items() if len(e) > 1}
        assert multi, "fixture must exercise more than one injection per file"

        for path, entries in multi.items():
            text = (out / path).read_text()
            lines = text.splitlines()
            for entry in entries:
                n = int(entry["line_range"])
                assert inject.MARKERS[entry["id"]].splitlines()[0].strip() in lines[n - 1], (
                    f"{entry['id']} in {path} points at the wrong line")


def test_a_find_string_that_matches_twice_aborts():
    """A silent mis-application would mean a manifest claiming a defect that is not
    where it says, or is not there at all."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        base = make_base(tmp)
        target = base / host
        target.write_text(target.read_text() + "  programs.nix-ld.enable = true;\n",
                          encoding="utf-8", newline="\n")
        out = tmp / "corpus"
        shutil.copytree(base, out)

        try:
            inject.apply_and_locate(inject.INJECTIONS, out)
        except SystemExit as exc:
            assert "matched 2 times" in str(exc), exc
        else:
            raise AssertionError("a duplicated find string must abort, not guess")


def test_a_missing_file_aborts():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        out = tmp / "corpus"
        out.mkdir()
        try:
            inject.apply_and_locate(inject.INJECTIONS, out)
        except SystemExit as exc:
            assert "missing from the base" in str(exc), exc
        else:
            raise AssertionError("a missing file must abort")


def test_the_written_files_are_lf_only():
    """The corpus is reviewed on Linux; a CRLF file measures differently from the
    one the reviewers read."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        base = make_base(tmp)
        out = tmp / "corpus"
        shutil.copytree(base, out)
        inject.apply_and_locate(inject.INJECTIONS, out)
        for rel in FIXTURE:
            assert b"\r\n" not in (out / rel).read_bytes(), rel


def test_manifest_entries_carry_the_claim_and_severity():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        base = make_base(tmp)
        out = tmp / "corpus"
        shutil.copytree(base, out)
        manifest = inject.apply_and_locate(inject.INJECTIONS, out)
        for entry in manifest:
            assert entry["claim"].strip(), entry
            assert entry["severity"] in {"info", "low", "medium", "high", "critical"}
            assert entry["path"] in FIXTURE, entry["path"]


def test_every_injection_targets_a_file_the_fixture_provides():
    """The fixture is what lets these tests run without the real repository. If an
    injection targets a file it does not carry, apply_and_locate aborts and the
    whole suite fails -- so catch it here with a message that says why."""
    missing = sorted({inj["path"] for inj in inject.INJECTIONS} - set(FIXTURE))
    assert not missing, (
        f"injections target files the fixture does not provide: {missing}. "
        "Add them to FIXTURE with each anchor present exactly once.")


def test_the_injections_include_the_cross_file_class():
    """A corpus of comment-contradicting defects is findable by reading one file,
    and a single generalist pass finds most of them. The class that actually
    separates the arms is the silent one: a plain definition beating another
    module's mkDefault, or a list option merging where a restriction was meant.
    Those must be present or the experiment cannot discriminate."""
    ids = {inj["id"] for inj in inject.INJECTIONS}
    assert "SEC-8" in ids, "the list-merge defect (trusted-users) is missing"
    silent = [inj for inj in inject.INJECTIONS if inj["id"] == "SEC-8"][0]
    assert "MERGE" in silent["claim"], silent["claim"]


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok    {name}")
            except AssertionError as exc:
                failures += 1
                print(f"  FAIL  {name}: {exc}")
    print(f"\n{failures} failure(s)")
    sys.exit(1 if failures else 0)
