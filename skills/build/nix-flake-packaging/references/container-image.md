# Building the container image from the flake

Why the image is a flake output rather than a Dockerfile, the `dockerTools`
traps, and the read-only-store consequences for a toolchain that resolves
itself.

## Shipping the flake as a container image

For users who are not on NixOS, the image is **an output of the same flake**, not a
Dockerfile beside it: `packages.<system>.container` from `dockerTools`. A Dockerfile
reinstalls the tool set from `pip`/`apt` at whatever versions resolve, so the container and
the Nix host disagree about the same repository and neither number is authoritative. Built
from the flake, the analyzers *are* the pinned store paths — one mechanism, and a score
means the same thing on both sides. This is worth measuring rather than asserting: run the
repo's own diagnostic command on the host and inside the image and compare field by field.

`dockerTools` has four traps, all of which fail at build time with an unhelpful message:

- **Drop the nix database, and build LAYERED.** `buildImageWithNixDb` is the only thing
forcing a single layer: its gcroots point into a layer that is not present while it is
generated (`ln: failed to create symbolic link ...: Permission denied`), which is why the
warning printed beside it says "better to only have one layer that contains a nix store".
Measure what the database buys before keeping it, because the answer is usually nothing:
nothing at run time calls `nix path-info` or `nix-store -q`, and `buildLayeredImage`
without it measured **99 layers at 333 MiB** against **365 MiB single-layer**, with the nix
probes, the analyzers and the diagnostic command all still working. Layering is also the
whole caching story — a store path's layer is content-addressed, so an unchanged toolchain
produces byte-identical layer digests and a pull fetches only what changed.
- **`buildLayeredImage` takes `contents`, not `copyToRoot`.** The latter belongs to
`buildImage`; passing it to the layered builder dies with `unexpected argument
'copyToRoot'`.
- **`lib.unique` the `contents` list.** Two names can resolve to one store path
  (`bashInteractive` and `bash`), and a duplicate breaks the database step: it symlinks each
entry into `nix/var/nix/gcroots/docker` by basename, then follows its own symlink into the
read-only store on the second pass.
- **Do not write `/etc/passwd`.** `etc` arrives from a package as a symlink into the
read-only store (nix ships `etc/profile.d`), so a build-time write fails and a Nix image has
no shadow suite for runtime. Set `config.User` to a numeric uid:gid and set `HOME`
explicitly; nothing then needs to resolve a user *name*.
- **Nest a directory tree under a prefix.** `dockerTools` merges a content path's
**top-level** entries into the image root, so adding a repo tree scatters its directories
across `/`. Wrap it in a derivation that symlinks it to `$out/opt/<name>`.

Two consequences for the scripts inside:

- **A read-only store breaks toolchain resolution.** A helper that runs
  `nix build <flake>#toolchain` to find its tool set cannot work in a container —
instantiating a derivation writes a `.drv`. Give it an environment-variable short-circuit
(`REVIEW_COUNCIL_TOOLCHAIN`, checked before the build) and bake the value into the image's
`config.Env`. Without it every probe that depends on the toolchain reports "did not run"
and a coverage term silently drops, with no error to explain why.
- **Assume the agent CLI, do not install it.** An image that bundles it pins the user to one
version and drifts from theirs. Resolve it from an explicit env var (`HERMES_BIN`) or `PATH`,
fail with instructions when it is absent, and make the harness honour the same variable — a
`shutil.which`-only lookup cannot see an install mounted outside `PATH`.

### A Dockerfile is allowed as a thin consumer, never as a second definition

A host can run docker and not nix, and that is a real audience — docker is the one
interface every CI system and PaaS already speaks. The mistake is letting the Dockerfile
*install* the tool set, which is what makes the two paths disagree about the same
repository. Keep one definition: hoist the image's contents into the flake as a plain tree
output (`.#image-root`), and have the Dockerfile's build stage run nix to produce it and
then copy its closure into a `scratch` image. The Dockerfile then adds container plumbing
only — `ENV`, `WORKDIR`, `USER`, `ENTRYPOINT`, `CMD` — and cannot drift.

State which path is primary rather than implying they are equivalent: the flake produces a
layered image, the Dockerfile a single layer, because the layering is `dockerTools`' and
`docker build` cannot reproduce it. And prove the seam by building the tree with and
without `.git` — nix treats a git checkout and a plain path as different inputs, and the
Dockerfile's build context has no `.git`.

**Read-only store paths: modes set inside a derivation do not survive a copy.** A store
path is 0555, so the modes a derivation set are gone the moment something copies the tree
out — `tmp` arrives 0555 rather than 1777, and a probe that needs scratch then fails. Ship
the mode-setting as a FILE in the tree and have the consumer re-run it on the copy.
`dockerTools` needs no such step because its `extraCommands` runs on the image root, where
modes ARE preserved: one definition of the prep, two ways of applying it.

**`cp -a` propagates the source directory's mode onto the destination.** Copying a 0555
store path with `cp -a` leaves the destination read-only, so the next step in the same
`RUN` cannot write to it. Use `tar -cf … -C <src> .` piped into `tar -xf … -C <dst>
--no-overwrite-dir`, which records modes without altering the extraction root — and one
archive beats N `cp` invocations.

**`>` truncates an existing file and needs write permission ON THE FILE.** A `chmod u+w
etc` does not let you rewrite `etc/passwd` if the file already exists at mode 444 — from a
package, or from a second run of the same script. The redirect fails, the content silently
stays whatever it was, and the symptom surfaces much later as a user-resolution error.
`chmod u+w etc/passwd etc/group` before the redirect, and assert on the file's CONTENT
rather than treating "no output" as success.

