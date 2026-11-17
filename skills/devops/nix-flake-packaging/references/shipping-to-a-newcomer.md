# Shipping to someone who has never seen it

The always-on rule is in the skill body: **the flake is the interface.** This file
is the depth behind it — the traps a URL user hits, what a helper script may still
do, and what it must never get wrong.

## If you do add a checker script

Bash only, at the repo root, executable, no dependencies beyond a POSIX shell. It
reports what the machine has and **refuses** rather than guessing. It is not a
second interface: it prints the `nix run` line it executes, and it stops with one
instruction when something is missing.

**Check the prerequisite you cannot supply first, and answer it with one command.**
If the tool depends on something external, that is the failure that stops people —
so it is the first check and the message is the install line, not a stack trace
later. Everything else the script can find or point at.

**Validate an explicit path, do not take it on trust.** A tool that refuses an
unanchored session for good reasons will accept whatever path you hand it, so an
entry point that passes one through silently undoes that refusal — `./start /tmp`
reviews `/tmp` and writes its scratch directory into it. Refuse a directory with
no repository and no project marker.

**Warn before the expensive thing, not after.** If the default action spends
money, calls an API, or runs for minutes, say so before it starts and name the
flags that look first (`--dry-run`, a one-round variant, a cheaper mode).

**Make every refusal a check.** The refusals are the contract, so assert them in
the gate: shellcheck the script, run it with an EMPTY `PATH` (the machine it is
written for), and require a non-zero exit for an unknown option, an invalid value,
a missing path and a non-project directory. Name `bash` absolutely in that check —
an empty `PATH` cannot find it.

**Do not wrap the entry point in `writeShellApplication`** if it deliberately
avoids `set -e` (a bootstrap has to let each check fail and be reported, rather
than aborting before it can say what is wrong): the wrapper prepends `set -o
errexit`. Run shellcheck as its own check instead.

**Surface the caveats where the user asks, not where they are stored.** A
calibration or configuration file's own warnings are read by nobody. The
`doctor`/`status` command is where someone asks "is this machine ready?", so the
caveat that decides whether the output means anything belongs there — by default,
not behind a flag. A newcomer who runs the tool, sees a failing result and
concludes it is broken is the failure that prevents.

**A store path breaks path-based detection.** If the framework runs from
`/nix/store`, `__file__`-relative comparisons can never match the user's checkout,
so "is this the repository I was calibrated on?" always answers no. Prefer naming
the thing ("calibrated for the X repository") over detecting it, because a
detection that is always wrong is worse than none.

## What the checker is allowed to do

`nix build <url>#<pkg>` exports any output without a clone, so the script's job is
only the cases the flake cannot cover:

1. **nix is not installed.** Say the one install command and stop. Nothing else
   can help, because every other route needs nix once.
2. **a check before a run.** Report what is present, and refuse a target that is
   not a project.

And it should **print the `nix run` line it executes**, so someone who outgrows the
wrapper already knows the command.

### `nix run` runs from a read-only STORE COPY

The single worst bug in this area: resolving "this repository" against the
framework's own location. Under `nix run` — and from a flake URL especially —
`BASH_SOURCE`/`__file__` points into `/nix/store/…-source`, a frozen snapshot. A
script that defaults to it will review the *framework*, not the user's project,
and from a non-project directory it will happily start a full run of it.

Two rules follow:

- **Never default to the framework root.** Default to the working directory, and
  validate it.
- **Better, pass nothing and let the tool resolve it.** `nix run` **preserves the
  caller's cwd** (verified), so a program that resolves its own project from cwd
  works correctly through the flake — and that resolution is already written and
  already tested. Only an *explicitly named* path needs validating here.

### A private repo breaks `github:` URLs

`nix run github:owner/repo` gets a **404** for a private repository — GitHub
answers 404 rather than 403 to an unauthenticated request, so it looks like the
repo does not exist. Options, in order of how little the user has to do:

- **make it public** — `nix run github:owner/repo` then works with no setup, which
  for a tool meant for strangers removes every remaining step;
- `git+ssh://git@github.com/owner/repo` — works whenever the user's `git clone`
  works, i.e. whenever they have an SSH key on the account;
- `access-tokens = github.com=<token>` in `~/.config/nix/nix.conf`, after which
  plain `github:` works.

Document whichever applies, and say why, because "404" reads as a broken repo.

### Do not advertise a system nixpkgs has dropped

Listing `x86_64-darwin` while pinned to nixpkgs 26.11 made `nix flake show` **error
out** instead of listing anything:

    error: Nixpkgs 26.11 has dropped support for x86_64-darwin.

