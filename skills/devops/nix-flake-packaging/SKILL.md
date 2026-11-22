---
name: nix-flake-packaging
description: "Use when exposing a repo's scripts as Nix apps/packages."
version: 1.2.0
author: Storm, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
category: devops
metadata:
  hermes:
    tags: [nix, flake, packaging, apps, checks, cli]
    related_skills: [nixos-clan-flake, deterministic-quality-gates]
writes: [none]
side_effects: [none]
---

# nix-flake-packaging

**Runtime.** Podman; `docker` is the accepted substitute — the policy and the differences that bite are in `docs/runtime.md`.

Turning a repository's own commands — Python and shell scripts — into a pinned Nix
surface: `nix run`-able apps, packages, checks, a devShell and a formatter, all from
one `flake.lock`.

For a NixOS **system** configuration flake, or anything crossing the Windows/WSL
boundary, use `nixos-clan-flake`; it owns the boundary and the FOD rules. This skill
owns the flake's **outputs**.

## When to Use

- "Make this repo runnable the Nix way" / "expose it as `nix run`".
- A script repo has no flake, or a flake with only `devShells` and no `apps`.
- Adding, renaming or regrouping a command in an existing tooling flake.

## Rules (always on)

**One app with verbs, not N top-level apps.** Thirteen sibling apps
(`tool-gate`, `tool-doctor`, `tool-ablate`, …) make every operation look equally
important, including the ones a normal user never runs, and they crowd
`nix flake show` until the common path is invisible. Ship **one** app whose first
argument selects the verb; run it bare and it prints the verb list, so the no-argument
case is informative and cheap. Reserve a second app only for something genuinely
unrelated to the first.

The same problem recurs INSIDE the single app, in the verb list itself:

- **Sort it by who needs it, not alphabetically.** Alphabetical order puts the one verb
the tool exists for fifth of twelve, next to five nobody will ever run — the list is
then a wall rather than a signpost. Group it (`START HERE` / `ALSO USEFUL` / `ADVANCED`)
from a field in the verb table, so the ordering is generated and cannot drift.
- **A verb with sub-verbs should make its bare form DO the common case**, not error with
a list of choices. `tool setup` answering "expected one of: bots ci dispatcher
toolchain" asks the newcomer to guess which of four is the first-run path; the bare
verb performing it is strictly better, and the sub-verbs stay available.
- **A verb that is a prerequisite for everything else is a setup verb**, and the run
itself should refuse without it — see the preflight rule in
`references/shipping-to-a-newcomer.md`.

**Keep the implementations separate; unify only the interface.** Different scripts take
different arguments and are tested separately — that is not a reason to merge them. A
dispatcher in front of them costs one case arm each and buys one name, one help page and
one namespace.

**The version comes from the package metadata; the flake must not restate it.** A
derivation's `version`, an image `tag` and a check asserting `__version__ == "1.2.3"` are
copies of `pyproject.toml` that no release check reads. Bind it once — `version =
(builtins.fromTOML (builtins.readFile ./pyproject.toml)).project.version;` — and feed the
package, the image tag and the check's expected value from that binding. Have `__version__`
read the installed metadata (`importlib.metadata.version("pkg")`) with a source-checkout
fallback, so the wheel cannot disagree with the tree that built it. A hardcoded image tag
is the one that ships silently: the package is 2.0.0, the image still says 0.1.0, and every
check is green because each copy is internally consistent.

