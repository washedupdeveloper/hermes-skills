# Release artifact verification

What to run to prove a release is shippable, and what each command proves. Label every
result **executed** (the artifact ran) or **structural** (its bytes were inspected) —
never let the second stand in for the first.

## Wheel

```bash
out=$(nix build .#wheel --no-link --print-out-paths)
ls -l "$out"; sha256sum "$out"/*.whl
```

Install it into a clean environment, with no network, and run it:

```bash
nix run nixpkgs#uv -- venv /tmp/release-venv
nix run nixpkgs#uv -- pip install --no-index "$out"/*.whl  # nix-provision: the wheel under test
/tmp/release-venv/bin/python -c "import pkg; print(pkg.__version__)"
/tmp/release-venv/bin/pkg --help
```

`--help` proves the entry point resolves. To prove the wheel carries its data files,
read the archive and the metadata without `unzip` (not installed on a NixOS host):

```python
import pathlib, zipfile
wheel = next(pathlib.Path(out).glob("*.whl"))
with zipfile.ZipFile(wheel) as z:
    print("prompt:", [n for n in z.namelist() if n.endswith(".md")])
    meta = next(n for n in z.namelist() if n.endswith(".dist-info/METADATA"))
    print("\n".join(z.read(meta).decode().splitlines()[:4]))
```

Then run the installed tool end to end on a throwaway repository with a stub reviewer,
and read the exit code and `verdict.json`. A wheel can lack a prompt, a package-data
file or a console script and still answer `--help`.

A wheel cannot carry `bwrap`; `command` proofs there degrade to `UNRUNNABLE`. Say so
rather than reporting the wheel as equivalent to the image.

## Image

Structural, no daemon: unpack the tarball's `manifest.json` and assert one entry, the
`RepoTags` naming `name:version`, a `Config` file and every layer present.

Executed: materialise the rootfs and run the entrypoint under a user namespace:

```bash
nix develop -c bash -c 'PYTHON=python tools/image-run.sh image.tar.gz /bin/tool --help'
```

A materialiser that defaults to `python3` needs `PYTHON=python` on a host with no system
Python. `executed` means the binary printed its output; a clean `chroot` with no output
and exit 120 is a failed run, not a pass.

## Tag and version

```bash
python tools/release.py check --tag vX.Y.Z
git describe --tags --exact-match      # must print vX.Y.Z
```

A tag on the local machine is not published. State explicitly that it is unpushed, and
if a release commit lands after tagging, move the local tag to the final commit and run
the check again.

## CI entry

```bash
nix run nixpkgs#actionlint -- .github/workflows/ci.yml
nix run nixpkgs#yq-go -- -e '.runs.using' .github/actions/tool/action.yml
```

nixpkgs `yq` is the Python wrapper with a different argument order; `yq-go` is the Go
binary that takes an expression and a file. Then run the action's own command line
locally — the same flags, the same entry verb — and read its exit code. A valid workflow
file proves syntax, not that its command works.

## Report

One table: artifact, command, result, and whether it ran. A green build is not a verified
artifact, and "nix build succeeded" is not evidence that the thing inside runs.
