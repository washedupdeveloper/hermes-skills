"""Run the council inside its own image, on a host that has no container runtime.

`docker run` needs a daemon, a setuid helper or `newuidmap`; a NixOS box with none of them can still
run the image the image format already describes. This module unpacks the OCI archive the flake
builds, gives the rootfs what a real runtime gives it (a tmpfs `/dev` with the nodes chromium opens,
`/proc`, `/dev/shm`), bind-mounts the repository, the Hermes mount and a credentials seed, and
executes a command in there.

Why this exists rather than "just use docker": on Windows the documented path IS the container, and
on this class of Linux host there is no runtime to run it with. A reviewer that cannot be exercised
on the machine a user has is not runnable.

The user-namespace root mapping is deliberate: `unshare -r` maps container root to *the invoking
user*, so artefacts written into the bind-mounted repository are owned by the user on the host, not
by an unmapped root that shows up as `nobody`.

Not a security boundary. It is a run environment: the mount set is explicit, nothing is guessed, and
anything not mounted is not reachable from inside.

CLI (dev verb — it needs `unshare`, which the image itself does not have privileges for):

    council sandbox                       # the image's entrypoint, no arguments
    council sandbox --repo . -- doctor --repo /repo
    council sandbox --repo . --home ~/.hermes -- /bin/council-entrypoint /repo
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
INSIDE_VAR = "COUNCIL_SANDBOX_INSIDE"
DEFAULT_CACHE = "council-sandbox"
ENTRYPOINT = "/bin/council-entrypoint"
# The nodes a headless browser opens before it will start. Without them chromium aborts with
# SIGABRT/SIGTRAP and every dom claim is unrunnable — measured, not assumed.
DEV_NODES = ("null", "zero", "full", "random", "urandom", "tty")


@dataclass(frozen=True)
class Mount:
    source: Path
    target: str
    read_only: bool = False

    def argv(self, root: Path) -> List[List[str]]:
        """Mount commands against the unpacked rootfs — never the host's absolute `/repo`.

        `mount --bind src /repo` would bind onto the HOST's /repo (and fail when it does not
        exist); the target has to be `<rootfs>/repo`. Read-only needs a second call: `mount -o
        remount,bind,ro` after the bind.
        """
        target = root / self.target.lstrip("/")
        steps = [["mount", "--bind", str(self.source), str(target)]]
        if self.read_only:
            steps.append(["mount", "-o", "remount,bind,ro", str(target)])
        return steps


@dataclass
class Plan:
    image: Path
    rootfs: Path
    mounts: List[Mount] = field(default_factory=list)
    command: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    keep: bool = False
    fresh: bool = False


# --- what to mount, and where ----------------------------------------------------


def closure_paths(binary: Path) -> List[Path]:
    """The store closure of a nix-wrapped binary, or [] when this is not a nix installation.

    A nix `hermes` is a wrapper that execs `/nix/store/<hash>-hermes-agent-env/bin/hermes`. Mounting
    only its `bin/` gives an image in which the wrapper runs and the binary it names does not exist —
    rc=127, after the probes have already been paid for. Measured on this host: 543 paths.
    """
    if shutil.which("nix") is None:
        return []
    result = subprocess.run(["nix", "path-info", "-r", str(binary)],
                            capture_output=True, text=True)
    if result.returncode != 0:
        return []
    return [Path(line.strip()) for line in result.stdout.splitlines()
            if line.strip().startswith("/nix/store/")]


def plan_mounts(repo: Optional[Path], home: Optional[Path], hermes: Optional[Path],
                seed: Optional[Path]) -> List[Mount]:
    """The mount set, explicit and ordered. Nothing is mounted that was not asked for."""
    mounts: List[Mount] = []
    if repo is not None:
        mounts.append(Mount(repo, "/repo"))
    if home is not None:
        mounts.append(Mount(home, "/home/council/.hermes"))
    if hermes is not None:
        # read-only: the council never writes to the Hermes it borrows
        mounts.append(Mount(hermes, "/opt/hermes", read_only=True))
        if (hermes / "bin" / "hermes").exists():
            for path in closure_paths((hermes / "bin" / "hermes").resolve()):
                mounts.append(Mount(path, str(path), read_only=True))
    if seed is not None:
        mounts.append(Mount(seed, "/seed", read_only=True))
    return mounts


def rootfs_key(image: Path) -> str:
    """A cache key that changes when the image does — size and mtime, not a guess."""
    try:
        stat = image.stat()
        material = f"{image.resolve()}:{stat.st_size}:{int(stat.st_mtime)}"
    except OSError:
        material = str(image)
    return hashlib.sha256(material.encode()).hexdigest()[:16]


def cache_dir(image: Path, base: Optional[Path] = None) -> Path:
    root = base or Path(os.environ.get("COUNCIL_SANDBOX_ROOT")
                        or (Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
                            / DEFAULT_CACHE))
    return root / rootfs_key(image)


# --- unpacking the image ----------------------------------------------------------


def _safe_members(tar: tarfile.TarFile):
    for member in tar.getmembers():
        name = member.name
        if ".." in Path(name).parts:
            raise SystemExit(f"refusing to extract an unsafe path: {name}")
        if name.startswith("/"):
            member.name = name.lstrip("/")
        yield member


def extract(image: Path, dest: Path) -> Path:
    """Unpack a docker-archive tarball into a rootfs, honouring whiteouts and layer order."""
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(image) as outer:
        manifest = None
        for member in _safe_members(outer):
            outer.extract(member, dest, filter="fully_trusted")
            if member.name in ("manifest.json", "./manifest.json"):
                manifest = json.loads((dest / member.name).read_text())
    if not manifest:
        raise SystemExit(f"{image} carries no manifest.json — not a docker archive")
    for layer_name in manifest[0]["Layers"]:
        layer = dest / layer_name
        if not layer.is_file():
            raise SystemExit(f"missing layer {layer_name}")
        with tarfile.open(layer) as tar:
            for member in list(_safe_members(tar)):
                base = os.path.basename(member.name.rstrip("/"))
                parent = os.path.dirname(member.name)
                if base == ".wh..wh..opq":
                    target = dest / parent
                    if target.is_dir():
                        for child in target.iterdir():
                            shutil.rmtree(child) if child.is_dir() else child.unlink()
                    continue
                if base.startswith(".wh."):
                    target = dest / parent / base[4:]
                    if target.is_dir():
                        shutil.rmtree(target)
                    elif target.exists() or target.is_symlink():
                        target.unlink()
                    continue
                tar.extract(member, dest, numeric_owner=True, filter="fully_trusted")
    return dest


def image_env(image: Path) -> Dict[str, str]:
    """The image's own Env. `manifest.json` names a config BLOB; it does not carry it inline."""
    with tarfile.open(image) as tar:
        manifest_file = tar.extractfile("manifest.json")
        if manifest_file is None:
            raise SystemExit("manifest.json is not a regular file")
        manifest = json.loads(manifest_file.read())[0]
        name = manifest["Config"]
        if not isinstance(name, str):
            raise SystemExit("manifest Config is not a filename")
        config_file = tar.extractfile(name)
        if config_file is None:
            raise SystemExit(f"{name} is not a regular file")
        config = json.loads(config_file.read())
    if "config" in config and isinstance(config["config"], dict):
        config = config["config"]
    env: Dict[str, str] = {}
    for item in config.get("Env") or []:
        key, _, value = item.partition("=")
        env[key] = value
    return env


