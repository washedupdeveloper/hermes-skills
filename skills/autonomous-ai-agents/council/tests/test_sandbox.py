"""Sandbox: the mount plan, the archive handling, and the refusals.

Run standalone (no pytest needed):
    python tests/test_sandbox.py

What is testable without a user namespace is the part that decides what the container can see — the
mount set — plus the archive handling that was written twice by hand before this module existed.
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import tarfile
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

_spec = importlib.util.spec_from_file_location("sandbox", REPO / "scripts" / "sandbox.py")
sandbox = importlib.util.module_from_spec(_spec)
sys.modules["sandbox"] = sandbox
_spec.loader.exec_module(sandbox)


def make_image(tmp: Path, layers, config=None) -> Path:
    """A docker archive: manifest.json naming a config BLOB, plus layers in order."""
    image = tmp / "image.tar"
    names = []
    with tarfile.open(image, "w") as outer:
        for index, files in enumerate(layers):
            layer_path = tmp / f"layer{index}.tar"
            with tarfile.open(layer_path, "w") as layer:
                for name, data in files.items():
                    info = tarfile.TarInfo(name)
                    info.size = len(data)
                    layer.addfile(info, io.BytesIO(data))
            outer.add(layer_path, arcname=f"layer{index}/layer.tar")
            names.append(f"layer{index}/layer.tar")
        manifest = json.dumps([{"Config": "config.json", "Layers": names}]).encode()
        info = tarfile.TarInfo("manifest.json")
        info.size = len(manifest)
        outer.addfile(info, io.BytesIO(manifest))
        blob = json.dumps(config or {"config": {"Env": ["HOME=/home/council"]}}).encode()
        info = tarfile.TarInfo("config.json")
        info.size = len(blob)
        outer.addfile(info, io.BytesIO(blob))
    return image


# --- what the container may see ----------------------------------------------------


def test_only_what_was_asked_for_is_mounted():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        repo, home, hermes, seed = (root / n for n in ("repo", "home", "hermes", "seed"))
        for path in (repo, home, hermes, seed):
            path.mkdir()
        assert [m.target for m in sandbox.plan_mounts(repo, None, None, None)] == ["/repo"]
        every = sandbox.plan_mounts(repo, home, hermes, seed)
    assert [m.target for m in every] == ["/repo", "/home/council/.hermes", "/opt/hermes", "/seed"]
    assert [m.read_only for m in every] == [False, False, True, True]


def test_nothing_mounted_means_an_empty_list_not_a_default_repo():
    assert sandbox.plan_mounts(None, None, None, None) == []


def test_a_nix_hermes_brings_its_store_closure():
    """The wrapper execs a store path; mounting only `bin/` gives rc=127 inside the image."""
    with tempfile.TemporaryDirectory() as tmp:
        hermes = Path(tmp)
        (hermes / "bin").mkdir()
        (hermes / "bin" / "hermes").write_text("#!/bin/sh\n")
        original = sandbox.closure_paths
        sandbox.closure_paths = lambda binary: [Path("/nix/store/a-agent-env"),
                                                Path("/nix/store/b-python")]
        try:
            mounts = sandbox.plan_mounts(None, None, hermes, None)
        finally:
            sandbox.closure_paths = original
    assert [m.target for m in mounts] == ["/opt/hermes", "/nix/store/a-agent-env",
                                          "/nix/store/b-python"]
    assert all(m.read_only for m in mounts)


def test_a_non_nix_hermes_mounts_only_the_prefix():
    with tempfile.TemporaryDirectory() as tmp:
        hermes = Path(tmp)
        (hermes / "bin").mkdir()
        (hermes / "bin" / "hermes").write_text("#!/bin/sh\n")
        original = sandbox.shutil.which
        sandbox.shutil.which = lambda name: None
        try:
            assert sandbox.closure_paths(hermes / "bin" / "hermes") == []
        finally:
            sandbox.shutil.which = original


def test_mount_commands_target_the_rootfs_not_the_host():
    """`mount --bind src /repo` binds onto the HOST's /repo — the bug this test exists for."""
    mount = sandbox.Mount(Path("/host/repo"), "/repo", read_only=False)
    steps = mount.argv(Path("/cache/rootfs"))
    assert steps == [["mount", "--bind", "/host/repo", "/cache/rootfs/repo"]]


