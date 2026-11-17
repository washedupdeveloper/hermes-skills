# Shipping to other machines

Depth for the step after the code is correct: making a repository usable by someone whose
machine is not yours. Reach for this when the ask is "is this generally applicable, or
has it been tuned to your situation?"

## What counts as shipping

Anything another person reads or runs. Machine-specific values hide in places a source
scan for `os.path` never looks:

- test fixtures and expected-output files
- doc examples, tables and recorded error output
- injected sample defects and example configs
- error messages and help text
- skills and rubrics, which are installed onto other people's machines

A historical record (a decision log, a milestone, a test log) still ships. The fact it
records survives genericisation; the incidental path adds nothing a placeholder does not.

## Auditing for local assumptions

Grep for the *shape* of a path, not one spelling of it, and case-insensitively:

```bash
grep -rniE '(/home/[a-z]+|/Users/[A-Za-z]+|[A-Za-z]:[\\/]Users[\\/])' \
  --include='*.py' --include='*.sh' --include='*.nix' --include='*.md' \
  --include='*.yaml' --include='*.json' .
```

Then separately for the specific names: username, hostname, distro name, and any
project name that only exists on your machine. Search both spellings of a Windows path —
a file containing a string literal stores a doubled backslash per separator, so the
single-backslash form matches nothing and the audit falsely reports clean.

Exclude generated and vendored trees from the count, but read the hits before dismissing
them. An adapter that translates one platform's paths is not a hardcoded dependency, and
neither is a fixture whose *purpose* is to exercise a translation — say so rather than
leaving a reader to wonder.

## Resolving an external binary

A program that shells out to another tool should not assume it is on PATH. Look for an
explicit override first, then fall back:

1. the variable you document (`MYTOOL_BIN`) — expanded, and accepted either as a path or
   as a bare name to look up
2. a lookup on PATH

Without the override, the only way to point at an alternate install is to rewrite PATH
for every caller — which a container entrypoint or a wrapper cannot always do. Also
prepend the resolved binary's directory to PATH when a *sibling* script resolves the tool
by name rather than through the variable.

## Packaging so it runs elsewhere

**Do not install the application you orchestrate.** If the tool is a plugin, extension or
front-end for another program, it should use that program's install — a second copy baked
into an image is one the user did not choose and which drifts from theirs. Instead:

- make the base image a build argument (`ARG BASE_IMAGE` / `FROM ${BASE_IMAGE}`) so the
  image can be layered on one that already has the dependency
- resolve the dependency at entrypoint and, when it is absent, print the exact command to
  supply it — mount the install, or set the override variable
- guard optional package installs (`command -v apt-get`, `command -v pip`) so a different
  base image still builds, and let a missing optional tool degrade a metric rather than
  fail the run

State in the README what is verified and what is not. An image that has never been built
is not a working artifact, and saying so is more useful than implying otherwise.

## Version skew between the release and the development branch

A tool installed from a package index lags the branch the framework is developed against,
so a flag or subcommand that exists upstream may be absent from the release. Prefer the
invocation that works on both — set the child's working directory rather than passing a
version-specific `--in`/`--cwd` flag — and check the released version's `--help` before
relying on a flag you read in the source.

Scores or outputs are comparable only within one install. Two installs with independently
resolved dependencies are two different measurements; say which one a number came from.

## Calibration is not portable

A threshold derived from a defect ladder built from one repository is a yardstick for that
repository, not a standard. Check whether the calibration file states its own provenance,
and report it: a metric built from one known-good sample is provisional by its own
description. The *findings* are the portable output; the score is local. A new user
recalibrates, or sets the threshold themselves and reads the score as a relative signal.