**Merge each content path's `bin` into `/bin`.** `dockerTools` does this for you; a plain
tree does not, so an image built from one has every analyzer reachable only through the
entrypoint's `PATH` — and `docker run --entrypoint sh` finds none of them. That divergence
surfaces only while someone is already debugging.

**`--user "$(id -u):$(id -g)"` needs the in-image paths writable by that uid too.** The
image runs as uid 1000 and a caller is not necessarily 1000, so the repo mount AND the
profile home have to be world-writable, and the entrypoint has to append a passwd entry for
the runtime uid — `nix` resolves `$HOME` through `getpwuid` and fails without one. Without
the flag the run directory lands in the repo while the home stays read-only, and the
failure is a traceback rather than a message: have the harness catch the `PermissionError`
and print the flag instead.

### State the limitation the image cannot fix

The same read-only store means the image **cannot review a Nix repository
properly**: evaluating a foreign flake means fetching inputs and instantiating
derivations, both of which write, and nix also wants to own
`/nix/var/nix/profiles/per-user`. The probes then report `ran: false`, which is
honest but leaves the deterministic half of the score thin.

That is a documentation problem, not a build one — say it plainly, and point a Nix
repository at the native deployment rather than letting someone conclude the tool
scores badly. Distinguish the two cases in the docs: on a Python, Go, Rust or
JavaScript repository the container is fully equivalent; on a Nix repository it is
not, and the native path is the honest one. A limitation stated up front costs a
paragraph; discovered, it costs the user's trust in every other number.

### Verify the image by running it, in a VM

An extracted rootfs run under `unshare --user` + `chroot` proves the *contents* are right and
nothing more: no runtime namespaces, mounts or cgroups, and it runs as root, which hides every
permission problem. If no container runtime is installed locally, a `runNixOSTest` that boots a
NixOS VM with `virtualisation.docker.enable = true`, `docker load`s the image and runs it is
the cheap way to get a real one. Give the VM `virtualisation.diskSize` headroom — a multi-
hundred-MB image fills the 1 GB default mid-load with `no space left on device`.

**The test VM has no outbound network.** No DNS, and QEMU's gateway is closed, so anything
that fetches inside it fails for a reason unrelated to what is being tested — `docker
build` cannot pull a base image at all, and the error reads like a Dockerfile problem. Two
consequences: verify the built image by `docker import` from a rootfs tarball (which is
exactly what a `FROM scratch` + `COPY --from=builder / /` produces) rather than by `docker
build`; and if you point `docker build` at the tree anyway, assert on WHICH error came back
— Docker parses the whole file before executing any instruction, so reaching the pull
proves the file parses, and `unknown instruction` is the failure that means it does not.
Asserting the parse is real evidence; asserting nothing is not. Importing the rootfs and
running the analyzers under a real daemon is the stronger test regardless: it exercises
namespaces, mounts and cgroups, and it proved 16 probes actually RUN inside the image —
resolving a tool is not running it, and a toolchain that is present but cannot execute is
exactly what a score silently degrades over.

**Reaching a host service from a VM: `127.0.0.1` in a guest is the guest.** A test that
needs the host's loopback has to say so explicitly, and the address is not the one you
would guess. Measured with a control listener to prove the probe itself works: a listener
*inside* the VM answers on `127.0.0.1`, the host's does not, and the host is reachable at
QEMU's SLIRP gateway `10.0.2.2` — but **only with the build sandbox off**, because the
sandbox gives the build its own network namespace, so that gateway points at the sandbox's
loopback and the host's services are invisible.

`--option sandbox false` on its own changes nothing: it is not part of the derivation, so
nix returns the CACHED result and the option appears inert — the experiment "confirms"
whatever it did last time. Force it with `--rebuild`. Better still, design the test so it
needs no host service: a stub honouring the same contract tests the harness, and tests
nothing about the host — which is the part a test should not depend on anyway.

Four defects that only that run could see, all silent in a chroot:

- **No `/etc/passwd`.** Nix resolves `$HOME` through `getpwuid()` rather than trusting the
environment, so a numeric `config.User` — all the kernel needs — is not enough: every nix
invocation fails with `cannot determine user's home directory`. Write the entry in
`extraCommands`, after `chmod u+w etc` (a package's `etc` arrives mode 555).
- **No `nix.conf`.** A minimal image has none, so the experimental features are off and
`nix eval` / `nix flake check` fail with `experimental feature 'nix-command' is disabled`.
`/etc` is read-only, so stage the conf under `/opt` and set `NIX_CONF_DIR`.
- **`nix/var/nix` not writable.** Nix opens the store's lock file on startup, so even
`nix --version` fails as a non-root user with `opening lock file ...: Permission denied`.
`chmod -R a+w nix/var/nix` in `extraCommands` — and `mkdir` the per-user profile directory
*before* that chmod, or it is created afterwards and left mode 755.
- **A missing runtime dependency.** Anything a script shells out to has to be in the image;
here `baseline.py` calls `git diff` and `git ls-files`, so `--baseline` could not work at all.
Grep the scripts for external commands rather than assuming the toolchain covers them.

**A `path:` flake input is pinned by narHash, so an edit does not reach a test that depends on
it.** A consumer flake that takes your repo as `path:…` keeps using the locked revision after
you change the source, and the test silently re-runs against the OLD image — reporting a
pass for code you already fixed. Run `nix flake update <input>` in the consumer before
trusting any result, and confirm the run actually happened (a build log with no VM output
means it was cached).