which is the worst possible first impression, since `flake show` is what a URL
user runs to see what is on offer. `nix flake check` had only ever *warned* that
the system was "omitted", so nothing failed loudly enough to notice. Keep the
`systems` list to what the pinned nixpkgs actually supports.

### Confirm the URL actually sees your new commit

`nix` caches the fetched flake, so `nix run <url>` immediately after a push can
still evaluate the PREVIOUS revision — and the test then "passes" against code you
already changed. Use `--refresh`, and compare the revision rather than assuming:

    nix flake metadata <url> --refresh    # Revision must equal your local HEAD
    nix run <url>#app -- --help

A `path:` input is the same trap one level down: it is pinned by narHash in the
consumer's `flake.lock`, so a consumer flake keeps testing the locked revision
until `nix flake update <input>` — silently, and while reporting a pass for code
you have already fixed.

## A preflight that reads host state makes tests host-dependent

Adding a check that refuses a run when a prerequisite is missing is right, and it
will break the test suite in a way that looks like a sandbox problem. It is not.

The measured case: the loop refuses when its two agent profiles are absent. The
tests stubbed the binary lookup, so the home-directory resolution fell through to
the **developer's** `~/.hermes` — where the profiles were installed. Locally 309
passed; in the nix sandbox, where no home exists, **23 failed**.

So the rule: a test that exercises a run has to provide the run's preconditions,
exactly as a real machine does. Give it a temporary home with the profiles in it.
Do not weaken the check, and do not special-case the test — a suite that passes or
fails depending on what the developer happens to have installed is not testing the
code.

Reproduce it cheaply before believing it is a sandbox quirk:

    env HERMES_HOME=/tmp/empty-home pytest tests/ -q     # the sandbox condition
    env -u HERMES_HOME pytest tests/ -q                  # no home at all

Both must pass. If only one does, something is reading ambient state.

## A guard on the run path must not cost more than it saves

A preflight runs on EVERY invocation, so its own cost is on the critical path.
Time the entry point before and after adding one — a check that reads host state
can spawn a subprocess, and that is invisible until measured.

Measured: resolving the agent's home directory by asking the tool
(`hermes profile show default`) cost **~550 ms**, against **0.01 ms** for reading
it from the environment or a default location. Called once per run, it was 90% of
a `--dry-run` that had been 60 ms.

The ordering rule that follows, and it is NOT the same as the one a writer needs:

- **A writer asks the tool first.** An installer needs the authoritative value
  because it is about to write into it, and a wrong answer creates files in the
  wrong place.
- **A checker tries the cheap local answers first** and keeps the subprocess as a
  last resort — it only needs to know whether a directory exists.

Keep the last resort, because it is what makes a non-standard location still work,
but order it last and say in the comment why the order differs from the installer's.
Two functions that resolve the same thing differently look like a bug until the
reason is written down.

### Reordering a fallback chain needs a test for the branch you moved

The reorder is precisely the change that silently breaks the case the fallback
existed for: the cheap paths now answer first, so the expensive branch only runs in
the situation you cannot reproduce by accident. Cover both directions:

- one test that the cheap path WINS and spawns nothing — otherwise the reorder
  bought nothing, and a later revert costs the same 550 ms back unnoticed;
- one test that the last resort is REACHED, with the cheap paths stubbed away.

And the fixture must satisfy the code's own validation: a resolver that checks
`is_dir()` will correctly reject a test naming a home directory it never created,
so the branch stays unproven while the test looks like it covers it. Create the
resource, then assert on it.

## A partial setup must name the step it cannot do

An installer that completes part of a setup and stops has to say what is left, in
its own closing output, or the user meets the remainder later as an error that
looks like a bug. Measured: the profile installer created both agent profiles and
never mentioned that credentials are stored **per profile** and are not shared, so
the council could not reach a provider and the failure surfaced as a provider
error with nothing pointing at the skipped step.

The general rule: when a tool does the automatable half of a setup, print the
manual half as numbered commands before exiting — and say *why* it is manual. If
the step is genuinely copyable (a config block the user already has elsewhere),
consider doing it for them; a step you can automate and do not is friction you
chose.

## A tool that installs itself has to install every half

A setup verb that installs *part* of the tool leaves the newcomer with something that
looks finished and is not. Measured: the first-run verb created the agent profiles and
stopped, so a user following the documented path got a working CLI and **no agent
command** — the skill that makes the slash command exist had no installer at all. The
operation existed, but as a dev-only verb, so the shipped surface could not reach it.

Two rules:

