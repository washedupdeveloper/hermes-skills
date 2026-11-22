# Provisioning: a tool comes from Nix

The rule this library holds itself to: **a skill does not install a tool at run time.** It
names a Nix command that provides one.

```sh
nix shell nixpkgs#<tool> -c <tool> …     # one command, ephemeral, cached
nix run nixpkgs#<tool> -- …              # same, when the binary is the whole point
nix run .#<app> -- …                     # the repository's own flake app
```

## Why, in one paragraph

`pip install`, `npm install -g`, `npx`, `cargo install`, `apt install`, `brew install` and
`curl … | sh` all resolve a package from the network at run time. What they install is
described by nothing on the machine: not by a lockfile, not by a manifest, not by the flake
the user already has. The version can change between two runs of the same instruction. On a
Nix host this is not a style preference — it is a second, unrecorded package manager writing
into a profile the declaration does not describe, and the next `nixos-rebuild` does not know
it exists.

Nix resolves the same package through `flake.lock`, puts it in the store, caches it, and makes
the version a thing a reviewer can read. That is the whole argument.

## What the rule covers

A fenced command in any `.md` under `skills/` that installs:

| verb | example |
|---|---|
| `pip install`, `python -m pip install`, `pipx install` | `pip install websockets` |
| `uv pip install`, `uv venv`, `uv tool install`, `uv add`, `uvx` | `uv pip install pytest` |
| `npm install -g`, `npm i -g`, `npx` | `npx -y some-cli` |
| `pnpm add -g`, `yarn global add`, `bun add -g` | `pnpm add -g some-cli` |
| `cargo install`, `go install`, `go get`, `gem install` | `cargo install ripgrep` |
| `apt install`, `dnf install`, `pacman -S`, `snap install`, `brew install`, `choco install`, `winget install` | `apt install jq` |
| `curl … \| sh`, `wget … \| sh` | `curl -fsSL https://x/install.sh \| sh` |

`npm install` without `-g` is not covered: a Node project's own dependencies are its build,
not a tool this library provisions. Neither is a version manager's own bootstrap — `nix` has
to come from somewhere.

## The two exceptions

Both are marked on the line, so the exception is a decision a reader can see rather than a
rule that quietly did not fire.

**The artifact under test.** A release-verification step installs the wheel it just built. That
is the subject, not a tool. Install it with `uv` from nixpkgs and no index:

```sh
nix run nixpkgs#uv -- pip install --no-index "$out"/*.whl  # nix-provision: the wheel under test
```

**Installing Nix itself.** Nothing can provision Nix except Nix. The bootstrap command is
allowed and is the only one.

```sh
# nix-provision: Nix cannot be provisioned by Nix
curl -L -o /tmp/nix-install.sh https://nixos.org/nix/install
```

A line that needs an exception carries a trailing `# nix-provision: <reason>`. The gate reads
that marker; a reason is required, and the marker alone is not a reason.

## What this replaced, in this repository

The spec CLI was the first offender: `npx -y @fission-ai/openspec@1.15.0` in six places. It is
now `nix run .#openspec -- …`, a package and an app of this flake, with `pkgs.openspec.version`
asserted against `pins.nix` so a nixpkgs bump fails the gate instead of silently changing the
tool. `nix-flake-packaging` carries the general pattern; `nix-declarative-config` carries the
declarative form for a whole system.

## Where the gate runs

`scripts/scope.py:check_provisioning` reads every fenced block under `skills/` and fails a line
that invokes one of the verbs above without a `# nix-provision:` marker. It runs as part of
`python3 scripts/validate.py`, so it holds with or without Nix on the machine.

The one place the rule does not reach is CI's no-Nix leg, which installs `pytest` with pip on
purpose: that job exists to prove the gate needs no Nix, and a Nix provisioner there would
delete the thing being tested.
