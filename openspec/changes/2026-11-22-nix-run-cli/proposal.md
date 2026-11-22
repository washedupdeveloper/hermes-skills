# The spec CLI runs through the flake

## Why

The repository told readers to install `@fission-ai/openspec` with `npx` or `npm install -g`,
and its own CI did the same. On a Nix host that is unnecessary and wrong: `npx` resolves a
package from the network at run time, at whatever version the registry serves, so the CLI that
validates the specs is described by nothing. `flake.lock` describes the system; the `npx`
invocation describes nothing.

`nixpkgs` already carries `openspec`. The flake now exposes it as `packages.openspec` and
`apps.openspec`, so the command is a flake output.

## What changes

- `nix run .#openspec -- <verb>` replaces every `npx` and `npm install -g` instruction, in the
  skill, `AGENTS.md`, the bootstrap template, the CI job template and this repository's workflow.
- The gate reads the form, not a version literal: every line that invokes the CLI must name
  `nix run .#openspec`, and an `npx` or `npm install` invocation fails wherever it sits.
- `pins.openspecCli` stays, as the version the flake is expected to provide, asserted against
  `pkgs.openspec.version` so a nixpkgs bump fails the gate instead of silently changing the CLI.
- The nix domain skills gain the rule they were missing: a Node CLI is a package and an app,
  never `npx`.

## Impact

- `nix-flake-packaging`: one new section, the pattern the other skills cite.
- `openspec` skill, `AGENTS.md`, `bootstrap.sh`, `templates/ci-job.yml`, `.github/workflows/ci.yml`.
- `nix/tests.nix`: the installer parser becomes a form check; the e2e mutants are re-pointed.