- **The first-run verb does both halves**, in the order that needs the least to already
exist: the skill first (it carries the framework, and it is what a machine with neither
nix nor docker runs everything else from), then the profiles. Keep the sub-verbs
(`setup skill`, `setup bots`) so either half can be re-run alone.
- **A module reachable from a user verb must ship.** If the installer's module is
dev-only, the shipped app cannot run its own first-run path — and a scope check asserting
"no dev verb's module is in the shipped tree" is what catches it, which is the point of
asserting it.

**Resolve the install destination from the live config, and document the precedence.** A
skill installs into the configured external library when there is one, and into
`<HERMES_HOME>/skills/…` otherwise. The trap is that the local copy SHADOWS the mounted
one, so installing to both leaves two copies diverging silently — the agent loads one
while the installer updates the other. Ask the tool for its own configured mount rather
than guessing a path, and warn when you fall back to the local one.

**Verify the install from a scratch home.** Your own home is populated, so a missing
installer or a wrong destination is invisible there — the thing works because something
else already put it in place. Point `HERMES_HOME` at an empty directory, run the
documented first-run command, and assert on what actually landed: the file count, the
subdirectories, and that the installed copy can then run ITSELF with no clone and no nix.
A deployment is also not a copy — it lags silently — so give the user the re-install verb
and a drift check, and say that the deployment must be re-synced after the source changes.

## Name the cause, not the symptom

A run that fails because a prerequisite is missing must say which prerequisite.
The measured case, with no profiles installed:

    convening 1 generalist x 1 samples…
      0/1 sample(s) readable; findings per dimension: all zero
      security  rc=1  NO FILE          (all five dimensions)
    OUTCOME: ESCALATE
    reason:  gate could not evaluate the run (missing/unparseable reviewer output)

Every sample failed for one reason, and the reported reason is what the failure
looked like from the outside. A newcomer reads that, does not know what to install,
and concludes the tool is broken — after paying for the samples that failed that
way. Check the prerequisite **before** spending anything and before the run
directory is created, so a refusal writes nothing.

Make `--dry-run` run the same check. Then it answers "will this work?" rather than
only "what is the plan", which is what someone actually wants before their first
run.

## First run: guided, and actually configurable

The first-run verb is the one thing a stranger runs before they trust anything, so it
carries two separate obligations: ask the few questions that are theirs, and make the
answers editable afterwards.

**An interactive setup must never hang.** Detect a real terminal (`stdin.isatty()`); with
no tty — a container, CI, a piped stdin — take every default, say that you did, and
continue. A prompt that blocks fails the tool at exactly the moment someone is evaluating
it, and `docker run` is where that happens. Treat EOF as "accept the default" rather than
an error, and offer `--yes` for the interactive case.

**Show the summary before doing anything, and let `--yes` skip the questions rather than
the report.** What will be written, what will be installed, and where — as a list, before
the write. Then `--yes` means "I trust the defaults", not "do something I have not seen".

**Re-running is "change one thing", not "answer everything again".** Seed every prompt
with the current effective value, so the second run is a single edit. A wizard that starts
from scratch each time is a wizard people stop running.

**Validate the whole configuration and report every problem at once.** Dying on the first
error turns a five-line fix into five round trips. And refuse the combination the
architecture cannot survive: if the design depends on a capability NOT being present (no
fan-out, no delegation), a config that adds it is an error rather than a preference —
validate the invariant, not just the types.

**Ship ONE config file, and prove something reads it.** The failure this guards against is
the worst kind of configurable: a value declared in a file no code parses. It looks
editable, the user edits it, and nothing changes — measured on a capability set declared in
one file while the installer hardcoded its own copy, so editing either had no effect. Two
rules: the declaration and the read must be the same code path, and a test must assert that
editing the file changes the installed result. A declaration nothing reads is worse than no
declaration, because it advertises a control the user does not have.

**Pick the config format the bare interpreter can parse.** If the tool must run on a stock
interpreter with no third-party packages, a YAML config needs a dependency the tool
otherwise does not have — and the failure is a hard stop on a machine that was working a
moment earlier. `tomllib` is stdlib from 3.11, parses with no dependency, and keeps
comments, which a config a human edits wants. Choosing YAML there buys nothing and costs
the whole first-run path.

**Round-trip the file through the reader before writing it.** Hand-rendering a config is
the natural way to keep the comments that make it usable, and it is also how you emit
something your own parser rejects — at which point every later command fails on a file the
tool itself wrote. Parse the rendered text inside `write()`, and assert the round-trip in a
test including a value with a quote and a backslash.

**A default must be usable on a machine that is not yours.** No provider, model, key,
hostname or home directory in a shipped default: those are the user's to set, and a default
naming one makes the tool silently wrong for everyone else. Where a value has a sensible
"unset" meaning, spell it (`""` = inherit) and document it, rather than letting a shipped
default pin a choice the user did not make.