# --- inside the namespace ---------------------------------------------------------


def _mount(argv: List[str]) -> None:
    result = subprocess.run(argv, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"{' '.join(argv)} failed: {result.stderr.strip()}")


def resolve_command(command: List[str], rootfs: Path) -> List[str]:
    """Turn what the user typed into an argv the image can execute.

    Three shapes, because all three are natural to type and only one of them is an executable:

        `/bin/council-entrypoint /repo`   an executable in the image        -> as given
        `/opt/.../council.py doctor`      a script, not marked executable  -> python3 <script>
        `doctor --repo /repo`             a council verb                   -> python3 .../council.py doctor

    Measured the hard way: `doctor` alone resolved through PATH to an unrelated binary named
    `doctor`, and a `.py` passed straight to execvpe failed with EACCES.
    """
    if not command:
        return [ENTRYPOINT]
    head = command[0]
    if head.startswith("/"):
        target = rootfs / head.lstrip("/")
        if os.access(target, os.X_OK) and not head.endswith(".py"):
            return command
        return ["python3", *command]
    if head.endswith(".py"):
        return ["python3", head, *command[1:]]
    return ["python3", "/opt/review-council/scripts/council.py", *command]


def with_hermes_path(env: Dict[str, str], mounts: List[Mount]) -> Dict[str, str]:
    """Put the mounted Hermes on PATH, the way the image's entrypoint does.

    The reviewers are started as `hermes -p <profile>`, resolved by name, so a mounted
    /opt/hermes that is not on PATH is a review that dies with rc=127 after paying for its probes.
    """
    if any(mount.target == "/opt/hermes" for mount in mounts):
        # Extend whatever PATH the caller has; a fixed list here would be a PATH that cannot find
        # the project's own toolchain (tests/test_portability.py fails the gate for exactly that).
        current = env.get("PATH") or os.environ.get("PATH") or ""
        prefix = "/opt/hermes/bin"
        if prefix not in current.split(":"):
            env = dict(env, PATH=prefix + (":" + current if current else ""))
        env.setdefault("HERMES_BIN", "/opt/hermes/bin/hermes")
    return env


