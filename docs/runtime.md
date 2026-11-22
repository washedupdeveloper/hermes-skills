# Container runtime

**Podman is the runtime this library writes for. Docker is the accepted substitute.**

Every command in a skill is written for `podman`. A reader who cannot or will not
use it replaces `podman` with `docker` in the command; the CLI is deliberately
compatible for everything here. Two things are not a substitution:

- **Compose.** Use `podman compose` (or `podman-compose`); a `docker-compose.yml`
  file is still the input format, so the filename does not change.
- **Daemon and socket.** Podman is daemonless by default. `podman system service`
  provides a Docker-compatible socket; a line that assumes `dockerd` is already
  running is wrong on a podman host and right on a Docker one.

## What stays named `docker` on purpose

A name is not a runtime choice. These keep their spelling:

- the `docker` value of `terminal.backend`, and the `terminal.docker_volumes` key;
- `Dockerfile`, `dockerTools`, `docker-compose.yml`, and a repository's `docker/`
  directory;
- a host description that genuinely has only Docker installed.

## The rule for authors

A fenced command that invokes `docker` as the program is a fallback, not the norm.
Mark the line so the gate can tell it apart from a name:

```sh
docker load < image.tar   # docker-fallback: reader verified on Docker only
```

Unmarked, the gate rejects it. The marker carries a reason because the next reader
deserves to know why this one line diverges.
