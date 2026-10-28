# Spec Delta

## ADDED Requirements

### Requirement: The installer is one the gate understands

A line that names the CLI SHALL use an installer the gate parses — `npm`, `npx` or `nix`. Any other
installer SHALL fail the check, naming the file and the line.

#### Scenario: An adopted installer

- **WHEN** a line reads `npm install -g @fission-ai/openspec@1.15.0`, or runs it through
  `nix shell … -c npx`
- **THEN** the check accepts the line and the version rule reads its spec

#### Scenario: A foreign installer

- **WHEN** a line reads `pnpm add -g @fission-ai/openspec@1.15.0`, `bun add -g`, or
  `yarn global add`
- **THEN** the check fails and names the line, because the version rule cannot read it

#### Scenario: An installer with no package at all

- **WHEN** a line pipes an archive into a shell, `curl … | sh`
- **THEN** the check fails: there is no package spec and no version for any rule to read