**The flake is the interface — do not wrap it in a second one.** `nix run <url>`
is the distribution mechanism: nothing has to be cloned, and `nix build <url>#<output>`
exports any output. A bootstrap script that re-implements that is a second interface
which will drift from the first, and it invites the wrong question ("which one do I
use?"). When someone wants an easier entry point, the answer is the flake's own
surface plus a **checker** that reports what is missing and prints the `nix run` line
it would execute — never a parallel command set. A wrapper is justified by exactly two
cases: the tool that is not installed yet, and a pre-flight check.

The same holds one level up, for a LOOP. If the host agent already ships a continuation
primitive — a standing goal judged each turn, with a deterministic **quality gate** that
must exit 0 before the goal can be judged done — drive that instead of re-implementing
iteration inside the tool. The tool's own gate becomes the gate command, so the decision to
stop is a command's exit code rather than a model's opinion, and pause/status/subgoal/turn
budget come for free. A bespoke loop re-earns none of that, and drifts from the primitive
the user's agent already understands.

**Make a scope field load-bearing, or delete it.** A field like `audience = "user" |
"dev"` is worth having only if something *checks* it: assert that a dev-only verb is
rejected by the shipped app and accepted by the devshell. Otherwise it is a comment that
will drift, and dev-only commands leak into the user surface.

**A verb's scope and its module's shipping are the same fact.** The check that keeps
dev verbs out of the shipped app is also what forbids a dev verb's module from being in
the shipped tree — so an operation that must be reachable from the **user** surface
cannot also be a dev-only verb. When you need such an operation, promote it: move the
module into the runtime set, give the verb one name on the user surface, and **retire
the dev alias rather than keeping both**. Two names for one operation is exactly the
redundancy the scope field exists to prevent, and the scope check rejects the
arrangement anyway — the module is either shipped or it is not.

**Intercept `--help` on every verb that acts.** A verb whose script parses arguments can
pass `--help` through and show that script's own help. A verb whose script **does**
something rather than parsing flags has no argument handling at all, so `tool export
--help` silently *runs the export* — and a setup verb's `--help` may perform an
installation or a network registration. A `--help` that does something is a trap, not a
help. Answer it in the dispatcher for those verbs — and give a verb GROUP its own `--help`
that lists its sub-verbs rather than erroring. A check that probes every verb's `--help`
reaches the group too, so `tool setup --help` answering "expected one of: a b c" on stderr
with a non-zero exit turns a passing surface into a failing build.

**Name the interpreter in the wrapper; never rely on the executable bit.** Write
`exec python3 <path>` / `exec bash <path>` rather than depending on the shebang and the
mode, so a store copy that lost `+x` still runs.

**A command the app prints for later execution must not assume the app is on `PATH`.**
When a verb emits a command that a *different* process will run — a scheduled job, a
spawned worker, a task-card body, a cron entry — resolve it from the artifact's own
location (`nix run <root>#app`, or the running interpreter plus the script's own path)
and quote the paths. The consumer's `PATH` is not yours: a command that works in your
shell fails on its first line under a daemon, and a bare interpreter name may not exist
there at all (a NixOS host has no system `python3`). Resolving it also keeps the emitted
command correct from a checkout, a store path and a handoff bundle alike.

**A verb a background process must run belongs in the user scope.** The shipped app is
what a daemon, scheduler or spawned worker can reach; a devshell-only verb is not on
their `PATH` and no devshell is active for them. If the durable or scheduled path needs
a verb, the scope split has to include it even when a human would call it a maintainer
tool — check the audience of every verb you are about to emit into a generated command.

**Mirror the repo layout in the tree derivation.** If the scripts resolve their own root
as `dirname(__file__)/..`, a store copy must have the same shape (`scripts/` beside the
other directories they reach). Anything a script reads relative to *itself* has to be in
that derivation; paths concerning the repo **under review** must not be, so they arrive
as arguments. That separation is what lets the tree live in a read-only store path.

**Mirroring the layout is not copying the repo: ship only what runs.** A tree derivation
that copies `scripts/` wholesale, plus `tests/`, `pyproject.toml`, the README and the flake
files, ships a suite and a development surface nothing at run time reads — and every
dev-only verb the dispatcher refuses by scope is still a file inside the image. Make the
module set an **explicit list in the flake** (`runtimeModules` / `devModules`) and
parameterise the derivation by scope, so the shipped tree and the devshell's tree come from
one expression with a different audience — the same split the verb table already expresses.
Then assert it from the app's own table: fail if a user verb's module is missing from the
shipped tree, if a dev verb's is present in it, or if the tree carries `tests/`,
`pyproject.toml`, the README or the flake files. The list plus the check is what stops the
manifest rotting into a comment.

**Bake the resolved environment into the wrapper, so the tree needs no flake.** A script
that falls back to `nix build <tree>#toolchain` when nothing tells it the store path is the
reason the tree derivation had to carry `flake.nix` and `flake.lock` at all. Export the
path from the generated launcher instead — it is the store path the build already fixed, so
the two agree by construction rather than by coincidence — and the copy drops the flake
files, needs no writable store, and cannot resolve a different toolchain than the one it
shipped with.

**A module is not a program: guard the direct invocation.** When the repo's scripts are
reachable both as verbs of the CLI and as files on disk, `python3 scripts/<name>.py`
bypasses everything the wrapper provides — the pinned `PATH`, the scope filter, any
preflight — and several of those files *act* (install into a home directory, prune a
deployment, rewrite a repository they are pointed at, spend real agent turns). Have each
module's `__main__` refuse unless a variable is set that **only the dispatcher sets**, and
have the refusal name the verb to run instead. Three details decide whether it works:

- **Guard in `__main__`, never at import.** The suite loads these files as libraries and
  calls their entry points directly, which is not a hand-run; an import-time guard breaks
  every such test, and the tempting fix is then to weaken the guard.
- **Let children inherit the variable.** The dispatcher's own subprocess fan-out (a probe
  runner, a scorer) has to keep working, so the variable is inherited rather than
  re-established per process.
- **Check BOTH directions — an over-eager guard is as broken as none.** One check asserts
  that a direct invocation is refused AND that the same verb through the CLI succeeds. A
  test that walks every module's `__main__` for the guard, and fails when the verb it names
  is not one the CLI exposes, is what keeps the message pointing at a verb that exists.
- **Re-grep the docs whenever the guard changes.** Adding or widening a guard silently
  invalidates every documented command that hand-runs a module: a line reading
  `python3 <dir>/scripts/<module>.py` now exits 1 with the refusal, and nothing fails until
  a user follows the instructions — the suite does not exercise prose. Sweep the README, the
  docs and the shipped skill for an invocation of a guarded module and route each through
  the CLI. The same sweep catches the mirror image: a module reachable from a user verb but
  still listed as dev-only, which the scope check flags once the module is made to ship.

A single-sided guard is the failure to watch for: it looks like security and is a
regression, and only a check that runs the verb through the CLI can tell the two apart.

**Every check must be able to fail.** A check ending in `|| true`, or one that only
asserts its own exit status, prints "all checks passed!" while verifying nothing — and is
worse than no check, because it is trusted. `nix flake check` is the one command a
contributor runs before pushing, so it must carry the real gates: the suite, the linters,
the formatter check.

**Prove a new check can fail before trusting it.** A check that has only ever printed
green is a hypothesis about the regex, the path or the glob, not evidence. Plant the
violation it is supposed to catch, watch it go red and name the offending file, then
remove it. This costs one command and is the only way to tell a working gate from a
vacuous one — and a structural convention is exactly the kind of check worth adding:
"no shell scripts in the tree", "no `.sh` in the image", "every verb's script exists"
are all one command, and they turn a convention into a property of the build.

**Add a check for the command surface itself.** A wrapper pointing at a renamed script
fails only when a user runs it. One check should assert that every verb's script exists in
the tree, that every verb starts, and that the scope split holds — the three breakages a
diff cannot show.

Drive that check from the app's OWN verb table, not a second copy of it. A table written
out in the flake drifts from the one the app dispatches on, and the drift is invisible: a
verb exists in the CLI, is missing from the checks, and nothing verifies that its module
ships or that its `--help` works. Have the app print its table as JSON (`<app>
--verbs-json`) and iterate that, so one table cannot disagree with itself. Two traps in the
iteration:

- **`for v in $(cmd)` word-splits.** A two-word verb (`setup bots`) becomes two iterations,
so the check exercises `setup` and `bots` instead of the verb — it passes while testing
something that is not a verb. Read whole lines: `while IFS= read -r v; do … done < file`.
- **A loop fed by a PIPE runs in a subshell**, where `exit 1` cannot fail the build, so the
check reports success whatever it found. Redirect the command's output to a file and read
the file.

Both traps fail OPEN — a green gate over an unexercised surface — which is why they belong
next to "prove a new check can fail": the proof is what catches them.

**`writeShellApplication` for the wrappers.** It gives `set -euo pipefail`, a
**build-time shellcheck** pass, and `runtimeInputs` — which is how the pinned toolchain
gets on `PATH` at exec time, so `nix run` needs no devshell. A pure nix shell has no
coreutils, so add `bash`/`coreutils`/`gnused`/`gnugrep`/`findutils`/`gnutar`/`gzip` for
any shell script; `dirname` and `sed` are load-bearing in almost all of them.

`runtimeInputs` is **prepended** to the inherited `PATH`, not a replacement for it — which is
what lets a wrapped command still find a binary the *user* has (their agent CLI, a git remote
helper) while the pinned toolchain takes precedence over any same-named system one. Do not
work around a missing tool by adding it to `runtimeInputs` if the caller is supposed to supply
it; that pins a version the user did not ask for.

**Pin the inputs; do not model an effect as a derivation.** Build the whole tool set as
ONE derivation resolved from ONE nixpkgs input, so it moves atomically with a single lock
revision. But a command that spawns network calls, agents, or other non-reproducible work
is an **effect, not a build** — wrap it as an app and keep the interface pinned, rather
than faking a sandboxed derivation. The same goes for float arithmetic and AST
manipulation: a build system is the wrong engine, and the wrapper is the right answer.

**A repo that is the source of a deployed artifact is not finished until the artifact is
re-synced.** A skill the agent loads, an installed package, a published image — each is a
copy, and a stale copy is silent: it keeps running the old code and reporting the old
behaviour with nothing to say a newer version exists. After changing the source, run the
sync and confirm its own drift check comes back clean. Prefer a sync that MIRRORS over one
that only copies: a copy-only sync leaves files the source deleted in the artifact
forever, and a downstream step that keys off the set then re-runs or re-installs them.
Treat "the tests pass" and "the deployment is current" as two separate claims — the first
says nothing about the second, and the gap only shows up when someone uses the artifact.

**A sync that cannot find a file it is supposed to install must REFUSE, not skip.** A
copy step written as `if exists(src): place(src)` with no else is a silent skip: the
artifact keeps whatever it had, the drift check under-reports, and the gap is invisible
until someone uses the stale copy. It bites hardest when the derivation *deliberately*
excludes a file the artifact still needs — a tree that ships only what runs carries no
flake files, so a sync run from that tree finds nothing to install and installs nothing,
forever. Two halves to the fix: stage the excluded files as their own small derivation
output and export its path from the generated launcher, so the source reaches the sync
from **every** entry point (checkout, devshell, image); and have the sync exit non-zero
naming what it could not find. A prune has the same failure mode — deleting a file the
source lacks and printing nothing leaves "it is gone" as the only evidence — so print
every removal, not just the ones `--check` reports.

## Shipping it to other people

Two topics have their own reference, because they are depth rather than always-on
rules:

- **`references/shipping-to-a-newcomer.md`** — **the flake is the interface.** Why
  `nix run <url>` beats a bootstrap script, what a private repository does to a
  `github:` URL, why `nix run` executes from a read-only store copy (and what that
  breaks), and the narrow cases a checker script legitimately covers.
- **`references/container-image.md`** — building the image from the flake instead
  of a Dockerfile, the `dockerTools` traps that fail at build time, and what a
  read-only store does to a toolchain that resolves itself.

## A tool is a package, never an install at run time

`pip install`, `uv pip install`, `npx`, `npm install -g`, `cargo install` and `curl ... | sh`
resolve a package at run time, from the network, at whatever version the registry serves that
day. On a Nix host that is a second, unrecorded pin: `flake.lock` describes the system, the
install command describes nothing, and the tool it runs is not in the store.

Check nixpkgs first -- `pkgs.<tool>`, `python3Packages.<module>` -- and either run it for one
command or expose it as an app, so the reference is a flake output rather than a package manager:

```nix
packages = forAllSystems (pkgs: { openspec = pkgs.openspec; });
apps = forAllSystems (pkgs: {
  openspec = { type = "app"; program = "${pkgs.openspec}/bin/openspec"; };
});
```

```sh
nix shell nixpkgs#python3Packages.websockets -c python verify.py   # a module, for one command
nix run nixpkgs#uv -- venv .venv                                   # a tool, not a global install
nix run .#openspec -- validate --all --strict                      # this flake's own app
```

Only when nixpkgs has no expression is packaging the tool the answer: `buildNpmPackage` with a
lockfile and an `npmDepsHash`, or `fetchFromGitHub` plus `pnpm.fetchDeps` for a pnpm repository.
Both are pinned, offline after the first fetch, and cached -- `npx` and `pip install` are none
of those.

A library that teaches others holds itself to this too: `docs/provisioning.md` in this repository
is the policy, and its gate fails a fenced install line that is not marked
`# nix-provision: <reason>`.

A version literal earns its place only as an assertion against the flake (`pkgs.<tool>.version`),
so a nixpkgs bump fails the gate instead of silently changing the tool that runs.

Read that version through the flake, not through the CLI's registry channel. `nixpkgs#<tool>` on
a command line resolves by the **flake registry**, not by this project's `flake.lock`, so it can
report a different version than the tree will build with — measured, `nix eval
nixpkgs#openspec.version` said 1.13.1 while the repository's own locked `pkgs.openspec.version`
was 1.14.1. Use `nix eval --raw .#packages.<system>.<name>.version` before writing the value
into a pin the gate asserts, or the assertion encodes the registry's answer and fails on the
first `nix flake check` — which is how the wrong literal was caught here.

## Pitfalls

- **Every flake output — `nix build`, `nix run`, `nix flake check` — reads the git-TRACKED
tree, not the working tree.** A file that is not yet `git add`ed is invisible to all of them.
For a check, a verb naming it fails with `framework is missing scripts/<name>` while the file
sits on disk looking fine. For a build the symptom is worse because the build SUCCEEDS: the
package ships without the new module and the installed binary tracebacks at run time
(`ModuleNotFoundError`) while the suite, run from the checkout, was green. Stage before you
check or build (`git add -A` first) — otherwise you tested the previous revision while
appearing to test the new one, which is the same trap as editing on the Windows side of the
boundary: a confident wrong answer rather than an obvious failure. Do not report a gate or an
artefact as verified from a run made before staging, and when a newly added module is missing
at run time, check `git ls-files` before debugging the import.
- **`nix flake check` prints "running 0 flake checks … all checks passed!" on a cache hit.**
The line to read is the count, not the verdict: zero means every check derivation was already
in the store, so nothing executed and the run proves content identity rather than behaviour.
Legitimate for an unchanged tree, worthless as evidence for a changed one. Force execution
with `nix build --rebuild .#checks.<system>.<name>`: `nix flake check` itself rejects
`--rebuild`, and `--rebuild` errors out when the changed derivation was never built — so build
it once plainly, then rebuild. Quote the count when reporting the gate, and re-run it after
staging.
- **A `path:` input is pinned by a lock, so a consumer keeps testing the revision it locked.**
A test flake taking the project as `inputs.<name>.url = "path:/…/thing"` records that input
in its OWN `flake.lock`, and the check then builds the source as it was when the lock was
written — every assertion passes, against the pre-refactor tree. Run `nix flake update
<input>` after changing the project, or use `git+file:` so the tracked revision is explicit.
The signature is an assertion failing on a path or symbol you can see with `ls`: suspect the
lock before the code. The same trap one level up, for a `github:` URL the fetcher has cached,
is in `references/shipping-to-a-newcomer.md`.
- **A `case` pattern containing a space must be quoted.** `setup bots)` is a shell syntax
error; `"setup bots")` is a valid pattern. A nested dispatcher usually matches the
SUB-verb, so keep the pattern and the human-readable label as separate values.
- **`lib.mapAttrsToList` passes `(name, value)`.** A two-argument function handed to it
bare is applied to the attribute name, so the value arrives as the first parameter and
eval dies with `cannot coerce a set to a string`. Write the lambda out.
- **`nix flake show` reads `meta.description` from the APP entry**, not from the
derivation. Setting it only on the package leaves every app reporting "no description".
- **statix flags `lib = nixpkgs.lib;`** as "assignment instead of inherit". Write
`inherit (nixpkgs) lib;` and update the references to it.
- **A toolchain join cannot supply transitive Python deps.** Joining
`python3Packages.pytest` yields `site-packages/pytest` with no `pluggy`, so
`python3 -m pytest` dies even though the `pytest` wrapper works. Join a
`python3.withPackages (ps: [ … ])` environment instead, and keep a check that imports
the packages.
- **A directory-by-directory mirror between two clones silently misses a directory.**
Copying `docs scripts tests .github` and the root files looks complete and is not: the
first pass left `skills/` behind, so the commit carried the old skill file while the
working tree had the new one, and `git status` was clean because the *mirror* was what
got committed. Verify with a recursive diff (`diff -r -q --exclude=.git <clone-a>
<clone-b>`) before committing, and treat a non-zero result as a failed mirror rather
than as noise -- the diff is the check, not the copy step. Two related traps in the same
flow: a stale `.git/index.lock` makes `git add` fail while the rest of the script runs
on, so the commit captures whatever was already staged (check for a live `git` process,
then delete the lock); and a commit made against a partially staged index passes
`nix flake check` only if the missing file is not one the checks name -- which is how
`framework is missing scripts/hermes_home.py` becomes the first sign that the tree under
test was never the tree you edited.
- **Two clones of one repo can diverge in BOTH directions, so a fast-forward is not always
possible.** One side holds a commit the other lacks and vice versa: `merge --ff-only`
refuses, and `reset --hard` would discard work. Check the direction first (`git log --oneline
<other-head>..HEAD`, and the reverse) before deciding, then reconcile through a bundle —
`git bundle create` on the side holding the commit, `git fetch <bundle> <branch>` on the
other, `git rebase FETCH_HEAD` to lift the local-only commit on top. Fetch a bundle by its
distro path (`/mnt/c/...`), not `C:/...`, which git reads as an scp-style `host:path` and
reports as a permissions failure. Then confirm both sides agree with a recursive diff — the
rebase succeeding is not the same as the trees matching. Two more traps in the same flow:
**a scratch artifact written into the repo is committed by `git add -A`** — create bundles,
tarballs and logs in the scratch directory, never beside the checkout, and after committing
verify what actually landed (`git ls-files | grep <artifact>`) rather than trusting the
commit to have done what you meant; and **root-owned objects under `.git/objects`** (left by
an earlier root invocation) block every new write with `insufficient permission for adding
an object to repository database`, which names the symptom and not the cause — `chown -R
<owner> .git` and re-commit.
- **Editing on Windows while building in the distro tests the wrong revision.** If the
repo has a checkout on each side of the WSL boundary, `patch`/`write_file` land on the
Windows copy while every `wsl.exe … bash` command reads the distro's own clone. Copy the
file across before *every* command there, and copy it **back** after anything that
rewrites it in place — a formatter run reformats the distro's copy and the next edit then
lands on a stale file. Confirm by grepping the **distro's** copy for a string you just
added. The same boundary mangles line endings: a write through these tools on Windows
translates `\n` to `\r\n`, and a `.gitattributes` of `* text=auto eol=lf` normalises it
on commit so `git status` shows only `M` — the working tree is CRLF while every blob is
LF. On an LF-only repo, sweep for CRs before committing and verify the **blob**
(`git cat-file blob HEAD:<path> | grep -c $'\r'`), never the working tree.
Sweeping is detection; make the rule a property of the repo instead. Three versioned layers
cover the three moments a file is created, edited and committed: `.editorconfig`
(`end_of_line = lf`) so an editor writes LF before git sees the file, `core.safecrlf = true` so a
CRLF file cannot be staged, and `.githooks/pre-commit` (reached via `core.hooksPath`) that refuses
the file by name and prints the fix. Git does not track its own config, so ship those settings as
one script and say in AGENTS.md that a fresh clone runs it once — the
`.gitattributes` and `.editorconfig` halves need no setup at all. Note which side can enforce
what: a local gate that walks the working tree sees CRLF, while CI reads the tracked copy (already
normalised) and cannot, so a CI-only check does not cover this.

**A pre-commit hook is `sh`, so no `$'\r'`.** `${...}` and `$'..'` escapes are bashisms: under a
POSIX `sh` the pattern matches nothing and the hook passes silently on the file it was written to
catch. Build the character with `CR=$(printf '\r')`, and let git decide what is binary (`awk
'$1 != "-"'` over `git diff --cached --numstat`) rather than keeping a second extension list in
step with `.gitattributes`.
- **A check that probes an effectful verb.** `--help` on a verb that installs, exports or
registers will *do* it — so either the dispatcher intercepts `--help` for those verbs (the
rule above), or the check must skip them. Track which is which in the verb table rather than
deciding at each call site. Once every acting verb is intercepted, `--help` is safe on every
verb and the check can exercise the **whole** surface, which is strictly better evidence than
probing a subset. What must never happen is probing an acting verb *without* the interception:
the check would then perform an install while reporting a passing gate.
- **Naming a dev-only verb in user-facing output.** An error message, a warning or a
doc the tool prints is read by someone on the SHIPPED surface, so a verb that exists
only in the devshell sends them straight to a failure — `run tool calibrate` from a
warning was rejected by the shipped app with "not a verb, and no such path". Check
every command you emit against the audience of the surface that emits it, and give the
form that works there (a devshell invocation, or a user-scope equivalent). The scope
field makes this checkable; use it when writing the message, not only when writing the
dispatcher.
- **Enumerating a set by a hardcoded list.** An installer that names its members inline
silently under-installs when one is added — the new file lands in the repo, never reaches the
target, and nothing reports it. Discover the set from the directory, and **prune** what is no
longer there: a stale member is worse than an absent one when a downstream step keys off the
set, because the stale entry is still worked on and its result then silently dropped.
- **Self-hosting the gate on the author's own machine.** It can only repeat a result already
held, and it queues whenever the box is off — so it adds a failure mode without adding
evidence. See "Running the gate in CI".
- **`nix fmt` reflows the file, so a multi-line patch anchor stops matching.** A
formatter gate that runs on every check means `flake.nix` is re-laid-out underneath
you, and a `patch` whose `old_string` spans several lines then matches nothing — the
same failure as an out-of-date read, but caused by your own formatter rather than by
time passing. `nixfmt` in particular moves `++ x` onto its own line and expands
single-line lists, so a block copied from a pre-format read is stale by the next run.
Anchor edits on a SINGLE line and insert after it, or re-read the file immediately
before patching. This is not a reason to skip the formatter — it is a reason to
anchor on lines rather than blocks. **A single line is not enough when it carries
indentation inside a `''` string**: nixfmt re-indents the shell text of an embedded
script whenever the surrounding nesting changes, so an anchor copied with its leading
spaces stops matching. Match on the line's CONTENT and re-apply the file's own indent
(`line[: len(line) - len(line.lstrip())]`), or locate it by line number.

- **A system you cannot evaluate is not a system you support.** `genAttrs` over
  `[x86_64-linux aarch64-linux x86_64-darwin aarch64-darwin]` with a Linux-only dependency in
  the closure (`bubblewrap`, `systemd`, a kernel module) fails evaluation for the other two, so
  `nix flake check` dies before running anything and `nix flake show` cannot render. Gate the
  outputs per platform (`lib.optionalAttrs pkgs.stdenv.isLinux { … }`) and verify every system
  you advertise with `nix eval .#packages.<system>.default.drvPath`; an attrset that names a
  system it cannot build is a promise the flake breaks.
- **`nix build .#a` replaces `./result`, so a harness that shells to `./result/bin/x` breaks
  when `.#b` is built.** The symlink is one mutable pointer, not a handle: carry the store path
  (`out=$(nix build .#a --no-link --print-out-paths)`) in anything that builds one output and
  then runs it.
- **A helper script must not embed a `/nix/store/...` path.** A store path survives only while
  something references it; a literal pasted into a script is not a reference, so the next
  `nix-collect-garbage` deletes the tool out from under it. Resolve at run time (`nix develop
  --command …`, `nix build --print-out-paths`) or bake it into the wrapper the derivation pins.

## Procedure

1. **Inventory the commands** the repo actually ships, and group them: which a normal
   user runs, which only maintainers run. That split becomes the scope field.
2. **Write one table** of verbs (`script`, interpreter, scope, whether it parses `--help`,
   one-line description) and drive the app, the devshell, the checks and the usage text
   from it. One table is what stops a verb existing on one surface and not another.
3. **Build the toolchain** as a single derivation with an inventory file beside it, so the
   pinned set is inspectable (`nix run .#inventory`).
4. **Build the tree derivation** mirroring the repo layout, excluding bytecode caches.
5. **Generate the dispatcher** per scope, filtering the verb table.
6. **Add the checks** — the repo's own gates plus the command-surface check.
7. **Run it, do not just build it**: `nix flake check --keep-going`, then each verb, then
   confirm an existing verb still reproduces the result it produced before the wrapper
   existed. A wrapper that changes a number is a broken wrapper.

## Running the gate in CI

The `checks` are the gate, so CI runs `nix flake check --keep-going`. *Where* it runs is the
decision that matters, and the intuitive answer is the wrong one.

**Put the gate on a hosted runner — a clean machine is the whole point.** The gate already runs
locally in seconds against the same store, so a self-hosted runner on your own box can only ever
**repeat a result you already hold**. It is local with extra steps, and it wears a green badge
while doing it. The one thing CI proves that local cannot is that the work survives on a machine
sharing none of your state; self-hosting destroys exactly that property.

Two consequences, both worse than the download cost they were meant to avoid:

- **Availability.** A gate that queues while your box is off is worse than no gate: it looks
  like verification is coming and never arrives. A hosted runner always runs.
- **Security, later.** On a private repo the risk today is small, but the moment the repo goes
  public or gains a collaborator, a self-hosted runner executes *their* pull-request code on
  *your* machine — and by then it is installed.

Keep a self-hosted installer only as a documented **alternative** for someone who cannot use
hosted runners — air-gapped, or on a plan where minutes are scarce: flip the job's `runs-on` and
drop the nix-install step, since that runner is the machine that already has nix and a second
install over the top gives two stores and a mystery.

**Measure the closure's substitutability before adding any cache — usually you need none.** The
intuitive move is to add a binary cache so the cold build is cheap. Check what is actually
missing first, because a toolchain built from ordinary nixpkgs packages is already served:

```bash
tc=$(nix build .#toolchain --print-out-paths --no-link)
nix-store -qR "$tc" | while read -r p; do
  nix path-info --store https://cache.nixos.org "$p" >/dev/null 2>&1 || echo "not cached: $p"
done
```

`cache.nixos.org` is nix's **default** substituter and Hydra has already built every stock
package, so the paths that come back missing are the ones this flake builds itself — the
`symlinkJoin`s and `withPackages` environments, which hold almost no bytes and build in seconds.
A measured toolchain of 238 paths typically has two missing. A cache there buys a download that
is already happening, and charges an account, a token, a repo secret, a repo variable and a new
failure mode for it.

**Do not assert the cold-build cost — measure it.** A claim like "CI would build N packages from
scratch on every push" is what makes a cache look necessary, and it is easy to believe without
checking: it assumes the packages need *compiling*, when prebuilt-and-publicly-served is the
normal case. The measurement above is three lines and settles it.

**Re-measure every number you repeat, including one you recorded yourself.** A figure in a doc,
a changelog or your own earlier summary is a claim, not a fact: an image size drifts the moment
the contents change, and a conclusion reached from reading code can be wrong in a way that
survives into later sessions as a belief. Measured twice in one pass: a documented image size was
9 MiB stale, and a "these two curves diverge" claim repeated from an earlier session was false —
the two agreed exactly, and re-deriving it was ten lines. Prefer the live value over the recorded
one, and when they disagree say which you measured; a retracted claim costs one line, a repeated
one costs the reader's trust in every other number beside it.

- **Keep the portability matrix hosted.** A job that must pass on three operating systems
  cannot move to one self-hosted Linux box, and it *is* the cross-platform guarantee. It is also
  the expensive job in quota terms: a private repo's allowance is measured in Linux-equivalent
  minutes and macOS minutes are multiplied tenfold (Windows twofold), so the macOS leg is most
  of the bill. Fine at tens of pushes a month — but check the multiplier before adding a
  platform.
- **If you do add a cache, gate the step on a repo variable, not on the secret.** A missing
  cache must cost minutes rather than fail the build, so make the step conditional on the cache
  *name* being configured — never on the token, whose absence would go red. Prefer a substituter
  (`extra-substituters` plus its public key, which needs no account at all) over a registry-style
  service: a cache is a download, whereas a registry adds an account dependency the repo does not
  need in order to be reproducible.
- **Warm a new cache from the machine that already has the store.** Push the toolchain's store
  paths from the box that has them built, rather than paying for the first hosted run to build
  everything.
- **Ship the recipe in the docs, not the workflow.** Code should carry the configuration you
  actually use; a step for a cache you measured as unnecessary is config nobody runs. Keep the
  how-to in the CI doc so an adopter whose closure *is* partly unsubstitutable can add it back.
- **Never take a credential through the conversation.** When a step needs a token the user must
  supply — a runner registration, a cache auth token — have them write it to a mode-600 file the
  script reads, or run the single command themselves, and delete the file afterwards. Pasting it
  into chat puts it in the transcript and in the agent's context permanently, for a value that is
  usually single-use and short-lived anyway.
- **When you reverse a decision, record the rejected reasoning beside the chosen one.** A
  configuration doc that silently changes its answer teaches nothing, and the old argument comes
  straight back. The next reader should not have to re-derive why. Once a release is tagged, put
  the correction in an `Unreleased` changelog section rather than editing the released entry —
  that entry is the record of what that release shipped.

## Adding a verb

One entry in the table. It appears in the help, joins the package, and is checked — no
other file changes. That is the test of whether the table is doing its job.

Three things a new verb does need, all of them **enforced rather than remembered**: the
module's `__main__` calls the dispatch guard, its filename is in the flake's scope list,
and `--help` is safe on it. If adding a verb takes more than that, the table is not doing
its job.

**A verb that reads a data file needs that file's directory in EVERY derivation that ships
the code.** The scope list enumerates *modules*, so a non-module asset — a JSON contract, a
rubric, a schema, a fixture — sits silently outside it. The checkout keeps working because the
file is right beside the script, so nothing fails until the shipped tree runs the verb, the
lookup misses, and a fail-closed loader reports every input as unrunnable: the symptom reads
as a broken tool, not as a packaging gap, and no repair inside the image is possible. Copy the
directory in each derivation that ships the code (the framework tree, the skill/deployment
tree, and any image built from either), and resolve the asset relative to the code rather than
from a machine path — the same shape the store copy preserves. The general form is worth
stating because it generalises past verbs: **an explicit list of what ships is only as complete
as the things it enumerates**, so pair it with an assertion about the directories the code
*reads*, not just the files it *executes* — a check that resolves one asset the way the code
resolves it fails the gate instead of the user.
