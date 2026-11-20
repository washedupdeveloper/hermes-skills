# Running a child under bwrap with no host writes

Use this when a harness spawns a reviewer, agent or other child that must be able
to read the host and reach the network, but must not leave anything behind.

## The invocation

```bash
bwrap \
  --die-with-parent --unshare-pid \
  --ro-bind / / \
  --dev /dev --proc /proc --tmpfs /tmp \
  --ro-bind "$PROMPT_DIR" "$PROMPT_DIR" \
  --ro-bind "$BINARY" "$BINARY" \
  --overlay-src "$HOME" --tmp-overlay "$HOME" \
  --chdir / \
  -- "$BINARY" "$@"
```

- `--ro-bind / /` makes the whole host readable and immutable. A repository under
  `$HOME` is writable only through the home overlay; a repository outside `$HOME`
  stays read-only.
- `--tmpfs /tmp` gives the child a private `/tmp` that vanishes with it. It also
  hides the prompt file and the binary if they live under `/tmp`, so bind each back
  **after** the tmpfs. Binding a file to its own path is valid.
- `--overlay-src "$HOME" --tmp-overlay "$HOME"` is the two-argument home overlay.
  `--overlay` is a different, three-argument mount (`RWSRC WORKDIR DEST`); do not
  substitute it.
- `--chdir /` avoids a cwd that the private `/tmp` just hid.
- `--die-with-parent` and `--unshare-pid` keep the child from outliving the caller
  and from seeing the caller's process tree.
- Network is shared by default. That is deliberate for a model call; if the child
  does not need it, add `--unshare-net` and expect the call to fail.

## Python helper

```python
def sandbox_argv(argv: list[str], prompt_dir: Path) -> list[str]:
    bwrap = shutil.which("bwrap")
    if bwrap is None:
        raise OSError("bwrap is required for the sandbox but is not on PATH")
    binary = shutil.which(argv[0]) or argv[0]
    home = str(Path.home())
    return [
        bwrap, "--die-with-parent", "--unshare-pid",
        "--ro-bind", "/", "/",
        "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp",
        "--ro-bind", str(prompt_dir), str(prompt_dir),
        "--ro-bind", binary, binary,
        "--overlay-src", home, "--tmp-overlay", home,
        "--chdir", "/", "--", *argv,
    ]
```

## The test that proves containment

A print-only stub proves the child starts, not that writes are contained. The fake
must write to both places the sandbox claims to protect, and the test must assert
the host is clean afterwards:

```python
marker_home = Path.home() / "sandbox-leak-marker"
marker_tmp = Path("/tmp/sandbox-leak-marker")
for marker in (marker_home, marker_tmp):
    marker.unlink(missing_ok=True)

binary = py_script(tmp_path, '''
from pathlib import Path
Path.home().joinpath("sandbox-leak-marker").write_text("x")
Path("/tmp/sandbox-leak-marker").write_text("x")
print(json.dumps({"sections": {}}))
''')
answer = hermes_runner("p", binary=str(binary), timeout=20, sandbox=True)("q")
assert answer.strip() == '{"sections": {}}'
assert not marker_home.exists()
assert not marker_tmp.exists()
```

Skip only when `bwrap` is genuinely unavailable. In a Nix build sandbox the binary
can be present while user namespaces are unavailable, so a `which("bwrap")` guard
is not proof the test ran; assert the test executed, or split it into a host-only
check and name which gate ran it.

## Real-child check

Before making the sandbox the default, run the real child once inside it:

```bash
bwrap --die-with-parent --unshare-pid --ro-bind / / \
  --dev /dev --proc /proc --tmpfs /tmp \
  --overlay-src "$HOME" --tmp-overlay "$HOME" --chdir / \
  -- hermes -p <profile> chat -q "Reply with the single word: ok" --oneshot -Q
```

A real Hermes call answered `ok` in 21 s under this shape, which proves the
profile, credentials and network survive the sandbox. A fake binary alone does not.

## Limits

- Linux only. macOS and Windows have no bwrap; a portable tool records
  `sandbox: false` there rather than pretending.
- Reads are not isolated: the child can read the host. The sandbox prevents writes,
  not disclosure. If reads matter, bind only the directories the child needs.
- The home overlay is per-process. Two concurrent children do not share writes, and
  neither sees the other's overlay.
- A bare wheel cannot carry bwrap. The Nix package puts it on the wrapper's `PATH`;
  a wheel user without it gets `sandbox: false` or a strict-flag failure, not a
  silent fallback.