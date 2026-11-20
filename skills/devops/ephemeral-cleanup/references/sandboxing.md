# Sandboxing a command so its writes vanish

Use this when a shell, test run, reviewer or other child process must be able to
read the host and reach the network but must not leave files behind. The
filesystem boundary is the point; network isolation is a separate decision.

## Linux / NixOS: bwrap overlay

```bash
bwrap --die-with-parent --unshare-pid \
  --ro-bind / / --dev /dev --proc /proc --tmpfs /tmp \
  --ro-bind "$PROMPT_DIR" "$PROMPT_DIR" \
  --ro-bind "$BINARY" "$BINARY" \
  --overlay-src "$HOME" --tmp-overlay "$HOME" \
  --chdir / -- "$@"
```

- `--ro-bind / /` makes the host readable and immutable.
- `--tmpfs /tmp` gives the child a private `/tmp`; writes there vanish.
- `--overlay-src "$HOME" --tmp-overlay "$HOME"` is the single-argument form:
the home is readable, writes land in a tmpfs upper layer, and the host home is
unchanged. Do not pass a separate `--overlay` path; the two-argument form is a
different operation and fails or exposes the wrong tree.
- `--die-with-parent` prevents an orphan holding the sandbox open.
- `--unshare-pid` keeps the child's process view private; it does not hide the
  host filesystem.

**Rebind what the private `/tmp` hides.** A prompt file, a stub reviewer, or a
script under `/tmp` disappears when `--tmpfs /tmp` is mounted. Bind each needed
path back read-only after the tmpfs. A missing file then reads as `ENOENT` even
though it exists on the host; that is the symptom, not a missing input.

**Kill the process group, not just the parent.** A wrapper's `sleep` or shell can
inherit the stdout pipe and keep a stream reader open after the parent exits.
Start the child in its own session and kill the group on timeout; otherwise the
watchdog fires but the reader never sees EOF.

## Non-NixOS: the container is the boundary

Where bwrap is unavailable (macOS, native Windows), use an OCI container as the
coarse sandbox:

```bash
docker run --rm --read-only --tmpfs /tmp \
  -v "$PWD:/repo:ro" \
  -v "$HOME/.config/hermes:/root/.config/hermes:ro" \
  <tool> review -C /repo --base HEAD --json
```

- `--rm` removes the container filesystem; `--read-only` makes the image
  immutable; `--tmpfs /tmp` gives the run a writable, vanishing scratch area.
- Mount the repository read-only. The reviewer reads it; proofs overlay it; no
  write reaches the host.
- The container shares the host kernel and needs a runtime. It is a coarser
  boundary than bwrap, not a stronger one.
- Native Windows uses WSL2 (the Linux path) or a container; there is no bwrap.

## What this does not do

- **No network isolation.** The reviewer must reach the model. bwrap and the
  container keep the filesystem boundary, not the network one.
- **No read secrecy.** The child can read what the host exposes; the sandbox
  prevents writes, not reads.
- **No image cleanup.** `--rm` removes the container, not the image or build
  cache; those belong to the runtime.
- **No claim on a host without a boundary.** Without bwrap or a container, a
  temp run directory still removes its own tree, but a process can write
  elsewhere. Record the sandbox as unavailable (`reviewer_sandbox: false`) rather
  than implying isolation.

## Test the boundary, not the flag

A test that only asserts `--sandbox` was passed proves nothing. Have the child
write a marker to `$HOME` and `/tmp`, run it through the sandbox, and assert both
host markers are absent. Also test the refusal path: with bwrap removed from
`PATH`, the wrapper must exit non-zero with an install hint, not silently run
unsandboxed.

In a Nix build there is no `/usr/bin/env`; a test that executes a repo script
directly fails with `FileNotFoundError` naming the script, not the interpreter.
Invoke it as `bash ./script` (or patch the shebang) so the test measures the
script rather than the build sandbox's missing FHS path.