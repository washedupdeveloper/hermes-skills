## REMOVED Requirements

### Requirement: The installer is one the gate understands

**Reason**: The gate no longer reads an installer. The CLI is an output of this flake, so there
is no install step to parse and no version literal to compare.

**Migration**: A line that invokes the CLI must name `nix run .#openspec`; see the requirement
below. `pins.openspecCli` remains as the version the flake is expected to provide.

## ADDED Requirements

### Requirement: The CLI runs through the flake app

A line that invokes the spec CLI SHALL name `nix run .#openspec`. An `npx` or `npm install`
invocation SHALL fail the check wherever it sits, naming the file and the line.

`nix run` resolves the CLI through `flake.lock`, so the version is pinned once and the tool is
offline after the first fetch. `npx` resolves it from the network at run time, which is a second
pin that nothing records.

#### Scenario: A line uses the flake app

- **WHEN** a line reads `nix run .#openspec -- validate --all --strict`
- **THEN** the check accepts it

#### Scenario: A line falls back to a package manager

- **WHEN** a line reads `npx -y @fission-ai/openspec@1.15.0 validate`, `npm install -g`,
  `pnpm add -g`, or the bare `openspec validate` where the binary would have to be on PATH
- **THEN** the check fails, naming the file and the line

#### Scenario: Prose names the form it forbids

- **WHEN** a sentence reads "`npx` and `npm install -g` are what this replaces"
- **THEN** the check passes: the rule measures invocations, not mentions

### Requirement: The flake provides the version the repository documents

`pkgs.openspec.version` SHALL equal `pins.openspecCli`. A nixpkgs bump that changes the CLI
SHALL fail the gate rather than silently changing the tool that validates the specs.

#### Scenario: nixpkgs ships a different version

- **WHEN** `pkgs.openspec.version` is not the value in `pins.openspecCli`
- **THEN** `nix flake check` fails, naming both values