def host_files_to_bind(rootfs: Path,
                       host_root: Path = Path("/")) -> List[Tuple[Path, Path]]:
    """The host files a container runtime bind-mounts for you, if the image has none.

    Measured: without `/etc/resolv.conf` the reviewer turn reaches the provider and dies with
    `APIConnectionError` after three retries — a DNS failure that looks exactly like being offline.
    `/etc/hosts` is bound alongside it for the same reason, and the CA bundle is the same class of
    omission (TLS failures read as "can't reach the model provider").

    `host_root` exists so the decision can be tested without depending on what the build machine
    happens to have in /etc — the nix build sandbox has no resolv.conf, which is how a test that
    read the real one passed on a workstation and failed in the gate.
    """
    names = ("etc/resolv.conf", "etc/hosts", "etc/ssl/certs/ca-certificates.crt")
    pairs: List[Tuple[Path, Path]] = []
    for name in names:
        source = host_root / name
        if not source.exists():
            continue
        target = rootfs / name
        try:
            present = target.exists() and target.stat().st_size > 0
        except OSError:
            present = False
        if not present:
            pairs.append((source, target))
    return pairs


def prepare(rootfs: Path, plan: Plan) -> None:
    """Give the rootfs what runc gives a container. Every step is required and named."""
    dev = rootfs / "dev"
    proc = rootfs / "proc"
    for path in (dev, proc, dev / "pts", dev / "shm"):
        path.mkdir(parents=True, exist_ok=True)
    if dev.is_dir() and not os.path.ismount(dev):
        _mount(["mount", "-t", "tmpfs", "tmpfs", str(dev)])
        for name in DEV_NODES:
            node = dev / name
            node.touch(exist_ok=True)
            _mount(["mount", "--bind", f"/dev/{name}", str(node)])
        (dev / "pts").mkdir(exist_ok=True)
        (dev / "shm").mkdir(exist_ok=True)
        os.chmod(dev / "shm", 0o1777)
        _mount(["mount", "-t", "devpts", "devpts", str(dev / "pts")])
    if not os.path.ismount(proc):
        _mount(["mount", "-t", "proc", "proc", str(proc)])
    for source, target in host_files_to_bind(rootfs):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch(exist_ok=True)
        _mount(["mount", "--bind", str(source), str(target)])
    for mount in plan.mounts:
        target = rootfs / mount.target.lstrip("/")
        # A store closure contains FILES as well as directories (`wildmidi.cfg` is a store path),
        # so the target is created to match the source rather than assumed to be a directory.
        if mount.source.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.touch(exist_ok=True)
        for step in mount.argv(rootfs):
            _mount(step)


# No teardown exists on purpose: every mount lives in this process's mount namespace, and the
# namespace dies with the process. Only the unpacked rootfs survives, which is the cache.


# --- the two halves ---------------------------------------------------------------