def test_a_read_only_mount_is_a_bind_then_a_remount():
    mount = sandbox.Mount(Path("/host/hermes"), "/opt/hermes", read_only=True)
    steps = mount.argv(Path("/cache/rootfs"))
    assert steps[0][:2] == ["mount", "--bind"]
    assert steps[1] == ["mount", "-o", "remount,bind,ro", "/cache/rootfs/opt/hermes"]


def test_a_bare_verb_is_dispatched_through_the_council_cli():
    """`doctor` is a verb, not a binary. Typed alone it resolved to an unrelated PATH binary."""
    got = sandbox.resolve_command(["doctor", "--repo", "/repo"], Path("/nonexistent"))
    assert got == ["python3", "/opt/review-council/scripts/council.py", "doctor",
                   "--repo", "/repo"]


def test_a_script_in_the_image_is_run_with_python_not_executed():
    got = sandbox.resolve_command(["/opt/review-council/scripts/council.py", "proofs",
                                   "--self-test"], Path("/nonexistent"))
    assert got[:2] == ["python3", "/opt/review-council/scripts/council.py"]


def test_an_executable_in_the_image_is_run_as_given():
    with tempfile.TemporaryDirectory() as tmp:
        rootfs = Path(tmp)
        binary = rootfs / "bin" / "council-entrypoint"
        binary.parent.mkdir(parents=True)
        binary.write_text("#!/bin/sh\n")
        binary.chmod(0o755)
        assert sandbox.resolve_command(["/bin/council-entrypoint", "/repo"], rootfs) == [
            "/bin/council-entrypoint", "/repo"]


def test_the_runtime_files_a_chroot_lacks_are_bound():
    """No /etc/resolv.conf in a dockerTools image; without it the reviewer dies on DNS."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        host = root / "host"
        (host / "etc").mkdir(parents=True)
        (host / "etc" / "resolv.conf").write_text("nameserver 1.1.1.1\n")
        rootfs = root / "root"
        (rootfs / "etc").mkdir(parents=True)
        (rootfs / "etc" / "resolv.conf").touch()          # present but empty — still useless
        pairs = sandbox.host_files_to_bind(rootfs, host)
    assert pairs == [(host / "etc" / "resolv.conf", rootfs / "etc" / "resolv.conf")]


def test_a_real_resolv_conf_is_left_alone():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        host = root / "host"
        (host / "etc").mkdir(parents=True)
        (host / "etc" / "resolv.conf").write_text("nameserver 9.9.9.9\n")
        rootfs = root / "root"
        (rootfs / "etc").mkdir(parents=True)
        (rootfs / "etc" / "resolv.conf").write_text("nameserver 1.1.1.1\n")
        assert sandbox.host_files_to_bind(rootfs, host) == []


def test_a_mounted_hermes_goes_on_path():
    """Otherwise `hermes -p council-generalist` is rc=127 after the probes have already run."""
    mounts = sandbox.plan_mounts(None, None, Path("/host/hermes"), None)
    env = sandbox.with_hermes_path({"PATH": "/usr/bin:/bin"}, mounts)
    assert env["PATH"] == "/opt/hermes/bin:/usr/bin:/bin"
    assert env["HERMES_BIN"] == "/opt/hermes/bin/hermes"


def test_the_path_is_extended_not_replaced():
    """A fixed PATH that replaces the caller's cannot find the project's own toolchain."""
    mounts = sandbox.plan_mounts(None, None, Path("/host/hermes"), None)
    env = sandbox.with_hermes_path({"PATH": "/run/current-system/sw/bin"}, mounts)
    assert env["PATH"].endswith(":/run/current-system/sw/bin")


def test_an_empty_path_does_not_produce_a_trailing_colon():
    """The property that matters is no empty segment — not that the ambient PATH is empty."""
    mounts = sandbox.plan_mounts(None, None, Path("/host/hermes"), None)
    path = sandbox.with_hermes_path({}, mounts)["PATH"]
    assert path.startswith("/opt/hermes/bin")
    assert not path.endswith(":") and "::" not in path


def test_without_a_hermes_mount_the_path_is_untouched():
    mounts = sandbox.plan_mounts(Path("/host/repo"), None, None, None)
    env = sandbox.with_hermes_path({"PATH": "/usr/bin:/bin"}, mounts)
    assert env == {"PATH": "/usr/bin:/bin"}


def test_no_command_at_all_is_the_entrypoint():
    assert sandbox.resolve_command([], Path("/x")) == [sandbox.ENTRYPOINT]


def test_the_default_command_is_the_image_entrypoint():
    plan = sandbox.Plan(image=Path("/x.tar"), rootfs=Path("/r"), command=[sandbox.ENTRYPOINT])
    assert plan.command == ["/bin/council-entrypoint"]


def test_the_rootfs_cache_key_changes_when_the_image_does():
    with tempfile.TemporaryDirectory() as tmp:
        image = Path(tmp) / "image.tar"
        image.write_bytes(b"a" * 10)
        first = sandbox.rootfs_key(image)
        os.utime(image, (0, 0))
        second = sandbox.rootfs_key(image)
        image.write_bytes(b"a" * 20)
        third = sandbox.rootfs_key(image)
    assert first != second and second != third


def test_the_cache_directory_honours_an_override():
    with tempfile.TemporaryDirectory() as tmp:
        image = Path(tmp) / "image.tar"
        image.write_bytes(b"x")
        previous = os.environ.get("COUNCIL_SANDBOX_ROOT")
        os.environ["COUNCIL_SANDBOX_ROOT"] = tmp
        try:
            where = sandbox.cache_dir(image)
        finally:
            if previous is None:
                os.environ.pop("COUNCIL_SANDBOX_ROOT")
            else:
                os.environ["COUNCIL_SANDBOX_ROOT"] = previous
    assert str(where).startswith(tmp) and where.parent == Path(tmp)


# --- the archive -------------------------------------------------------------------


def test_extraction_lays_layers_down_in_order_and_honours_whiteouts():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        image = make_image(root, [
            {"etc/keep": b"kept", "etc/remove": b"gone", "bin/tool": b"#!/bin/sh\n"},
            {"etc/.wh.remove": b"", "etc/added": b"new"},
        ])
        out = root / "rootfs"
        sandbox.extract(image, out)
        # inside the `with`: the tree is the thing under test, and a TemporaryDirectory that has
        # already been cleaned up turns every assertion into a FileNotFoundError
        assert (out / "etc" / "keep").read_text() == "kept"
        assert not (out / "etc" / "remove").exists()
        assert (out / "etc" / "added").read_text() == "new"
        assert (out / "bin" / "tool").exists()


def test_absolute_paths_in_a_layer_are_normalised_not_refused():
    """dockerTools writes `/nix/store/...`; refusing the archive it ships would be absurd."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        image = make_image(root, [{"/nix/store/abc-file": b"payload"}])
        out = root / "rootfs"
        sandbox.extract(image, out)
        assert (out / "nix" / "store" / "abc-file").read_text() == "payload"


