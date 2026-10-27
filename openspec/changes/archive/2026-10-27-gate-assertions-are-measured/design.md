# Design

## One scanner, and why it reads tokens instead of YAML

`scanLines` is the only place a file becomes numbered, non-comment lines. There were two
scanners; the second skipped comments but over a narrower file set, which is how the template
escaped the pin rules for a while.

The two rules read *tokens*, not YAML structure:

- **Runner.** The label is the defect wherever it sits — `runs-on: ubuntu-latest`, a quoted
  value, `[ubuntu-latest]`, a block list under `runs-on:`, or `os: [ubuntu-latest]` behind
  `runs-on: ${{ matrix.os }}`. Every one of those carries the token on a line, so matching the
  token is wider than a parser, and a parser would only narrow the surface. The rule reads
  workflows and the shipped template; AGENTS.md mentions `-latest` in prose *about* the rule,
  and a shell script's install message is not a runner.
- **Install.** `npx [-y] <spec>` takes the first non-flag after `npx`;
  `npm install|i|add -g|--global <spec>` takes the first non-flag after the subcommand, with
  value-taking flags (`--prefix`, `-p`, `--registry`, `--cache`, `--userconfig`) and their
  values skipped. Without that, `bootstrap.sh`'s `--prefix ~/.local/npm` reads as a package.

A comment starts at a `#` preceded by a space. Splitting on every `#` truncated
`nixpkgs#nodejs_22`, which silently removed AGENTS.md's `npx` line from the scan — the negative
controls caught it, which is why they exist.

## Fail closed

`builtins.pathExists` guarded the template, so renaming it left the scan empty and the gate
green. Presence is now an assertion (`adoptedMissing`), and a second assertion requires the
scanned set to be non-empty, because a sweep over nothing passes every other rule and looks
exactly like a real pass.

## One version, and a fifth site cannot hide

`nix/pins.nix` holds `openspecCli`. Every install spec must equal it, so all four adopted sites
are checked against one value rather than against each other. Discovery is separate: every text
file that names the package must be an adoption site or prose (`docs/`, `openspec/`, and `nix/`,
which quotes the forbidden forms as test data). A new workflow or script that names the CLI
fails until it is added to the checked set.

## Cost (task 6.1)

Same command, same host, warm store:

    nix eval --raw .#checks.x86_64-linux.workflows.drvPath

| | runs (ms) | median |
|---|---|---|
| before | 1391, 514, 503 | 514 |
| after | 604, 528, 530 | 530 |

**+16 ms, about 3%.** The eval tier now reads every tracked text file — 249 of 256, 2.32 MB —
because the fifth-site discovery cannot know in advance which file might name the CLI. The CRLF
assertion reuses the same file list, so the walk is computed once.

No Python or shell execution path gained work. The change touches the eval tier and two text
files that are *read*, not run: `bootstrap.sh:10` is a message literal naming the install
command, and the only executable line this change alters is the CI step's flags.

Eval-tier checks produce a derivation whose hash does not depend on the tree (`runCommand` with no
inputs), so `nix build .#checks.workflows` cannot distinguish content — a wrong tree fails at
*evaluation*. That is why every verification below runs `nix eval`, and why a green build is not
evidence for these assertions.

## Formatting and lint record (task 4.2)

Measured on the change's tree. `nixfmt --check $(git ls-files '*.nix')` over 17 tracked files
reports **6 failing at HEAD** (this file's `nix/tests.nix` among them) and **5 now**. The probe's
"ten files" does not reproduce with that command; the reviewer's "six" does.

| Tool | Location | Disposition |
|---|---|---|
| nixfmt | nix/tests.nix | **formatted by this change** (4.1) |
| nixfmt | nix/checks.nix, nix/lib.nix | deferred — formatting-only diff in files this change does not touch, and nothing enforces the formatter yet |
| nixfmt | skills/autonomous-ai-agents/council/tests/golden/target/modules/base.nix | kept — a golden fixture; reformatting changes the bytes the golden diff compares |
| nixfmt | skills/devops/nix-declarative-config/templates/hermes-skills.nix, .../skills-refresh-timer.nix | kept — shipped templates; users copy these bytes |
| deadnix | flake.nix:11 (`self`) | accepted — the flake's outputs signature; removing it changes the documented interface |
| deadnix | nix/overlay.nix:17, nix/overlay.nix:30 (`final`) | accepted — overlay convention, symmetric with `prev` |
| deadnix | templates/hermes-skills.nix:6 (`pkgs`), templates/skills-refresh-timer.nix:25 (`inputs`) | accepted — template arguments stay complete so an edit does not start from a broken signature |
| statix | flake.nix:29 (assignment instead of inherit) | deferred |
| statix | nix/overlay.nix:11 (`{ }`) | deferred |
| statix | nix/tests.nix:332 (eta-reducible) | **fixed by this change** |

The repository-wide check is not clean, and this record does not claim it is.

## Secret scan (task 5.1)

The allowlist names the two fixture *values*, not their paths: the fake `inf_…` credential in the
secret-probe tests and the placeholder 40-hex SHA in the sanitiser's usage example. By value, a
real secret added to either file still fires.

Before: 296 findings. 293 were in `.review-council/` — 76 MB of gitignored run scratch that the
probe walks because it scans the working tree — and 3 were the fixtures. The scratch is deleted;
after the allowlist, **0 findings**.

## adhoc-packages (task 5.2)

zizmor 1.30.1 reports `help[adhoc-packages]` at `.github/workflows/ci.yml:268`, low severity, high
confidence: a global install outside a lockfile.

Mitigation applied: `--ignore-scripts`, verified not to break the CLI (installed 1.15.0 into a
prefix, `openspec --version` and `list --specs` both behave). The shipped template carries the
same flag, since it is the command other repositories adopt.

Residual, accepted with its bound: a version pin closes **drift** — it cannot resolve to a
different release tomorrow — but not **registry substitution** (a compromised registry serves
different bytes under the same version) and not **transitive dependency drift** (the install has
no lockfile). The bound is the job: `permissions: {}` at workflow level and `contents: read`
here, so the blast radius is a runner and a read-only checkout, with nothing published or signed
from it. Closing the residual properly means a committed lockfile plus `npm ci`, which is a
dependency-management change rather than a gate change.

## What this change deliberately does not do

- It does not add a `nixfmt --check` assertion. Five files would fail today; adding the assertion
  before formatting them would turn the gate red for debt this change did not create. Recorded
  above instead, and the assertion is the natural next change.
- It does not parse YAML for the runner label, for the reason given above.
- It does not touch `bootstrap.sh`'s message or the npx form in AGENTS.md, which is a dev-shell
  command, not a CI step.