def outer(args: argparse.Namespace) -> int:
    """Resolve the image, then re-exec inside a user namespace that maps root to this user."""
    image = Path(args.image).expanduser().resolve() if args.image not in (None, "auto") else None
    if image is None:
        if shutil.which("nix") is None:
            print("sandbox: no image given and nix is not installed — pass --image <tarball>",
                  file=sys.stderr)
            return 2
        built = subprocess.run(
            ["nix", "build", "--no-link", "--print-out-paths", f"{ROOT}#container"],
            capture_output=True, text=True)
        if built.returncode != 0:
            print(f"sandbox: building the image failed:\n{built.stderr.strip()}", file=sys.stderr)
            return 2
        image = Path(built.stdout.strip().splitlines()[-1]).resolve()
    if not image.is_file():
        print(f"sandbox: no such image: {image}", file=sys.stderr)
        return 2
    if shutil.which("unshare") is None:
        print("sandbox: `unshare` is not installed — this host cannot create a user namespace, so "
              "the image cannot be entered. Use docker, or install util-linux.", file=sys.stderr)
        return 2

    rootfs = cache_dir(image, Path(args.rootfs).expanduser() if args.rootfs else None)
    inner = [sys.executable, str(Path(__file__).resolve()), "--inside",
             "--image", str(image), "--rootfs", str(rootfs)]
    if args.keep:
        inner.append("--keep")
    if args.fresh:
        inner.append("--fresh")
    for flag, value in (("--repo", args.repo), ("--home", args.home),
                        ("--hermes", args.hermes), ("--seed", args.seed)):
        if value:
            inner += [flag, str(Path(value).expanduser().resolve())]
    if args.command:
        inner += ["--", *args.command]

    if args.fresh and rootfs.exists():
        shutil.rmtree(rootfs, ignore_errors=True)
    env = dict(os.environ, **{INSIDE_VAR: "1"})
    return subprocess.run(["unshare", "-r", "-m", "-p", "-f", "--", *inner], env=env).returncode


def inner(args: argparse.Namespace) -> int:
    """Extract if needed, prepare the namespace, chroot, exec. Nothing is left implicit."""
    image = Path(args.image)
    rootfs = Path(args.rootfs)
    if not (rootfs / "bin").is_dir():
        print(f"  unpacking {image.name} into {rootfs} (first run)", file=sys.stderr)
        extract(image, rootfs)
    mounts = plan_mounts(
        Path(args.repo) if args.repo else None,
        Path(args.home) if args.home else None,
        Path(args.hermes) if args.hermes else None,
        Path(args.seed) if args.seed else None,
    )
    command = resolve_command(args.command or [], rootfs)
    plan = Plan(image=image, rootfs=rootfs, mounts=mounts, command=command,
                env=image_env(image), keep=args.keep, fresh=args.fresh)
    prepare(rootfs, plan)
    env = dict(os.environ)
    env.update(plan.env)
    env.setdefault("HOME", "/home/council")
    env["HERMES_HOME"] = env.get("HERMES_HOME") or "/home/council/.hermes"
    env["COUNCIL_SANDBOX_INSIDE"] = "1"
    env = with_hermes_path(env, mounts)
    if "/opt/review-council/scripts/council.py" in command:
        # the dispatcher refuses to run without it, and the image's entrypoint is what normally
        # sets it — a direct verb invocation has to set it itself
        env.setdefault("REVIEW_COUNCIL_DISPATCHED", "1")
    os.chroot(rootfs)
    os.chdir("/repo" if any(m.target == "/repo" for m in mounts) else "/")
    os.execvpe(command[0], command, env)
    return 127  # pragma: no cover - execvpe only returns by raising


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sandbox",
        description=(__doc__ or "").splitlines()[0] if (__doc__ or "").strip() else None)
    parser.add_argument("--inside", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--image", default="auto",
                        help="the OCI tarball; 'auto' builds .#container with nix")
    parser.add_argument("--rootfs", help="where to unpack (default: a cache keyed on the image)")
    parser.add_argument("--repo", help="the project to review, mounted at /repo")
    parser.add_argument("--home", help="a HERMES_HOME to mount at /home/council/.hermes")
    parser.add_argument("--hermes", help="a Hermes install to mount read-only at /opt/hermes")
    parser.add_argument("--seed", help="a directory with config.yaml/.env, mounted at /seed")
    parser.add_argument("--fresh", action="store_true", help="discard the cached rootfs first")
    parser.add_argument("--keep", action="store_true", help="leave the rootfs in place")
    parser.add_argument("command", nargs=argparse.REMAINDER,
                        help="-- <argv> to run inside (default: the image's entrypoint)")
    args = parser.parse_args(argv)
    command = [item for item in args.command if item != "--"]
    args.command = command
    if args.inside or os.environ.get(INSIDE_VAR) == "1":
        return inner(args)
    return outer(args)


if __name__ == "__main__":
    from council import require_dispatch

    require_dispatch("sandbox")
    sys.exit(main())