def test_a_path_escaping_the_rootfs_is_refused():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        image = make_image(root, [{"../escaped": b"nope"}])
        try:
            sandbox.extract(image, root / "rootfs")
        except SystemExit as exc:
            assert "unsafe" in str(exc)
        else:
            raise AssertionError("a traversal path was extracted")
        assert not (root.parent / "escaped").exists()


def test_the_image_env_comes_from_the_config_blob_not_the_manifest():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        image = make_image(root, [{"bin/x": b""}],
                           config={"config": {"Env": ["HOME=/home/council",
                                                      "FONTCONFIG_FILE=/nix/store/f.conf"]}})
        env = sandbox.image_env(image)
    assert env == {"HOME": "/home/council", "FONTCONFIG_FILE": "/nix/store/f.conf"}


def test_a_flat_config_is_accepted_too():
    """OCI configs carry their Env at the top level; docker images nest it under `config`."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        image = make_image(root, [{"bin/x": b""}], config={"Env": ["HOME=/home/council"]})
        assert sandbox.image_env(image) == {"HOME": "/home/council"}


# --- refusals -----------------------------------------------------------------------


def test_without_an_image_or_nix_it_says_so_instead_of_guessing():
    previous = os.environ.get("PATH", "")
    os.environ["PATH"] = ""
    try:
        code = sandbox.main([])
    finally:
        os.environ["PATH"] = previous
    assert code == 2


def test_a_missing_image_file_is_reported():
    with tempfile.TemporaryDirectory() as tmp:
        assert sandbox.main(["--image", str(Path(tmp) / "absent.tar")]) == 2


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok   {name}")
            except AssertionError as exc:
                failures += 1
                print(f"FAIL {name}: {exc}")
    raise SystemExit(1 if failures else 0)
