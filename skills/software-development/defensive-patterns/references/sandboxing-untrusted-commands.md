# Sandboxing a command that comes from outside the program

Verified on Linux 6.18 (WSL2) with bubblewrap 0.12. Needs `CONFIG_USER_NS` and unprivileged
overlay support; both are common, and the way to find out is to mount it, not to read a
version string.

## Probe the machine first

```bash
bwrap --version
unshare --user --map-root-user --mount sh -c '
  mkdir -p /tmp/o/{up,work,mnt}
  mount -t overlay overlay -o lowerdir=/etc,upperdir=/tmp/o/up,workdir=/tmp/o/work /tmp/o/mnt \
    && echo overlay-ok'
```

A kernel released before 5.11 lacks unprivileged overlay, but a vendor suffix (`-microsoft-
standard-WSL2`, `-azure`) says nothing either way. Mount it.

## The argv

```python
target = repo.resolve()
mountpoint = ["--dir", str(target.parent)] if target.is_relative_to("/tmp") else []
argv = [
    bwrap, "--unshare-all", "--die-with-parent", "--clearenv",
    "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
    "--tmpfs", "/tmp", *mountpoint,
    "--overlay-src", str(target), "--tmp-overlay", str(target),
    "--chdir", str(target),
    "--setenv", "PATH", os.environ.get("PATH", "/usr/bin:/bin"),
    "--setenv", "HOME", "/tmp", "--setenv", "TMPDIR", "/tmp",
    "--setenv", "PYTHONDONTWRITEBYTECODE", "1",
    "--setenv", "PYTEST_ADDOPTS", "-p no:cacheprovider",
    "--", *command,
]
```

`--unshare-all` covers net, pid, ipc, uts, cgroup and user. The two pytest variables matter
because a test runner writes `__pycache__` and `.pytest_cache` into the tree it is reading.

## Three traps

**Overlay the repository, never `/`.** `--overlay-src / --tmp-overlay /` fails with
`Can't make overlay mount ... userxattr: Invalid argument`, because `/` carries the `/proc`,
`/dev` and `/sys` submounts. The message blames `userxattr` and sends you after a kernel
rebuild you do not need — the same overlay works on a subdirectory. Overlaying the repo alone
lets the command write freely and leaves the real tree untouched (verify: write a file inside,
read the original outside).

**`--tmpfs /tmp` hides a repository that lives under `/tmp`** — pytest's `tmp_path`, scratch
checkouts. Bind it back *after* the tmpfs and create the mountpoint first with `--dir`;
`--dir` creates missing parents, so a nested `/tmp/pytest-x/sub` works.

**A relative path bound over the sandbox root hides everything.** `--ro-bind . .` binds the
caller's cwd, not the repo; always pass `repo.resolve()`.

## What each failure means

| observation | meaning |
|---|---|
| no `bwrap` on `PATH` | UNRUNNABLE — never spawn unsandboxed |
| `bwrap:` startup error | UNRUNNABLE, not a refutation of the claim |
| write outside the repo/`/tmp` | `EROFS` → UNRUNNABLE |
| command exits non-zero | the claim under test is refuted; the sandbox worked |

Only report a claim refuted after the command actually ran. A sandbox that fails to start
is an absent check, and treating it as evidence is the bug the sandbox exists to prevent.

## Testing it

- Gate the tests on the feature, not the image:
  `@pytest.mark.skipif(not _userns_ok(), reason="user namespaces are unavailable here")`,
  where `_userns_ok()` runs a trivial `unshare`. Those tests skip in a build sandbox that
  blocks user namespaces — say so in the report instead of counting them as passes.
- The allowlist is part of the fixture: a command using `python3` needs `python3` in the
  allowlist, or it fails as "not allowed" — which reads as a sandbox bug and is a fixture bug.
- Assert the effect, not the exit code: after a write attempt inside the repo, re-read the
  file from outside and require the old content.
