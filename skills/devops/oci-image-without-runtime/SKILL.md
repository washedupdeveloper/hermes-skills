---
name: oci-image-without-runtime
description: Use when a container image must run with no runtime.
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, windows]
category: devops
metadata:
  hermes:
    tags: [docker, oci, containers, nix, unshare]
    related_skills: [nix-flake-packaging, hermes-remote-backend]
writes: [none]
side_effects: [none]
---

# Running an OCI image without a container runtime

**Runtime.** Podman; `docker` is the accepted substitute — the policy and the differences that bite are in `docs/runtime.md`.

`unshare`, `mknod` and the `/nix/store` paths are the Linux guest's. On a Windows host every
command here runs inside WSL; a native shell reports `unshare: command not found`.

## When to Use

- `docker`/`podman` are absent, unusable (no setuid, `newuidmap` missing), or refused by policy, and an image still has to run.
- Verifying a Nix `dockerTools` image's contents on the machine that built it.
- Testing a shipped CLI, browser lane, or service without installing its dependencies on the host.

A host can have no docker, no podman and no `newuidmap` (setuid-less distros, locked-down CI) and still run the image a flake or `docker save` produced. The image is a tar of layers; a rootfs plus a user namespace is a container.

## Extract correctly

- `manifest.json` lists `Layers` in order and names the config **as a filename** (`manifest["Config"]`), not inline JSON. Read that blob for `Env`; parsing the manifest as inline config yields an empty env with no error.
- Layers carry absolute paths (`/nix/store/...`) — strip the leading `/`, reject any `..`.
- Honour whiteouts: `.wh.<name>` deletes, `.wh..wh..opq` empties a directory.
- Python ≥3.14's tarfile default filter raises `AbsoluteLinkError` on store symlinks: pass `filter="fully_trusted"`.
- Expect store *files* as well as directories; create each mount target to match its source type.
- **`--transform` rewrites symlink targets too.** Stripping the leading `/` with
  `tar --transform 's|^/||'` turns `/nix/store/…` links into relative ones, and the image then dies
  at `chroot … /bin/sh: No such file or directory` while the file exists. Scope it to member names:
  `--transform 'flags=r;s|^/||'`, and `readlink` one `/bin` entry before entering as proof.

## A flake's `image-root` is a skeleton, not a rootfs

`nix build .#image-root` returns `/bin` symlinks and `/opt` links whose targets live in the
store, and **none of those targets are inside it**. Entering that tree with `chroot` or
`bwrap` dies at `execvp /bin/python3: No such file or directory` while `/bin/python3 -V`
works on the host — the host supplies the store, the image does not. Materialise the closure
the way the Dockerfile does before believing anything about it:

```sh
ROOT=$(nix build .#image-root --no-link --print-out-paths)
nix-store --query --requisites "$ROOT" | grep -v "^$ROOT$" | sed 's|^/||' > paths.txt
tar -cf closure.tar -C / -T paths.txt && mkdir -p /rootfs
tar -xf closure.tar -C /rootfs --no-overwrite-dir
tar -cf root.tar -C "$ROOT" . && tar -xf root.tar -C /rootfs --no-overwrite-dir
chmod u+w /rootfs && (cd /rootfs && sh .nix/prep.sh)
```

`chroot /rootfs /bin/python3 -V` is the cheapest proof the closure was complete: an
interpreter that resolves from *inside* the tree. `du -sh` beside it is the size claim.

## Verifying what an image contains, from its layers

Grep the extracted `*/layer.tar` listings, never the merged view. `dockerTools` `contents`
places a store path under `/nix/store/...`, while the friendly `/opt/<name>` is a **symlink
entry** (`./opt/<tool>`) whose target the listing does not expand. A check for
`opt/<tool>/scripts/<file>` therefore returns zero on an image that ships it, and
reads exactly like a missing file. Search for the basename and read the path that comes
back; count the layers from `manifest.json` to know whether the scan covered the image.

## Supply what runc supplies

| Missing | Symptom |
|---|---|
| tmpfs `/dev` + bound `null zero full random urandom tty`, devpts, 1777 `/dev/shm` | browser aborts (SIGABRT/SIGTRAP); any runtime lane is unrunnable |
| `/etc/resolv.conf`, `/etc/hosts`, CA bundle | API/model calls fail with "connection error", "you may be offline" — it is DNS |
| the image `Env` | empty `FONTCONFIG_FILE`/`PATH`; glyphless screenshots, missing binaries |
| a PATH entry for any mounted tool prefix | `rc=127` after the expensive work has already run |
| a nix-wrapped binary's **store closure** (`nix path-info -r`) | the wrapper runs and the binary it execs does not exist |

## Enter it

`unshare -r -m -p -f` maps container root to the invoking user, so files written into bind-mounted host directories stay owned by you. Then `os.chroot` + `os.execvpe`. The mount namespace dies with the process — no teardown needed; only the unpacked rootfs persists, so cache it keyed on image path + size + mtime.

**Bind targets are rootfs paths**, never host paths: `mount --bind src /repo` hits the host's `/repo` and fails with "mount point does not exist". The target is `<rootfs>/repo`.

**When `mount --bind /dev` itself is refused** in the user namespace ("wrong fs type, bad option, bad superblock on /dev"), stop fighting it and let bubblewrap build the pseudo-filesystems: `bwrap --ro-bind "$ROOT" / --dev /dev --proc /proc --tmpfs /tmp --chdir /repo --setenv PATH /bin …`. It still needs `/dev` to exist in the rootfs as a mount *target*, so create `dev proc sys tmp` in the image builder — a runtime mounts over those paths and cannot create them under a read-only root.

## Verify from inside

Run the image's own smoke test in there, not a host equivalent. Give "not exercised" its own exit code (0 complete / 3 incomplete / 1 failed): a self-test that reports green while a lane was skipped is how a broken browser once shipped, and a pasted `10/10` carries no information about the lanes it skipped.

## Pitfalls

- A fixed fallback `PATH` that cannot find nix fails portability checks; extend the caller's PATH rather than replacing it.
- A command resolved by bare name inside the image can hit an unrelated binary of the same name (`doctor` resolved to a PATH binary, not the CLI verb): dispatch `python3 <cli> <verb>` for anything that is a verb rather than an executable.
- A subprocess failure must name its class (`api-connection`, `timeout`, `schema`); `rc=1, file=missing` beside 24 completed probes tells a reader nothing.
- An allowlist that asks `path.is_relative_to(toolchain)` refuses **every** tool in a `symlinkJoin`: `<toolchain>/bin/gitleaks` is a symlink to a different store path, so the prefix test is false for all fourteen pinned analyzers while the tools work fine. Ask the inverse — does `<toolchain>/bin/<name>` resolve to this path? — in one helper shared by the bare-name and absolute-path branches.
- A `dockerTools` rootfs can contain **no `/dev` directory at all** — `mount -t tmpfs tmpfs $ROOT/dev` then fails with `mount point does not exist`, which reads like a permission error. `mkdir -p` every mount target (`dev`, `proc`, and each bind destination) before mounting; `mount` names only the first one it cannot find.
- Verifying as mapped root is fine, but artefacts the *user* must own have to be written through a bind mount.
- A materialised rootfs cannot be `rm -rf`'d: store files are 0555. `chmod -R u+w "$root"` first, or
  the delete prints a screen of `Permission denied` and leaves the tree.
